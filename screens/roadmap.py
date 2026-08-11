"""
Product Roadmap screen
(design doc: AI PM Copilot Multi-Agent System Design -> "9. Roadmap Agent")

Deterministic quarterly board (manual scheduling, status tracking) plus an
optional "Run AI Roadmap Planning" action that calls the Roadmap Planner
agent in src/roadmap_agent.py (via utils.helpers.run_ai_roadmap_planning)
to schedule the top unscheduled prioritized features: quarter, sprint,
dependencies, and milestone flag. Release order is computed deterministically
from those dependencies via topological_sequence() and shown as a
"Release order" number on every card, so both AI-planned and manually-added
items stay consistently sequenced.
"""
import streamlit as st
import pandas as pd
import datetime as dt

from src.db import execute
from utils.helpers import (
    ws_id, fetch_features, fetch_roadmap, fetch_prioritized_backlog,
    ROADMAP_STATUSES, priority_bucket, run_ai_roadmap_planning, resequence_roadmap,
)

_QUARTERS = ["Q1", "Q2", "Q3", "Q4"]


def _inject_css():
    st.markdown("""
        <style>
        .rm-badge {
            display:inline-block; border-radius:999px; padding:2px 10px;
            font-size:11px; font-weight:600; margin-right: 6px;
        }
        </style>
    """, unsafe_allow_html=True)


