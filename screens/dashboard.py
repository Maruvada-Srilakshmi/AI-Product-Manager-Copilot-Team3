import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from utils.helpers import (
    fetch_feedback, fetch_features, fetch_documents, fetch_roadmap,
)


def _inject_css():
    st.markdown("""
        <style>
        .metric-card {
            background: var(--pm-bg);
            border-radius: 14px;
            padding: 18px 20px;
            border: 1px solid var(--pm-border);
            box-shadow: var(--pm-shadow);
        }
        .metric-label {
            font-size: 13px;
            color: var(--pm-text-muted);
            font-weight: 500;
        }
        .metric-value {
            font-size: 28px;
            font-weight: 700;
            color: var(--pm-navy);
            margin: 4px 0 2px 0;
        }
        .metric-delta {
            font-size: 12px;
            color: var(--pm-green);
            font-weight: 600;
        }
        .panel-title {
            font-size: 15px;
            font-weight: 700;
            color: var(--pm-navy);
            margin-bottom: 2px;
        }
        .issue-row,
        .activity-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 0;
            border-bottom: 1px solid var(--pm-border);
            font-size: 14px;
            color: var(--pm-text);
        }
        .issue-rank {
            background: var(--pm-primary-light);
            color: var(--pm-primary);
            font-weight: 700;
            border-radius: 6px;
            width: 22px;
            height: 22px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            margin-right: 8px;
            font-size: 12px;
        }
        .badge-time {
            color: var(--pm-text-muted);
            font-size: 12px;
        }
        </style>
    """, unsafe_allow_html=True)


