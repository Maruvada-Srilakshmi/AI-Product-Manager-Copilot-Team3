"""
Theme Extraction Agent panel (design doc: Theme Agent — topic extraction,
theme classification, sentiment analysis, pain point identification, intent
detection).

This module owns everything needed to render the Theme Extraction Agent as a
self-contained panel: its own CSS, its own color maps, and its own render
function. It has no dependency on any specific screen — `render()` can be
dropped into the Dashboard, its own page, or anywhere else in the app by
importing this module and calling `render()`.

Data flow:
 - The base Theme | Frequency table renders instantly from feedback already
   classified during ingestion (`utils.helpers.theme_frequency_table`) — no
   LLM call needed.
 - An optional "Enrich with AI" action calls the CrewAI-based agent in
   `src/theme_agent.py` (via `utils.helpers.run_theme_agent_enrichment`) to
   add sentiment, a pain-point summary, and detected intent per theme.
"""
import streamlit as st

from utils.helpers import theme_frequency_table, run_theme_agent_enrichment

_SENTIMENT_COLORS = {"Positive": "#22C55E", "Neutral": "#F59E0B", "Negative": "#EF4444"}
_INTENT_COLORS = {
    "Bug Report": "#EF4444",
    "Complaint": "#F97316",
    "Feature Request": "#6366F1",
    "Question": "#0EA5E9",
    "Praise": "#22C55E",
}


def _inject_css():
    st.markdown("""
        <style>
        .theme-agent-title {
            font-size: 15px;
            font-weight: 700;
            color: var(--pm-navy);
            margin-bottom: 2px;
        }
        .theme-row {
            padding: 10px 0;
            border-bottom: 1px solid var(--pm-border);
        }
        .theme-row:last-child {
            border-bottom: none;
        }
        .theme-row-head {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 14px;
            color: var(--pm-text);
        }
        .theme-freq {
            background: var(--pm-primary-light);
            color: var(--pm-primary);
            font-weight: 700;
            border-radius: 6px;
            padding: 1px 8px;
            font-size: 12px;
        }
        .theme-meta {
            font-size: 12px;
            color: var(--pm-text-muted);
            margin-top: 3px;
        }
        .intent-badge {
            display: inline-block;
            border-radius: 999px;
            padding: 1px 8px;
            font-size: 11px;
            font-weight: 600;
            margin-right: 6px;
        }
        </style>
    """, unsafe_allow_html=True)


def render():
    """Renders the Theme Extraction Agent panel. Call this from any screen."""
    _inject_css()

    with st.container(border=True):
        head_col, btn_col = st.columns([3, 1])
        with head_col:
            st.markdown('<div class="theme-agent-title">🧠 Theme Extraction Agent</div>', unsafe_allow_html=True)
            st.caption("Recurring customer pain points, clustered from feedback.")
        with btn_col:
            enrich_clicked = st.button("✨ Enrich with AI", use_container_width=True,
                                        help="Runs the Theme Extraction Agent to add sentiment, "
                                             "pain points, and intent for each theme.")

        freq = theme_frequency_table()
        if freq.empty:
            st.caption("No classified feedback yet — themes appear once feedback is ingested.")
            return

        if enrich_clicked:
            with st.spinner("Theme Extraction Agent is analyzing themes..."):
                enriched, error = run_theme_agent_enrichment(top_n=len(freq))
            st.session_state["theme_agent_result"] = enriched
            st.session_state["theme_agent_error"] = error
            if enriched is None:
                st.warning(
                    f"AI enrichment failed — showing the frequency table only.\n\n"
                    f"**Reason:** {error or 'Unknown error.'}\n\n"
                    "Note: this agent runs through CrewAI/LiteLLM (`src/theme_agent.py`), which is "
                    "a *different* code path from the direct Gemini SDK call used by "
                    "**Settings → Test Gemini connection** — so that test can pass while this "
                    "still fails (e.g. an older `crewai`/`litellm` pin not yet recognizing the "
                    "`gemini-3.5-flash` / `gemini-3.1-flash-lite` model IDs). Try "
                    "`pip install -U crewai litellm` if the reason above looks like a "
                    "model-not-found error rather than a key/auth error."
                )

        enriched = st.session_state.get("theme_agent_result")
        enriched_by_theme = {e["theme"]: e for e in enriched} if enriched else {}

        for _, row in freq.iterrows():
            theme, frequency = row["theme"], int(row["frequency"])
            info = enriched_by_theme.get(theme)

            if info:
                s_color = _SENTIMENT_COLORS.get(info["sentiment"], "#9CA3AF")
                i_color = _INTENT_COLORS.get(info["intent"], "#9CA3AF")
                meta_html = (
                    f'<div class="theme-meta">'
                    f'<span class="intent-badge" style="background:{i_color}22;color:{i_color};">{info["intent"]}</span>'
                    f'<span style="color:{s_color};">●</span> {info["sentiment"]} &nbsp;·&nbsp; '
                    f'Pain point: {info["pain_points"]}'
                    f'</div>'
                )
            else:
                meta_html = ""

            st.markdown(
                f'<div class="theme-row">'
                f'<div class="theme-row-head"><span>{theme}</span>'
                f'<span class="theme-freq">{frequency}</span></div>'
                f'{meta_html}'
                f'</div>',
                unsafe_allow_html=True,
            )
