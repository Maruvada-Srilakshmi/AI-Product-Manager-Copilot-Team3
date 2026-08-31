import streamlit as st

from utils.helpers import (
    available_theme_labels,
    record_theme_validation,
    theme_validation_queue,
    theme_validation_summary,
)

_ITEM_TYPE_LABELS = {
    "feedback": "Issue detection (feedback theming)",
    "feature_request": "Feature grouping (feature-request theming)",
}


def _inject_css():
    st.markdown("""
        <style>
        .validation-title { font-size: 15px; font-weight: 700; color: var(--pm-navy); margin-bottom: 2px; }
        .validation-card {
            background: var(--pm-bg); border-radius: 14px; padding: 18px 20px;
            border: 1px solid var(--pm-border); box-shadow: var(--pm-shadow);
        }
        .validation-metric-label { font-size:13px; color: var(--pm-text-muted); font-weight:500; }
        .validation-metric-value { font-size:28px; font-weight:700; color: var(--pm-navy); margin:4px 0 2px 0; }
        .validation-metric-sub { font-size:12px; color: var(--pm-text-muted); }
        .validation-item-text {
            font-size: 14px; color: var(--pm-text); margin-bottom: 4px;
        }
        .validation-item-theme {
            display:inline-block; background: var(--pm-primary-light); color: var(--pm-primary);
            font-weight: 700; border-radius: 6px; padding: 1px 8px; font-size: 12px;
        }
        </style>
    """, unsafe_allow_html=True)


def _metric_card(label, value, sub=None):
    sub_html = f'<div class="validation-metric-sub">{sub}</div>' if sub else ""
    st.markdown(f"""
        <div class="validation-card">
            <div class="validation-metric-label">{label}</div>
            <div class="validation-metric-value">{value}</div>
            {sub_html}
        </div>
    """, unsafe_allow_html=True)


def _accuracy_display(bucket: dict) -> str:
    if bucket["accuracy"] is None:
        return "Not yet reviewed"
    return f"{bucket['accuracy']}%"


def _render_dashboard():
    summary = theme_validation_summary()

    col1, col2, col3 = st.columns(3)
    with col1:
        _metric_card(
            "Overall accuracy",
            _accuracy_display(summary["overall"]),
            f"{summary['overall']['total']} reviewed so far",
        )
    with col2:
        _metric_card(
            "Issue detection accuracy",
            _accuracy_display(summary["feedback"]),
            f"{summary['feedback']['correct']} correct / {summary['feedback']['incorrect']} incorrect",
        )
    with col3:
        _metric_card(
            "Feature grouping accuracy",
            _accuracy_display(summary["feature_request"]),
            f"{summary['feature_request']['correct']} correct / {summary['feature_request']['incorrect']} incorrect",
        )


def _render_review_queue(item_type: str):
    queue = theme_validation_queue(item_type, limit=10)

    if queue.empty:
        st.caption("Nothing left to review right now — either everything has been "
                    "validated, or no themed items exist yet.")
        return

    theme_choices = available_theme_labels()

    for _, row in queue.iterrows():
        item_id = int(row["id"])
        original_theme = row["theme"]
        display_text = str(row["label"])

        with st.container(border=True):
            st.markdown(f'<div class="validation-item-text">{display_text}</div>', unsafe_allow_html=True)
            st.markdown(
                f'Assigned theme: <span class="validation-item-theme">{original_theme}</span>',
                unsafe_allow_html=True,
            )

            correct_col, incorrect_col = st.columns(2)
            with correct_col:
                if st.button("Correct", key=f"{item_type}_{item_id}_correct", use_container_width=True):
                    record_theme_validation(item_type, item_id, original_theme, is_correct=True)
                    st.rerun()
            with incorrect_col:
                if st.button("Incorrect", key=f"{item_type}_{item_id}_incorrect", use_container_width=True):
                    st.session_state[f"{item_type}_{item_id}_correcting"] = True

            if st.session_state.get(f"{item_type}_{item_id}_correcting"):
                options = [t for t in theme_choices if t != original_theme] or theme_choices
                chosen = st.selectbox(
                    "What's the correct theme?",
                    options=options,
                    key=f"{item_type}_{item_id}_choice",
                )
                custom = st.text_input(
                    "Or type a new theme name (optional)",
                    key=f"{item_type}_{item_id}_custom",
                )
                if st.button("Save correction", key=f"{item_type}_{item_id}_save"):
                    corrected_theme = custom.strip() if custom.strip() else chosen
                    record_theme_validation(
                        item_type, item_id, original_theme,
                        is_correct=False, corrected_theme=corrected_theme,
                    )
                    st.session_state.pop(f"{item_type}_{item_id}_correcting", None)
                    st.rerun()


def render():
    """Renders the Accuracy Validation panel. Call this from any screen."""
    _inject_css()

    st.markdown('<div class="validation-title">Accuracy Validation</div>', unsafe_allow_html=True)
    st.caption("Confirm or correct the AI-assigned theme on individual feedback items and "
               "feature requests, and see the resulting accuracy for issue detection and "
               "feature grouping.")

    _render_dashboard()
    st.markdown("---")

    tab_feedback, tab_features = st.tabs([
        _ITEM_TYPE_LABELS["feedback"],
        _ITEM_TYPE_LABELS["feature_request"],
    ])
    with tab_feedback:
        _render_review_queue("feedback")
    with tab_features:
        _render_review_queue("feature_request")