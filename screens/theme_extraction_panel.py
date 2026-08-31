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
_INTENT_PLAIN = {
    "Bug Report": "Reporting something broken",
    "Complaint": "Unhappy about something",
    "Feature Request": "Asking for something new",
    "Question": "Asking how something works",
    "Praise": "Sharing positive feedback",
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
        .theme-card {
            border: 1px solid var(--pm-border);
            border-radius: 10px;
            padding: 14px 16px;
            margin-bottom: 10px;
        }
        .theme-card-head {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .theme-name {
            font-size: 15px;
            font-weight: 700;
            color: var(--pm-text);
        }
        .theme-freq-badge {
            background: var(--pm-primary-light);
            color: var(--pm-primary);
            font-weight: 700;
            border-radius: 6px;
            padding: 2px 10px;
            font-size: 12px;
            white-space: nowrap;
        }
        .theme-bar-track {
            background: var(--pm-border);
            border-radius: 4px;
            height: 6px;
            margin: 8px 0 10px 0;
            overflow: hidden;
        }
        .theme-bar-fill {
            background: var(--pm-primary);
            height: 6px;
            border-radius: 4px;
        }
        .theme-fact-row {
            display: flex;
            align-items: baseline;
            gap: 8px;
            font-size: 13px;
            padding: 3px 0;
        }
        .theme-fact-label {
            color: var(--pm-text-muted);
            min-width: 130px;
            flex-shrink: 0;
        }
        .theme-fact-value {
            color: var(--pm-text);
        }
        .pill {
            display: inline-block;
            border-radius: 999px;
            padding: 1px 10px;
            font-size: 12px;
            font-weight: 600;
        }
        .theme-hint {
            font-size: 12px;
            color: var(--pm-text-muted);
            font-style: italic;
            margin-top: 4px;
        }
        </style>
    """, unsafe_allow_html=True)


def _fact_row(label: str, value_html: str):
    st.markdown(
        f'<div class="theme-fact-row">'
        f'<span class="theme-fact-label">{label}</span>'
        f'<span class="theme-fact-value">{value_html}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


def render():
    """Renders the Theme Extraction Agent panel. Call this from any screen."""
    _inject_css()

    with st.container(border=True):
        head_col, btn_col = st.columns([3, 1])
        with head_col:
            st.markdown('<div class="theme-agent-title">Customer Feedback Themes</div>', unsafe_allow_html=True)
            st.caption(
                "The topics customers mention most often, grouped automatically from their feedback. "
                "Bigger bar = more feedback about that topic."
            )
        with btn_col:
            enrich_clicked = st.button("Analyze with AI", use_container_width=True,
                                        help="For each topic below, adds: how customers feel about it, "
                                             "what they were trying to do, and their main complaint.")

        freq = theme_frequency_table()
        if freq.empty:
            st.caption("No feedback has been classified yet. Themes will appear here once feedback is loaded.")
            return

        if enrich_clicked:
            with st.spinner("Reading through feedback for each topic..."):
                enriched, error = run_theme_agent_enrichment(top_n=len(freq))
            st.session_state["theme_agent_result"] = enriched
            st.session_state["theme_agent_error"] = error
            if enriched is None:
                st.warning("AI analysis isn't available right now, so only topic counts are shown below.")
                with st.expander("Technical details"):
                    st.write(error or "Unknown error.")
                    st.caption(
                        "This step runs through CrewAI/LiteLLM (src/theme_agent.py), which is a "
                        "different code path from Settings -> Test Gemini connection, so that test "
                        "can pass while this still fails. If the message above looks like a "
                        "model-not-found error rather than a key/auth error, try: "
                        "pip install -U crewai litellm"
                    )

        enriched = st.session_state.get("theme_agent_result")
        enriched_by_theme = {e["theme"]: e for e in enriched} if enriched else {}

        max_frequency = int(freq["frequency"].max()) if not freq.empty else 1

        for _, row in freq.iterrows():
            theme, frequency = row["theme"], int(row["frequency"])
            info = enriched_by_theme.get(theme)
            bar_pct = round(100 * frequency / max_frequency) if max_frequency else 0

            card_html = [
                '<div class="theme-card">',
                '<div class="theme-card-head">',
                f'<span class="theme-name">{theme}</span>',
                f'<span class="theme-freq-badge">{frequency} mention{"s" if frequency != 1 else ""}</span>',
                '</div>',
                f'<div class="theme-bar-track"><div class="theme-bar-fill" style="width:{bar_pct}%;"></div></div>',
                '</div>',
            ]
            st.markdown("".join(card_html), unsafe_allow_html=True)

            if info:
                s_color = _SENTIMENT_COLORS.get(info["sentiment"], "#9CA3AF")
                i_color = _INTENT_COLORS.get(info["intent"], "#9CA3AF")
                intent_plain = _INTENT_PLAIN.get(info["intent"], info["intent"])
                _fact_row(
                    "How customers feel",
                    f'<span class="pill" style="background:{s_color}22;color:{s_color};">{info["sentiment"]}</span>'
                )
                _fact_row(
                    "What they wanted",
                    f'<span class="pill" style="background:{i_color}22;color:{i_color};">{intent_plain}</span>'
                )
                _fact_row("Main complaint", info["pain_points"])
            else:
                st.markdown(
                    '<div class="theme-hint">Click "Analyze with AI" above to see how customers feel '
                    'about this topic and their main complaint.</div>',
                    unsafe_allow_html=True,
                )

            st.write("")