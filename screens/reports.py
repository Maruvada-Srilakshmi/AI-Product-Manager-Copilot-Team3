import streamlit as st

from src.db import fetch_df, execute, now
from src.llm import generate_prd, generate_executive_summary, generate_quick_prd_from_feedback
from utils.helpers import (
    ws_id, fetch_feedback, fetch_features, fetch_documents,
    fetch_prioritized_backlog, ensure_rice_score, priority_bucket,
    schedule_feature_on_roadmap,
)


def _inject_css():
    st.markdown("""
        <style>
        .report-title-row {
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 4px;
        }
        .report-title {
            font-size: 15.5px;
            font-weight: 700;
            color: var(--pm-navy);
            line-height: 1.45;
        }
        .doc-type-chip {
            font-size: 10.5px;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            color: var(--pm-text-muted);
            background: var(--pm-bg-soft);
            border: 1px solid var(--pm-border);
            border-radius: 6px;
            padding: 2px 8px;
            white-space: nowrap;
        }
        .report-meta {
            font-size: 12px;
            color: var(--pm-text-muted);
        }
        .report-badge-wrap {
            text-align: right;
            padding-top: 3px;
        }
        .priority-badge {
            display: inline-block;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.02em;
            padding: 4px 14px;
            border-radius: 20px;
            white-space: nowrap;
        }
        .priority-high { background: var(--pm-red-bg); color: var(--pm-red); }
        .priority-medium { background: var(--pm-amber-bg); color: var(--pm-amber); }
        .priority-low { background: var(--pm-green-bg); color: var(--pm-green); }
        </style>
    """, unsafe_allow_html=True)


def _priority_class(priority):
    return {"High": "priority-high", "Medium": "priority-medium", "Low": "priority-low"}.get(priority, "priority-medium")


def _normalize_text(text: str) -> str:
    """Lowercases and collapses whitespace so two mentions of the same
    feedback (typed differently, pasted with extra spaces, etc.) compare
    as equal instead of only matching on an exact, case-sensitive string."""
    return " ".join((text or "").strip().lower().split())


def _generate_and_save_prd(target):
    """
    Drafts and saves a PRD for a single feature request, then schedules it
    onto the roadmap. Shared by the "+ Generate New PRD" flow (which picks
    the target automatically) and the "Generate PRD" button on the
    Prioritization Engine (which passes a specific feature). Leaves the
    caller to call st.rerun() afterwards.
    """
    theme_feedback = fetch_df(
        "SELECT text FROM feedback WHERE workspace_id = ? AND theme = ?", (ws_id(), target["theme"])
    )
    samples = theme_feedback["text"].tolist()

    with st.spinner(f"Drafting PRD for '{target.get('description') or target['title']}'..."):
        prd = generate_prd(target["title"], target["description"] or "", target["theme"] or "General", samples)
    execute(
        "INSERT INTO documents (workspace_id, doc_type, title, content, created_at) VALUES (?,?,?,?,?)",
        (ws_id(), "PRD", target["title"], prd, now()),
    )

    with st.spinner("Scheduling onto the roadmap..."):
        roadmap_item, roadmap_error = schedule_feature_on_roadmap(
            int(target["id"]), target["title"], target.get("theme"), int(target["votes"])
        )
    st.session_state["last_roadmap_addition"] = {
        "title": target["title"], "item": roadmap_item, "error": roadmap_error,
    }
    st.session_state["prd_success"] = f"New PRD generated for '{target.get('description') or target['title']}'!"


