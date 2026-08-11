"""
AI-Based Prioritization & Impact Analysis Engine panel
(design doc: AI PM Copilot Multi-Agent System Design -> "7. Prioritization Agent")

Mirrors screens/theme_extraction_panel.py: a fast deterministic view (the
backlog sorted by whatever RICE scores already exist — computed instantly
via the votes-based heuristic in utils.helpers.ensure_rice_score, no LLM
call needed) plus an optional "Run AI Impact Analysis" action that calls
the CrewAI-based Impact & Risk Analyst agent in src/prioritization_engine.py
(via utils.helpers.run_ai_prioritization_engine) to (re)score impact,
effort, confidence, and risk for the top features by votes, then derives
RICE, ICE, and a priority recommendation from those scores.
"""
import streamlit as st
import pandas as pd

from utils.helpers import (
    fetch_features, fetch_prioritized_backlog, ensure_rice_score, run_ai_prioritization_engine,
)
from src.prioritization_engine import recommend_priority

_RISK_COLORS = {"Low": "#22C55E", "Medium": "#F59E0B", "High": "#EF4444"}
_PRIORITY_COLORS = {"High": "#EF4444", "Medium": "#F59E0B", "Low": "#22C55E"}


def _inject_css():
    st.markdown("""
        <style>
        .prio-title { font-size: 15px; font-weight: 700; color: var(--pm-navy); margin-bottom: 2px; }
        .prio-badge {
            display:inline-block; border-radius:999px; padding:2px 10px;
            font-size:11px; font-weight:600; margin-right: 6px;
        }
        </style>
    """, unsafe_allow_html=True)


def show_prioritization_engine():
    st.subheader("AI-Based Prioritization & Impact Analysis Engine")
    st.caption(
        "Ranks feature opportunities by RICE and ICE score. Reach comes straight from customer "
        "votes; Impact, Effort, Confidence, and Risk are estimated by the Impact & Risk Analyst "
        "agent (falls back to a votes-based default if the AI call is unavailable)."
    )
    _inject_css()

    features = fetch_features()
    if features.empty:
        st.info("No feature requests yet — they appear automatically once feedback is ingested and classified.")
        return

    # Make sure every feature has at least a heuristic RICE score so the
    # table is never empty, same pattern Reports already uses.
    for _, row in features.iterrows():
        ensure_rice_score(row)

    head_col, btn_col = st.columns([3, 1])
    with head_col:
        st.markdown('<div class="prio-title">Prioritized Backlog</div>', unsafe_allow_html=True)
        st.caption("Sorted by RICE score, highest first.")
    with btn_col:
        run_clicked = st.button(
            "Run AI Impact Analysis", use_container_width=True,
            help="Runs the Impact & Risk Analyst agent to score impact, effort, confidence, "
                 "and risk for the top 15 features by customer votes."
        )

    if run_clicked:
        with st.spinner("Impact & Risk Analyst is scoring the backlog..."):
            summary, error = run_ai_prioritization_engine(top_n=15)
        if summary is None:
            st.warning(f"Couldn't analyze the backlog: {error}")
        elif error:
            st.warning(
                f"AI scoring unavailable for this run — all {summary['fallback']} of "
                f"{summary['total']} features used the default estimate instead.\n\n"
                f"**Reason:** {error}\n\n"
                "Note: this agent runs through CrewAI/LiteLLM (`src/prioritization_engine.py`), "
                "the same code path as the Theme Extraction Agent — if that agent also fails, "
                "the cause is usually a missing `GEMINI_API_KEY` or an outdated `crewai`/`litellm` pin."
            )
        else:
            st.success(
                f"Scored {summary['analyzed']} of {summary['total']} features with AI "
                f"({summary['fallback']} used the default estimate)."
            )

    backlog = fetch_prioritized_backlog().sort_values("rice_score", ascending=False, na_position="last")
    if backlog.empty:
        st.caption("No prioritized features yet.")
        return

    for _, row in backlog.iterrows():
        risk = row.get("risk_level") or "Medium"
        risk_color = _RISK_COLORS.get(risk, "#9CA3AF")
        priority = recommend_priority(row.get("rice_score"), risk)
        priority_color = _PRIORITY_COLORS.get(priority, "#9CA3AF")

        # Feature titles are shortened for use elsewhere in the app (e.g. the
        # Dashboard's "Top Requested Features" list), so show the full,
        # untruncated feedback text here instead — that's what was reading as
        # cut off mid-sentence on this page.
        full_text = (row.get("description") or row["title"] or "").strip()

        with st.container(border=True):
            top_c1, top_c2, top_c3 = st.columns([3, 1, 1])
            with top_c1:
                st.markdown(f"**{full_text}**")
                st.caption(f"{row['theme'] or 'Unclassified'} · {int(row['votes'])} votes")
            with top_c2:
                st.metric("RICE", f"{row['rice_score']:.0f}" if pd.notna(row["rice_score"]) else "—")
            with top_c3:
                st.metric("ICE", f"{row['ice_score']:.1f}" if pd.notna(row.get("ice_score")) else "—")

            st.markdown(
                f'<span class="prio-badge" style="background:{risk_color}22;color:{risk_color};">'
                f'{risk} risk</span>'
                f'<span class="prio-badge" style="background:{priority_color}22;color:{priority_color};">'
                f'{priority} priority</span>',
                unsafe_allow_html=True,
            )

            if row.get("ai_rationale"):
                st.caption(row["ai_rationale"])