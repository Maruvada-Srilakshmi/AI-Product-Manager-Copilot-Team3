import streamlit as st
import pandas as pd
import datetime as dt

from src.db import execute
from utils.helpers import (
    ws_id, fetch_features, fetch_roadmap, fetch_prioritized_backlog,
    ROADMAP_STATUSES, priority_bucket,
)

_QUARTERS = ["Q1", "Q2", "Q3", "Q4"]


def show_roadmap():
    st.markdown("## Product Roadmap")
    st.caption("Place prioritized features onto a quarterly roadmap — backed by the real feature/prioritization data")
    st.write("")

    features = fetch_features()
    roadmap = fetch_roadmap()

    # -----------------------------
    # KPI Cards (derived from real roadmap data)
    # -----------------------------
    total_initiatives = len(roadmap)
    in_progress = int((roadmap["status"] == "In Progress").sum()) if not roadmap.empty else 0
    completed = int((roadmap["status"] == "Completed").sum()) if not roadmap.empty else 0

    high_priority_count = 0
    if not roadmap.empty and not features.empty:
        backlog = fetch_prioritized_backlog()
        scheduled_feature_ids = set(roadmap["feature_id"].dropna().tolist())
        scheduled = backlog[backlog["feature_id"].isin(scheduled_feature_ids)]
        high_priority_count = int((scheduled["rice_score"].apply(priority_bucket) == "High").sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Planned", str(total_initiatives))
    c2.metric("In Progress", str(in_progress))
    c3.metric("Completed", str(completed))
    c4.metric("High Priority", str(high_priority_count))

    st.write("")

    # -----------------------------
    # Schedule a feature
    # -----------------------------
    if st.button("➕ Add Initiative", type="primary"):
        st.session_state.show_form = True

    if st.session_state.get("show_form", False):
        if features.empty:
            st.warning("No feature requests yet — these are auto-created once feedback is classified. "
                       "Reload the dataset from **Settings → Data** if the database is empty.")
        else:
            with st.form("roadmap_form", clear_on_submit=True):
                title = st.selectbox("Feature", features["title"].tolist())
                quarter = st.selectbox("Target quarter", _QUARTERS)
                c1, c2 = st.columns(2)
                start = c1.date_input("Start date", value=dt.date.today())
                end = c2.date_input("End date", value=dt.date.today() + dt.timedelta(days=30))
                submit = st.form_submit_button("Add to roadmap")

                if submit:
                    feature_row = features[features["title"] == title].iloc[0]
                    execute(
                        """INSERT INTO roadmap_items
                           (workspace_id, feature_id, title, quarter, start_date, end_date, status)
                           VALUES (?,?,?,?,?,?,?)""",
                        (ws_id(), int(feature_row["id"]), title, quarter, str(start), str(end), "Planned"),
                    )
                    st.session_state.show_form = False
                    st.session_state.roadmap_success = f"✅ '{title}' added to {quarter}!"
                    st.rerun()

    success_msg = st.session_state.pop("roadmap_success", None)
    if success_msg:
        st.success(success_msg)

    st.write("")

    # -----------------------------
    # Roadmap Columns (grouped by quarter, real data)
    # -----------------------------
    if roadmap.empty:
        st.info("Nothing scheduled yet — add a feature above.")
    else:
        cols = st.columns(len(_QUARTERS))
        for col, quarter in zip(cols, _QUARTERS):
            items = roadmap[roadmap["quarter"] == quarter]
            with col:
                st.subheader(quarter)
                if items.empty:
                    st.caption("No initiatives yet.")
                for _, item in items.iterrows():
                    with st.container(border=True):
                        c1, c2 = st.columns([4, 2])
                        with c1:
                            st.write(f"**{item['title']}**")
                            st.caption(f"{item['start_date']} → {item['end_date']}")
                        with c2:
                            new_status = st.selectbox(
                                "Status", ROADMAP_STATUSES,
                                index=ROADMAP_STATUSES.index(item["status"]) if item["status"] in ROADMAP_STATUSES else 0,
                                key=f"rm_status_{item['id']}", label_visibility="collapsed",
                            )
                            if new_status != item["status"]:
                                execute("UPDATE roadmap_items SET status = ? WHERE id = ?", (new_status, int(item["id"])))
                                st.rerun()

                        if st.button("🗑 Remove", key=f"remove_{item['id']}", use_container_width=True):
                            execute("DELETE FROM roadmap_items WHERE id = ?", (int(item["id"]),))
                            st.rerun()

        st.write("")
        st.subheader("Items per quarter")
        st.bar_chart(roadmap["quarter"].value_counts())

    st.write("")

    # -----------------------------
    # AI Recommendation (real: top RICE-scored features not yet scheduled)
    # -----------------------------
    st.subheader("AI Recommendation")

    if features.empty:
        st.info("No feature requests yet — recommendations will appear once feedback has been ingested and analyzed.")
    else:
        backlog = fetch_prioritized_backlog().sort_values("rice_score", ascending=False, na_position="last")
        scheduled_ids = set(roadmap["feature_id"].dropna().tolist()) if not roadmap.empty else set()
        unscheduled = backlog[~backlog["feature_id"].isin(scheduled_ids)].head(4)

        if unscheduled.empty:
            st.success("All prioritized features are already on the roadmap.")
        else:
            lines = "\n\n".join(
                f"• **{r.title}** ({r.theme}) — RICE {r.rice_score:.1f}" if pd.notna(r.rice_score)
                else f"• **{r.title}** ({r.theme}) — not yet scored"
                for r in unscheduled.itertuples()
            )
            st.info(
                "Based on customer feedback analysis and RICE prioritization, the AI recommends "
                f"scheduling these next:\n\n{lines}\n\n"
                "These initiatives are expected to improve customer satisfaction and reduce high-priority issues."
            )