def _metric_card(label, value):
    st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
        </div>
    """, unsafe_allow_html=True)


def _feedback_trend_chart(feedback: pd.DataFrame):
    fig = go.Figure()

    if feedback.empty:
        fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10),
                           plot_bgcolor="white", paper_bgcolor="white")
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.caption("No feedback in the database yet — data is loaded automatically on first launch.")
        return

    fb = feedback.copy()
    fb["created_at"] = pd.to_datetime(fb["created_at"], errors="coerce")
    fb = fb.dropna(subset=["created_at"])
    if fb.empty:
        st.caption("Feedback has no valid dates yet.")
        return
    fb = fb.sort_values("created_at").reset_index(drop=True)

    # Pick the coarsest time bucket that still yields at least two distinct
    # points, stepping down from week -> day -> hour -> minute as the data's
    # actual time span shrinks.
    span = fb["created_at"].max() - fb["created_at"].min()
    if span.days >= 60:
        period, tick_format = "W", "Week of %b %d"
    elif span.days >= 2:
        period, tick_format = "D", "%b %d, %Y"
    elif span.total_seconds() >= 2 * 3600:
        period, tick_format = "h", "%b %d, %I %p"
    elif span.total_seconds() >= 120:
        period, tick_format = "min", "%I:%M %p"
    else:
        period, tick_format = None, None

    total_by_bucket = None
    if period is not None:
        fb["bucket"] = fb["created_at"].dt.to_period(period).dt.start_time
        total_by_bucket = fb.groupby("bucket").size().sort_index()

    if total_by_bucket is None or len(total_by_bucket) < 2:
        # Every row landed in the same time bucket (e.g. all feedback was
        # imported in one batch, so there's no real time spread to chart).
        # Fall back to a cumulative view across the record sequence itself,
        # which still shows a genuine trend line instead of one dot.
        fb["seq"] = range(1, len(fb) + 1)
        total_cum = fb["seq"]
        resolved_cum = (
            fb["sentiment"].notna().cumsum() if "sentiment" in fb.columns
            else pd.Series(0, index=fb.index)
        )

        fig.add_trace(go.Scatter(
            x=fb["seq"], y=total_cum,
            mode="lines+markers", name="Total Feedback",
            line=dict(color="#6366F1", width=3), marker=dict(size=5)
        ))
        fig.add_trace(go.Scatter(
            x=fb["seq"], y=resolved_cum,
            mode="lines+markers", name="Classified",
            line=dict(color="#22C55E", width=3, dash="dot"), marker=dict(size=5)
        ))

        y_max = max(int(total_cum.max()), int(resolved_cum.max()), 1)
        fig.update_layout(
            height=280,
            margin=dict(l=10, r=10, t=10, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            plot_bgcolor="white",
            paper_bgcolor="white",
            xaxis=dict(showgrid=False, title="Feedback received (in order)"),
            yaxis=dict(showgrid=True, gridcolor="#F3F4F6",
                       rangemode="tozero", range=[0, y_max * 1.15]),
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.caption("All current feedback shares the same timestamp, so this shows cumulative volume by record order rather than by date.")
        return

    resolved_by_bucket = (
        fb[fb["sentiment"].notna()].groupby("bucket").size().reindex(total_by_bucket.index).fillna(0)
        if "sentiment" in fb.columns else pd.Series(0, index=total_by_bucket.index)
    )

    fig.add_trace(go.Scatter(
        x=total_by_bucket.index, y=total_by_bucket.values,
        mode="lines+markers", name="Total Feedback",
        line=dict(color="#6366F1", width=3), marker=dict(size=8)
    ))
    fig.add_trace(go.Scatter(
        x=resolved_by_bucket.index, y=resolved_by_bucket.values,
        mode="lines+markers", name="Classified",
        line=dict(color="#22C55E", width=3, dash="dot"), marker=dict(size=8)
    ))

    # Pad the x-axis so a narrow date range doesn't cause Plotly to auto-zoom
    # the range down to fractions of a second.
    pad = pd.Timedelta(days=3) if period == "D" else pd.Timedelta(days=7) if period == "W" else pd.Timedelta(hours=2)
    x_min, x_max = total_by_bucket.index.min(), total_by_bucket.index.max()

    y_max = max(int(total_by_bucket.max()), int(resolved_by_bucket.max()), 1)

    fig.update_layout(
        height=280,
        margin=dict(l=10, r=10, t=10, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        plot_bgcolor="white",
        paper_bgcolor="white",
        xaxis=dict(
            showgrid=False, type="date",
            range=[x_min - pad, x_max + pad],
            tickformat=tick_format,
        ),
        yaxis=dict(
            showgrid=True, gridcolor="#F3F4F6",
            rangemode="tozero", range=[0, y_max * 1.2],
        ),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def _donut_chart(labels, values, colors, height=220):
    fig = go.Figure(data=[go.Pie(
        labels=labels, values=values, hole=0.65,
        marker=dict(colors=colors), textinfo="none"
    )])
    fig.update_layout(height=height, showlegend=False, margin=dict(l=0, r=0, t=0, b=0))
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


_PALETTE = ["#6366F1", "#22C55E", "#F97316", "#F59E0B", "#9CA3AF", "#EC4899", "#0EA5E9"]


def show_dashboard():
    _inject_css()

    feedback = fetch_feedback()
    features = fetch_features()
    docs = fetch_documents()
    roadmap = fetch_roadmap()

    col_title, col_range = st.columns([3, 1])
    with col_title:
        st.title("AI Product Manager Dashboard")
        st.caption("Live overview of your product's health, sourced from your ingested feedback and AI analysis.")
    with col_range:
        st.selectbox("Date Range", ["All time"], label_visibility="collapsed")

    st.write("")

    total_feedback = len(feedback)
    top_issues_count = int((feedback["sentiment"] == "Negative").sum()) if "sentiment" in feedback.columns and not feedback.empty else 0
    feature_requests_count = len(features)
    satisfied_pct = (
        f"{round(100 * (feedback['sentiment'] == 'Positive').sum() / len(feedback))}%"
        if not feedback.empty and feedback["sentiment"].notna().any() else "—"
    )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _metric_card("Total Feedback", f"{total_feedback:,}")
    with c2:
        _metric_card("Negative Feedback", f"{top_issues_count:,}")
    with c3:
        _metric_card("Feature Requests", f"{feature_requests_count:,}")
    with c4:
        _metric_card("Satisfied Users", satisfied_pct)

    st.write("")

    left, right = st.columns([2, 1])

    with left:
        with st.container(border=True):
            st.markdown('<div class="panel-title">Feedback Trend</div>', unsafe_allow_html=True)
            _feedback_trend_chart(feedback)

    with right:
        with st.container(border=True):
            st.markdown('<div class="panel-title">Top Requested Features</div>', unsafe_allow_html=True)

            if features.empty:
                st.caption("No feature requests tracked yet.")
            else:
                top_feats = features.head(5)
                total_votes = top_feats["votes"].sum() or 1
                names = top_feats["title"].tolist()
                vals = [round(100 * v / total_votes) for v in top_feats["votes"].tolist()]
                colors = _PALETTE[:len(names)]
                _donut_chart(names, vals, colors)
                for f, v, c in zip(names, vals, colors):
                    st.markdown(
                        f'<div style="display:flex;justify-content:space-between;font-size:13px;padding:2px 0;">'
                        f'<span><span style="color:{c};">●</span> {f}</span><b>{v}%</b></div>',
                        unsafe_allow_html=True
                    )

    st.write("")

    col1, col2, col3 = st.columns(3)

    with col1:
        with st.container(border=True):
            st.markdown('<div class="panel-title">Top Issues</div>', unsafe_allow_html=True)

            if feedback.empty or "theme" not in feedback.columns or feedback["theme"].isna().all():
                st.caption("No classified feedback in the database yet.")
            else:
                neg = feedback[feedback["sentiment"] == "Negative"]
                top_issues = neg["theme"].value_counts().head(4)
                if top_issues.empty:
                    st.caption("No negative-sentiment themes yet.")
                for i, (name, count) in enumerate(top_issues.items(), 1):
                    st.markdown(
                        f'<div class="issue-row"><span><span class="issue-rank">{i}</span>{name}</span><b>{count}</b></div>',
                        unsafe_allow_html=True
                    )

    with col2:
        with st.container(border=True):
            st.markdown('<div class="panel-title">Sentiment Analysis</div>', unsafe_allow_html=True)

            if feedback.empty or "sentiment" not in feedback.columns or feedback["sentiment"].isna().all():
                st.caption("No classified feedback yet.")
            else:
                counts = feedback["sentiment"].value_counts()
                sentiments = [s for s in ["Positive", "Neutral", "Negative"] if s in counts.index]
                vals = [int(counts[s]) for s in sentiments]
                colors = {"Positive": "#22C55E", "Neutral": "#F59E0B", "Negative": "#EF4444"}
                cols = [colors[s] for s in sentiments]
                _donut_chart(sentiments, vals, cols, height=180)
                total = sum(vals) or 1
                for s, v, c in zip(sentiments, vals, cols):
                    pct = round(100 * v / total)
                    st.markdown(
                        f'<div style="display:flex;justify-content:space-between;font-size:13px;padding:2px 0;">'
                        f'<span><span style="color:{c};">●</span> {s}</span><b>{pct}%</b></div>',
                        unsafe_allow_html=True
                    )

    with col3:
        with st.container(border=True):
            st.markdown('<div class="panel-title">Recent AI Activities</div>', unsafe_allow_html=True)

            activities = []
            if not docs.empty:
                for _, d in docs.head(3).iterrows():
                    icon = "📝" if d["doc_type"] == "PRD" else "🧾"
                    activities.append((icon, f"Generated {d['doc_type']}: {d['title'][:28]}", str(d["created_at"])[:10]))
            if not roadmap.empty:
                activities.append(("🗺️", f"{len(roadmap)} item(s) on the roadmap", ""))
            if not feedback.empty:
                classified = int(feedback["theme"].notna().sum()) if "theme" in feedback.columns else 0
                activities.append(("🔍", f"Analyzed {classified} of {len(feedback)} feedback items", ""))
            if top_issues_count:
                activities.append(("⚠️", f"Identified {top_issues_count} negative feedback items", ""))

            if not activities:
                st.caption("No activity yet — start by uploading feedback.")
            for icon, text, when in activities[:4]:
                st.markdown(
                    f'<div class="activity-row"><span>{icon} {text}</span><span class="badge-time">{when}</span></div>',
                    unsafe_allow_html=True
                )