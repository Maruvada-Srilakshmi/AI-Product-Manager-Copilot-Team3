"""
Module 3: Product Analytics Data Integration Module

Ingests and visualizes product usage/event data (feature adoption, session
activity, click volume, etc.) alongside the rest of the workspace's data,
and cross-references it with customer-requested features (Module 5) to
show which requested features are actually catching on.

Data flow mirrors the Feedback Ingestion path:
 - The bundled `data/product_analytics_dataset.csv` is auto-seeded into the
   `analytics_events` table on first launch (utils.helpers.ensure_analytics_seeded,
   called from app.py), so this page always has data to show.
 - All aggregation (usage by feature, usage trend, event mix, usage-vs-demand
   correlation) is deterministic — src/analytics_utils.py — so this page
   never depends on an LLM/API key being configured.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from utils.helpers import (
    fetch_analytics, analytics_summary, analytics_vs_demand,
    ensure_analytics_seeded, reload_analytics,
)

_STATUS_COLORS = {
    "Shipped & used": "#22C55E",
    "Shipped, low usage": "#F59E0B",
    "No usage data": "#EF4444",
}


def _inject_css():
    st.markdown("""
        <style>
        .analytics-title { font-size: 15px; font-weight: 700; color: var(--pm-navy); margin-bottom: 2px; }
        .analytics-badge {
            display:inline-block; border-radius:999px; padding:2px 10px;
            font-size:11px; font-weight:600; margin-right: 6px;
        }
        .usage-row {
            display: flex; justify-content: space-between; align-items: center;
            padding: 8px 0; border-bottom: 1px solid var(--pm-border);
            font-size: 14px; color: var(--pm-text);
        }
        .usage-row:last-child { border-bottom: none; }
        .usage-count {
            background: var(--pm-primary-light); color: var(--pm-primary);
            font-weight: 700; border-radius: 6px; padding: 1px 8px; font-size: 12px;
        }
        </style>
    """, unsafe_allow_html=True)


def _metric_card(label, value):
    st.markdown(f"""
        <div style="background: var(--pm-bg); border-radius: 14px; padding: 18px 20px;
                    border: 1px solid var(--pm-border); box-shadow: var(--pm-shadow);">
            <div style="font-size:13px; color: var(--pm-text-muted); font-weight:500;">{label}</div>
            <div style="font-size:28px; font-weight:700; color: var(--pm-navy); margin:4px 0 2px 0;">{value}</div>
        </div>
    """, unsafe_allow_html=True)


def _trend_chart(trend: pd.DataFrame):
    fig = go.Figure()
    if trend.empty:
        fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10),
                           plot_bgcolor="white", paper_bgcolor="white")
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.caption("No usage events yet.")
        return

    fig.add_trace(go.Scatter(
        x=trend["date"], y=trend["usage"],
        mode="lines+markers", name="Usage",
        line=dict(color="#6366F1", width=3), marker=dict(size=5),
        fill="tozeroy", fillcolor="rgba(99,102,241,0.08)",
    ))
    fig.update_layout(
        height=260,
        margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor="white",
        paper_bgcolor="white",
        xaxis=dict(showgrid=False, type="date"),
        yaxis=dict(showgrid=True, gridcolor="#F3F4F6", rangemode="tozero"),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def _usage_bar_chart(by_feature: pd.DataFrame, top_n: int = 10):
    top = by_feature.head(top_n).iloc[::-1]
    fig = go.Figure(go.Bar(
        x=top["usage"], y=top["feature"], orientation="h",
        marker=dict(color="#6366F1"),
    ))
    fig.update_layout(
        height=max(220, 32 * len(top)),
        margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor="white",
        paper_bgcolor="white",
        xaxis=dict(showgrid=True, gridcolor="#F3F4F6", rangemode="tozero"),
        yaxis=dict(showgrid=False),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def show_product_analytics():
    _inject_css()

    st.subheader("Product Analytics Data Integration")
    st.caption(
        "Feature adoption and usage activity pulled in from product analytics events, "
        "cross-referenced with customer-requested features so demand and real usage "
        "can be compared side by side."
    )

    if not st.session_state.get("_analytics_seed_checked"):
        ensure_analytics_seeded()
        st.session_state["_analytics_seed_checked"] = True

    data = analytics_summary()
    metrics = data["metrics"]

    if metrics["total_events"] == 0:
        st.info("No usage data yet — it will auto-load from the bundled sample dataset.")
        return

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _metric_card("Tracked Events", f"{metrics['total_events']:,}")
    with c2:
        _metric_card("Total Usage", f"{metrics['total_usage']:,}")
    with c3:
        _metric_card("Features Tracked", f"{metrics['tracked_features']:,}")
    with c4:
        _metric_card("Most-Used Feature", metrics["top_feature"] or "—")

    st.write("")

    left, right = st.columns([2, 1])
    with left:
        with st.container(border=True):
            st.markdown('<div class="analytics-title">Usage Trend</div>', unsafe_allow_html=True)
            st.caption("Total tracked usage over time, across all features.")
            _trend_chart(data["trend"])

    with right:
        with st.container(border=True):
            st.markdown('<div class="analytics-title">Event Mix</div>', unsafe_allow_html=True)
            st.caption("What kind of activity is being tracked.")
            mix = data["event_mix"]
            if mix.empty:
                st.caption("No events yet.")
            else:
                total = mix["usage"].sum() or 1
                for _, row in mix.iterrows():
                    pct = round(100 * row["usage"] / total)
                    st.markdown(
                        f'<div class="usage-row"><span>{row["event_name"]}</span>'
                        f'<span class="usage-count">{pct}%</span></div>',
                        unsafe_allow_html=True,
                    )

    st.write("")

    with st.container(border=True):
        st.markdown('<div class="analytics-title">Usage by Feature</div>', unsafe_allow_html=True)
        st.caption("Total usage per feature, highest first.")
        _usage_bar_chart(data["by_feature"])

    st.write("")

    with st.container(border=True):
        st.markdown('<div class="analytics-title">Demand vs. Usage</div>', unsafe_allow_html=True)
        st.caption(
            "Customer-requested features (from the Feature Request Aggregation module) matched "
            "against tracked usage, so it's clear which requests actually shipped and caught on."
        )
        comparison = analytics_vs_demand()
        if comparison.empty:
            st.caption("No feature requests to compare yet.")
        else:
            for _, row in comparison.head(10).iterrows():
                color = _STATUS_COLORS.get(row["status"], "#9CA3AF")
                st.markdown(
                    f'<div class="usage-row">'
                    f'<span>{row["requested_feature"]}<br>'
                    f'<span style="font-size:12px;color:var(--pm-text-muted);">{row["votes"]} votes</span></span>'
                    f'<span class="analytics-badge" style="background:{color}22;color:{color};">'
                    f'{row["status"]}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    st.write("")
    if st.button("Reload sample dataset (re-run ingestion)"):
        with st.spinner("Clearing existing usage data and re-ingesting from the bundled dataset..."):
            result = reload_analytics()
        if "error" in result:
            st.error(result["error"])
        else:
            st.success(f"Reloaded {result['ingested']} usage events into the database.")
            st.rerun()