def show_roadmap():
    st.markdown("## Product Roadmap")
    st.caption(
        "Place prioritized features onto a quarterly roadmap. Quarter, sprint, dependencies, and "
        "milestone flags can be set manually or planned automatically by the Roadmap Planner agent, "
        "which also determines release order from whatever dependencies exist."
    )
    _inject_css()
    st.write("")

    features = fetch_features()
    roadmap = fetch_roadmap()

    # -----------------------------
    # KPI Cards (derived from real roadmap data)
    # -----------------------------
    total_initiatives = len(roadmap)
    in_progress = int((roadmap["status"] == "In Progress").sum()) if not roadmap.empty else 0
    completed = int((roadmap["status"] == "Completed").sum()) if not roadmap.empty else 0
    milestones = int(roadmap["is_milestone"].fillna(0).astype(int).sum()) if not roadmap.empty else 0

    high_priority_count = 0
    if not roadmap.empty and not features.empty:
        backlog = fetch_prioritized_backlog()
        scheduled_feature_ids = set(roadmap["feature_id"].dropna().tolist())
        scheduled = backlog[backlog["feature_id"].isin(scheduled_feature_ids)]
        high_priority_count = int((scheduled["rice_score"].apply(priority_bucket) == "High").sum())

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Planned", str(total_initiatives))
    c2.metric("In Progress", str(in_progress))
    c3.metric("Completed", str(completed))
    c4.metric("High Priority", str(high_priority_count))
    c5.metric("Milestones", str(milestones))

    st.write("")

    # -----------------------------
    # Roadmap Planning Agent
    # -----------------------------
    run_col, _ = st.columns([1, 3])
    with run_col:
        run_clicked = st.button(
            "Run AI Roadmap Planning", type="primary", use_container_width=True,
            help="Schedules the top 10 unscheduled prioritized features onto the roadmap: "
                 "quarter, sprint, dependencies, and milestone flag.",
        )

    if run_clicked:
        with st.spinner("Roadmap Planner is scheduling the backlog..."):
            summary, error = run_ai_roadmap_planning(top_n=10)
        if summary is None:
            st.info(error)
        elif error:
            st.warning(
                f"AI planning unavailable for this run -- all {summary['fallback']} of "
                f"{summary['total']} features used a default quarter assignment instead.\n\n"
                f"**Reason:** {error}\n\n"
                "Note: this agent runs through CrewAI/LiteLLM (`src/roadmap_agent.py`), the same "
                "code path as the Theme Extraction Agent and Prioritization Engine -- if those "
                "also fail, the cause is usually a missing `GEMINI_API_KEY` or an outdated "
                "`crewai`/`litellm` pin."
            )
        else:
            st.success(f"Scheduled {summary['planned']} of {summary['total']} features with AI planning.")
        st.rerun()

    st.write("")

    # -----------------------------
    # Schedule a feature manually
    # -----------------------------
    if st.button("Add Initiative", type="secondary"):
        st.session_state.show_form = True

    if st.session_state.get("show_form", False):
        if features.empty:
            st.warning("No feature requests yet -- these are auto-created once feedback is classified. "
                       "Reload the dataset from **Settings -> Data** if the database is empty.")
        else:
            already_scheduled = roadmap[["feature_id", "title"]].dropna() if not roadmap.empty else pd.DataFrame()
            dependency_options = ["None"] + already_scheduled["title"].tolist()

            with st.form("roadmap_form", clear_on_submit=True):
                title = st.selectbox("Feature", features["title"].tolist())
                q_col, s_col = st.columns(2)
                quarter = q_col.selectbox("Target quarter", _QUARTERS)
                sprint = s_col.number_input("Sprint", min_value=1, max_value=6, value=1)
                c1, c2 = st.columns(2)
                start = c1.date_input("Start date", value=dt.date.today())
                end = c2.date_input("End date", value=dt.date.today() + dt.timedelta(days=30))
                depends_on_title = st.selectbox(
                    "Depends on (optional)", dependency_options,
                    help="If this item is blocked by another roadmap item, pick it here -- "
                         "release order will keep it scheduled after its dependency.",
                )
                is_milestone = st.checkbox("Mark as milestone")
                submit = st.form_submit_button("Add to roadmap")

                if submit:
                    feature_row = features[features["title"] == title].iloc[0]
                    depends_on_feature_id = None
                    if depends_on_title != "None" and not already_scheduled.empty:
                        match = already_scheduled[already_scheduled["title"] == depends_on_title]
                        if not match.empty:
                            depends_on_feature_id = int(match.iloc[0]["feature_id"])

                    execute(
                        """INSERT INTO roadmap_items
                           (workspace_id, feature_id, title, quarter, start_date, end_date, status,
                            sprint, depends_on_feature_id, is_milestone)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (ws_id(), int(feature_row["id"]), title, quarter, str(start), str(end), "Planned",
                         f"Sprint {int(sprint)}", depends_on_feature_id, int(is_milestone)),
                    )
                    resequence_roadmap()
                    st.session_state.show_form = False
                    st.session_state.roadmap_success = f"'{title}' added to {quarter}."
                    st.rerun()

    success_msg = st.session_state.pop("roadmap_success", None)
    if success_msg:
        st.success(success_msg)

    st.write("")

    # -----------------------------
    # Roadmap Columns (grouped by quarter, real data)
    # -----------------------------
    if roadmap.empty:
        st.info("Nothing scheduled yet -- add a feature above or run AI Roadmap Planning.")
    else:
        title_by_feature_id = {
            int(row["id"]): row["title"] for _, row in features.iterrows()
        } if not features.empty else {}
        description_by_feature_id = {
            int(row["id"]): row["description"] for _, row in features.iterrows()
        } if not features.empty else {}

        cols = st.columns(len(_QUARTERS))
        for col, quarter in zip(cols, _QUARTERS):
            items = roadmap[roadmap["quarter"] == quarter].sort_values(
                "sequence_rank", na_position="last"
            )
            with col:
                st.subheader(quarter)
                if items.empty:
                    st.caption("No initiatives yet.")
                for _, item in items.iterrows():
                    with st.container(border=True):
                        # roadmap_items.title is a short label copied in at scheduling
                        # time; show the full, untruncated feedback text instead (same
                        # fix as the Prioritization Engine page) so the card never ends
                        # mid-sentence.
                        feature_id = int(item["feature_id"]) if pd.notna(item.get("feature_id")) else None
                        full_text = (
                            description_by_feature_id.get(feature_id) or item["title"]
                        ).strip() if feature_id else item["title"]

                        st.write(f"**{full_text}**")
                        st.caption(f"{item['start_date']} -> {item['end_date']}")

                        # A full-width row for the status dropdown -- squeezing it into
                        # a narrow side column cut off both the selected value and every
                        # option in the dropdown list (e.g. "Planne", "In Prog").
                        new_status = st.selectbox(
                            "Status", ROADMAP_STATUSES,
                            index=ROADMAP_STATUSES.index(item["status"]) if item["status"] in ROADMAP_STATUSES else 0,
                            key=f"rm_status_{item['id']}",
                        )
                        if new_status != item["status"]:
                            execute("UPDATE roadmap_items SET status = ? WHERE id = ?", (new_status, int(item["id"])))
                            st.rerun()

                        badges = []
                        if item.get("sprint"):
                            badges.append(("Sprint", item["sprint"].replace("Sprint ", ""), "#6366F1"))
                        if pd.notna(item.get("sequence_rank")):
                            badges.append(("Order", f"#{int(item['sequence_rank'])}", "#0EA5E9"))
                        if int(item.get("is_milestone") or 0):
                            badges.append(("Milestone", None, "#F59E0B"))
                        if badges:
                            badge_html = "".join(
                                f'<span class="rm-badge" style="background:{color}22;color:{color};">'
                                f'{label if value is None else label + " " + str(value)}</span>'
                                for label, value, color in badges
                            )
                            st.markdown(badge_html, unsafe_allow_html=True)

                        depends_on = item.get("depends_on_feature_id")
                        if pd.notna(depends_on) and int(depends_on) in title_by_feature_id:
                            dep_id = int(depends_on)
                            dep_text = description_by_feature_id.get(dep_id) or title_by_feature_id[dep_id]
                            st.caption(f"Depends on: {dep_text}")

                        if item.get("ai_rationale"):
                            st.caption(item["ai_rationale"])

                        if st.button("Remove", key=f"remove_{item['id']}", use_container_width=True):
                            execute("DELETE FROM roadmap_items WHERE id = ?", (int(item["id"]),))
                            resequence_roadmap()
                            st.rerun()

        st.write("")
        st.subheader("Items per quarter")
        st.bar_chart(roadmap["quarter"].value_counts())