def show_reports():
    _inject_css()

    feedback = fetch_feedback()
    features = fetch_features()
    # Reports owns PRDs, User Stories, and Executive Summaries -- Roadmap
    # documents (the AI-generated 2-Sprint Implementation Roadmap) are
    # generated and displayed on the Roadmap page instead, so they're
    # excluded here rather than leaking into "PRD Documents" below just
    # because they live in the same shared `documents` table.
    docs = fetch_documents()
    docs = docs[docs["doc_type"] != "Roadmap"] if not docs.empty else docs

    # feature_requests.title is truncated to ~70 characters (with an
    # ellipsis) for compact use elsewhere in the app (e.g. the Dashboard's
    # chart legend); documents inherit that same truncated title as their
    # key. Displayed here at full card/dropdown width that reads as a
    # sentence cut off mid-way, so anywhere a title would be shown as prose
    # below uses this lookup to show the full, untruncated feedback text
    # instead. The (truncated) title itself is still used as the matching
    # key everywhere -- only the displayed text changes.
    title_to_full = {}
    if not features.empty:
        for _, f in features.iterrows():
            title_to_full[f["title"]] = (f.get("description") or f["title"] or "").strip()

    def full_text(title):
        return title_to_full.get(title, title)

    header_col, btn_col = st.columns([5, 1.4])
    with header_col:
        st.markdown("### PRD Generation")
        st.caption("AI-generated insights and documents, generated by the real Gemini/CrewAI backend "
                    "(falls back to an offline template if no GEMINI_API_KEY is configured).")
    with btn_col:
        st.write("")
        gen_clicked = st.button("+ Generate New PRD", type="primary", use_container_width=True,
                                 disabled=features.empty)
        if features.empty:
            st.caption("No feature requests in the database yet.")

    # Arriving here via the "Generate PRD" button on the Prioritization
    # Engine (screens/prioritization_engine.py) drops the chosen feature's
    # id in session state instead of always auto-picking the top-voted
    # feature, so that specific feature's PRD gets drafted right away.
    #
    # This runs inline (no st.rerun() afterwards) and re-reads `docs` right
    # after, so the rest of this same page render already reflects the new
    # PRD. Rerunning here instead would bounce through a second navigation
    # -- Streamlit keeps the previous page's elements on screen (dimmed)
    # until a run finishes, so an extra rerun after an already-slow AI call
    # meant the Prioritization Engine's cards stayed visible underneath the
    # spinner for a second time, reading as "stuck on the old page".
    target_feature_id = st.session_state.pop("prd_target_feature_id", None)
    if target_feature_id is not None and not features.empty:
        target_match = features[features["id"] == target_feature_id]
        if not target_match.empty:
            _generate_and_save_prd(target_match.iloc[0])
            docs = fetch_documents()
            docs = docs[docs["doc_type"] != "Roadmap"] if not docs.empty else docs

    if gen_clicked and not features.empty:
        # Generate for the highest-voted feature request that doesn't have a PRD yet, else the top one.
        docs_titles = set(docs["title"]) if not docs.empty else set()
        candidates = features[~features["title"].isin(docs_titles)]
        target = candidates.iloc[0] if not candidates.empty else features.iloc[0]
        _generate_and_save_prd(target)
        docs = fetch_documents()
        docs = docs[docs["doc_type"] != "Roadmap"] if not docs.empty else docs

    st.write("")

    tab_prd, tab_summary, tab_insights = st.tabs(
        ["PRD Documents", "Executive Summary", "Feedback Insights"]
    )

    # -----------------------------
    # PRD Documents (real: src/db `documents` table, generated via src/llm)
    # -----------------------------
    with tab_prd:
        prd_success = st.session_state.pop("prd_success", None)
        if prd_success:
            st.success(prd_success)

        # Shows what the PRD -> Roadmap handoff just did, right after a PRD
        # is generated (either flow below), so the roadmap placement is
        # visible immediately instead of only discoverable by navigating
        # away to the Roadmap page.
        roadmap_addition = st.session_state.pop("last_roadmap_addition", None)
        if roadmap_addition:
            item = roadmap_addition["item"]
            with st.container(border=True):
                st.markdown(f"**Added to Roadmap: {full_text(roadmap_addition['title'])}**")
                if item is not None:
                    sprint_label = item.get("sprint") or "Sprint 1"
                    milestone_note = " -- flagged as a milestone" if int(item.get("is_milestone") or 0) else ""
                    st.caption(f"{item.get('quarter')}, {sprint_label}{milestone_note}")
                    if item.get("ai_rationale"):
                        st.caption(item["ai_rationale"])
                if roadmap_addition["error"]:
                    st.caption(f"AI planning unavailable this time (used a default quarter/sprint): {roadmap_addition['error']}")
                if st.button("View on Roadmap", key="jump_to_roadmap"):
                    # See the comment in app.py above the sidebar radio --
                    # "nav_page" can't be set directly here since that widget
                    # already exists in this run; "nav_target" is applied to
                    # it at the top of app.py on the next run instead.
                    st.session_state["nav_target"] = "Roadmap"
                    st.query_params["page"] = "Roadmap"
                    st.rerun()

        # -----------------------------
        # Quick PRD from raw feedback (ported from Team3_AICopilot_backend's
        # Feedback -> Feature -> Priority -> PRD agent chain). Doesn't need
        # feedback to already be ingested/classified -- paste anything.
        # -----------------------------
        with st.expander("Quick PRD from raw feedback (no ingestion needed)"):
            st.caption(
                "Paste raw customer feedback, support tickets, or a feature ask. This runs it through "
                "a 4-agent chain (Feedback -> Feature -> Priority -> PRD) and drafts a mini-PRD directly, "
                "without needing the text to already be in the database."
            )
            quick_text = st.text_area(
                "Raw feedback / support tickets / feature ask",
                height=140,
                placeholder="e.g. Users complaining that export takes 3 minutes and times out on 5000 rows. "
                             "Requesting async email export.",
                key="quick_prd_input",
            )
            if st.button("Generate Mini-PRD", key="quick_prd_button", disabled=not quick_text.strip()):
                with st.spinner("Running Feedback -> Feature -> Priority -> PRD agents..."):
                    stages = generate_quick_prd_from_feedback(quick_text.strip())
                st.session_state["quick_prd_stages"] = stages

            stages = st.session_state.get("quick_prd_stages")
            if stages:
                prd_stage = next((s for s in stages if s["stage"] == "PRD"), stages[-1])
                if len(stages) > 1:
                    stage_tabs = st.tabs([s["stage"] for s in stages])
                    for stab, s in zip(stage_tabs, stages):
                        with stab:
                            st.markdown(s["output"])
                else:
                    st.markdown(prd_stage["output"])

                title_guess = quick_text.strip().splitlines()[0][:60] if quick_text.strip() else "Quick PRD"
                if st.button("Save PRD to documents", key="save_quick_prd"):
                    execute(
                        "INSERT INTO documents (workspace_id, doc_type, title, content, created_at) VALUES (?,?,?,?,?)",
                        (ws_id(), "PRD", title_guess, prd_stage["output"], now()),
                    )

                    # Quick PRDs aren't tied to an existing feature request
                    # (the text is pasted raw), so create one if it doesn't
                    # already exist -- the roadmap needs a feature_id to
                    # schedule against, same as the main PRD flow above.
                    # Matched by normalized feedback text (not by title):
                    # titles here are the first 60 chars of the pasted text,
                    # while a feature already ingested through the normal
                    # pipeline gets its title from _truncate_title (a
                    # different 70-char cut), so the same feedback produces
                    # two different-looking titles and a title-only match
                    # missed the existing feature, creating a duplicate.
                    quick_norm = _normalize_text(quick_text)
                    if not features.empty:
                        existing_mask = features["description"].fillna(features["title"]).apply(
                            lambda t: _normalize_text(t) == quick_norm
                        )
                        existing_feature = features[existing_mask]
                    else:
                        existing_feature = features
                    if existing_feature.empty:
                        execute(
                            """INSERT INTO feature_requests
                               (workspace_id, title, description, votes, theme, status, created_at)
                               VALUES (?,?,?,?,?,?,?)""",
                            (ws_id(), title_guess, quick_text.strip(), 1, "Quick PRD", "New", now()),
                        )
                        new_feature = fetch_df(
                            "SELECT * FROM feature_requests WHERE workspace_id = ? AND title = ? "
                            "ORDER BY id DESC LIMIT 1",
                            (ws_id(), title_guess),
                        ).iloc[0]
                    else:
                        new_feature = existing_feature.iloc[0]

                    with st.spinner("Scheduling onto the roadmap..."):
                        roadmap_item, roadmap_error = schedule_feature_on_roadmap(
                            int(new_feature["id"]), title_guess, new_feature.get("theme"),
                            int(new_feature.get("votes") or 1),
                        )
                    st.session_state["last_roadmap_addition"] = {
                        "title": title_guess, "item": roadmap_item, "error": roadmap_error,
                    }
                    st.session_state.pop("quick_prd_stages", None)
                    st.session_state["prd_success"] = "Saved to PRD Documents below."
                    st.rerun()

        st.write("")

        if docs.empty:
            st.info("No PRDs generated yet. Click **+ Generate New PRD** above once you have feature requests.")
        for i, doc in docs.reset_index(drop=True).iterrows():
            # derive a priority badge from RICE (if the doc's title matches a scored feature)
            match = features[features["title"] == doc["title"]]
            rice = None
            if not match.empty:
                scored = ensure_rice_score(match.iloc[0])
                rice = scored.get("rice_score")
            badge = priority_bucket(rice)

            with st.container(border=True):
                title_col, badge_col = st.columns([5, 1.4])
                with title_col:
                    st.markdown(f"""
                        <div class="report-title-row">
                            <span class="report-title">{full_text(doc['title'])}</span>
                            <span class="doc-type-chip">{doc['doc_type']}</span>
                        </div>
                        <div class="report-meta">Generated on {str(doc['created_at'])[:10]}</div>
                    """, unsafe_allow_html=True)
                with badge_col:
                    st.markdown(f"""
                        <div class="report-badge-wrap">
                            <span class="priority-badge {_priority_class(badge)}">{badge} Priority</span>
                        </div>
                    """, unsafe_allow_html=True)

                st.write("")
                v_col, d_col, r_col, _ = st.columns([1, 1, 1, 4])
                with v_col:
                    if st.button("View", key=f"view_prd_{doc['id']}", use_container_width=True):
                        st.session_state.active_prd_view = (
                            None if st.session_state.get("active_prd_view") == doc["id"] else doc["id"]
                        )
                with d_col:
                    st.download_button(
                        "Download", doc["content"],
                        file_name=f"{doc['doc_type']}_{doc['title'][:30]}.md", mime="text/markdown",
                        key=f"download_prd_{doc['id']}", use_container_width=True,
                    )
                with r_col:
                    if st.button("Remove", key=f"remove_prd_{doc['id']}", use_container_width=True):
                        execute("DELETE FROM documents WHERE id = ? AND workspace_id = ?", (doc["id"], ws_id()))
                        st.session_state.pop("active_prd_view", None)
                        st.success(f"Removed '{full_text(doc['title'])}'.")
                        st.rerun()

                if st.session_state.get("active_prd_view") == doc["id"]:
                    st.write("")
                    st.markdown(doc["content"])

            st.write("")

    # -----------------------------
    # Executive Summary (real: computed metrics + src/llm.generate_executive_summary)
    # -----------------------------
    with tab_summary:
        total_fb = len(feedback)
        high_priority = 0
        avg_sentiment = None
        if not feedback.empty and feedback["sentiment_score"].notna().any():
            avg_sentiment = round(float(feedback["sentiment_score"].dropna().mean()), 2)
        if not features.empty:
            backlog = fetch_prioritized_backlog()
            high_priority = int((backlog["rice_score"].apply(priority_bucket) == "High").sum())

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Feedback", f"{total_fb:,}")
        c2.metric("High Priority Features", str(high_priority))
        c3.metric("Avg. Sentiment Score", f"{avg_sentiment}" if avg_sentiment is not None else "—")
        c4.metric("PRDs Generated", str(len(docs[docs["doc_type"] == "PRD"])) if not docs.empty else "0")

        st.write("")
        if st.button("Generate AI executive summary", type="primary"):
            context_parts = []
            if not feedback.empty:
                context_parts.append(
                    f"Total feedback items: {total_fb}. "
                    f"Sentiment split: {feedback['sentiment'].value_counts().to_dict() if feedback['sentiment'].notna().any() else 'not classified yet'}. "
                    f"Top themes: {feedback['theme'].value_counts().head(5).to_dict() if feedback['theme'].notna().any() else 'not classified yet'}."
                )
            if not features.empty:
                context_parts.append(
                    f"Feature requests tracked: {len(features)}. "
                    f"Status breakdown: {features['status'].value_counts().to_dict()}."
                )
            backlog = fetch_prioritized_backlog()
            if not backlog.empty and backlog["rice_score"].notna().any():
                top5 = backlog.sort_values("rice_score", ascending=False).head(5)
                context_parts.append("Top prioritized features by RICE score: " + ", ".join(
                    f"{r.title} ({r.rice_score:.1f})" for r in top5.itertuples() if r.rice_score
                ))
            context = "\n".join(context_parts) if context_parts else "No data has been ingested into this workspace yet."

            with st.spinner("Writing executive summary..."):
                summary = generate_executive_summary(context)
            st.session_state["exec_summary"] = summary

        if st.session_state.get("exec_summary"):
            with st.container(border=True):
                st.markdown(st.session_state["exec_summary"])
            save_col, download_col, _ = st.columns([1, 1, 3])
            with save_col:
                if st.button("Save summary", key="save_exec_summary"):
                    execute(
                        "INSERT INTO documents (workspace_id, doc_type, title, content, created_at) VALUES (?,?,?,?,?)",
                        (ws_id(), "Executive Summary", f"Executive Summary — {str(now())[:10]}",
                         st.session_state["exec_summary"], now()),
                    )
                    st.success("Saved to PRD Documents.")
            with download_col:
                st.download_button("Download summary", st.session_state["exec_summary"],
                                    file_name="executive_summary.md", mime="text/markdown",
                                    key="download_exec_summary")

    # -----------------------------
    # Feedback Insights (real: from the `feedback` table)
    # -----------------------------
    with tab_insights:
        with st.container(border=True):
            st.subheader("Top Issues")
            if not feedback.empty and feedback["theme"].notna().any():
                neg = feedback[feedback["sentiment"] == "Negative"]
                for theme, count in neg["theme"].value_counts().head(5).items():
                    st.write(f"• {theme} — {count} mentions")
            else:
                st.caption("No classified feedback in the database yet.")

        with st.container(border=True):
            st.subheader("Top Requested Features")
            if not features.empty:
                for _, row in features.head(5).iterrows():
                    st.write(f"• {full_text(row['title'])} — {row['votes']} requests")
            else:
                st.caption("No feature requests tracked yet.")

        with st.container(border=True):
            st.subheader("Sentiment Breakdown")
            if not feedback.empty and feedback["sentiment"].notna().any():
                counts = feedback["sentiment"].value_counts()
                total = counts.sum()
                c1, c2, c3 = st.columns(3)
                c1.metric("Positive", f"{round(100 * counts.get('Positive', 0) / total)}%")
                c2.metric("Neutral", f"{round(100 * counts.get('Neutral', 0) / total)}%")
                c3.metric("Negative", f"{round(100 * counts.get('Negative', 0) / total)}%")
            else:
                st.caption("No classified feedback yet.")