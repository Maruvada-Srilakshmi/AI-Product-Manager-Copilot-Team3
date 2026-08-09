import os

import streamlit as st

from src.db import execute
from src.llm import check_connection
from utils.helpers import fetch_feedback, fetch_features, reload_dataset, DEFAULT_DATASET_PATH


def _seed_settings():
    """
    Seeds the Profile tab from the actually logged-in user
    (st.session_state.current_user, set at login time) instead of a
    hardcoded account. Falls back gracefully if that's somehow missing.
    """
    user = st.session_state.get("current_user") or {}
    username = user.get("username", "")

    # Users table has no separate display-name column, so derive a
    # reasonable display name from the email/username the first time.
    if username and "@" in username:
        display_name = username.split("@")[0].replace(".", " ").replace("_", " ").title()
    else:
        display_name = username or "User"

    return {
        "name": display_name,
        "email": username,
        "role": user.get("role", "Product Manager"),
        "email_notifications": True,
        "weekly_digest": True,
        "high_priority_alerts": True,
        "theme": st.session_state.get("theme", "Light"),
    }


def show_settings():

    # Re-seed whenever the logged-in user changes (e.g. someone logs out
    # and a different account logs back in) rather than only on first load,
    # so settings never keep showing a stale/previous account.
    active_username = (st.session_state.get("current_user") or {}).get("username")
    if (
        "user_settings" not in st.session_state
        or st.session_state.get("_settings_seeded_for") != active_username
    ):
        st.session_state.user_settings = _seed_settings()
        st.session_state["_settings_seeded_for"] = active_username

    settings = st.session_state.user_settings
    ws = st.session_state["workspace"]

    st.markdown("## Settings")
    st.caption("Manage your profile, workspace, notifications, and AI backend connection.")
    st.write("")

    tab_profile, tab_workspace, tab_data, tab_ai, tab_danger = st.tabs(
        ["Profile", "Workspace", "Data", "AI Backend", "Log Out / Clear Workspace Data"]
    )

    # -----------------------------
    # Profile
    # -----------------------------
    with tab_profile:
        st.subheader("Profile Information")

        with st.form("profile_form"):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("Full Name", value=settings["name"])
                email = st.text_input("Email", value=settings["email"])
            with col2:
                role = st.selectbox(
                    "Role",
                    ["Product Manager", "Senior Product Manager", "Product Owner", "Team Lead"],
                    index=["Product Manager", "Senior Product Manager", "Product Owner", "Team Lead"].index(settings["role"])
                    if settings["role"] in ["Product Manager", "Senior Product Manager", "Product Owner", "Team Lead"] else 0
                )
                st.text_input("Company", value="AI Product Manager Copilot", disabled=True)

            saved = st.form_submit_button("Save Profile", type="primary")

            if saved:
                if name.strip() and email.strip():
                    settings["name"] = name.strip()
                    settings["email"] = email.strip()
                    settings["role"] = role

                    # Keep the logged-in user's session record and the
                    # `users` table in sync with the edit, so this doesn't
                    # get overwritten on the next re-seed (e.g. after
                    # navigating away and back).
                    user = st.session_state.get("current_user")
                    if user and user.get("id") is not None:
                        execute("UPDATE users SET role = ? WHERE id = ?", (role, user["id"]))
                        user["role"] = role
                        st.session_state.current_user = user
                        st.session_state["_settings_seeded_for"] = user.get("username")

                    st.session_state.profile_saved = True
                    st.rerun()
                else:
                    st.warning("Name and email can't be empty.")

        if st.session_state.pop("profile_saved", False):
            st.success("✅ Profile updated successfully!")

    # -----------------------------
    # Workspace (real: persisted in the `workspaces` table)
    # -----------------------------
    with tab_workspace:
        st.subheader("Workspace")
        st.caption("This is the single shared workspace all feedback, features, and roadmap data live in.")

        with st.form("workspace_form"):
            ws_name = st.text_input("Workspace name", value=ws["name"])
            ws_saved = st.form_submit_button("Save workspace name", type="primary")
            if ws_saved and ws_name.strip():
                execute("UPDATE workspaces SET name = ? WHERE id = ?", (ws_name.strip(), ws["id"]))
                st.session_state["workspace"]["name"] = ws_name.strip()
                st.success("✅ Workspace name updated.")
                st.rerun()

    # -----------------------------
    # Data (real: the database is auto-seeded from the bundled dataset —
    # there's no manual upload screen anymore. This tab shows what's stored
    # and lets it be reprocessed on demand.)
    # -----------------------------
    with tab_data:
        st.subheader("Dataset")
        st.caption(
            "Feedback is loaded straight into the database from the bundled "
            f"dataset (`{os.path.basename(DEFAULT_DATASET_PATH)}`) the first time the app runs, "
            "then processed by the same AI pipeline (theme clustering, sentiment scoring, "
            "feature-request promotion) used everywhere else. The Dashboard always reflects "
            "what's currently in the database."
        )

        feedback = fetch_feedback()
        features = fetch_features()

        d1, d2, d3 = st.columns(3)
        d1.metric("Feedback rows in DB", len(feedback))
        d2.metric("Feature requests in DB", len(features))
        d3.metric(
            "Classified",
            int(feedback["theme"].notna().sum()) if not feedback.empty and "theme" in feedback.columns else 0,
        )

        st.write("")
        if st.button("Reload dataset (re-run AI classification)", type="primary"):
            with st.spinner("Clearing existing feedback/feature data and re-ingesting from the dataset..."):
                result = reload_dataset()
            if "error" in result:
                st.error(result["error"])
            else:
                st.success(f"✅ Reloaded {result['ingested']} feedback rows into the database.")
                st.rerun()

    # -----------------------------
    # AI Backend (real: tests the actual Gemini connection used by src/llm.py)
    # -----------------------------
    with tab_ai:
        st.subheader("Gemini connection")
        st.caption(
            "The AI Product Manager Copilot uses Google Gemini (via CrewAI orchestration, with a direct-API "
            "fallback) for PRD generation, impact scoring, executive summaries, and the chat assistant. "
            "If no `GEMINI_API_KEY` is configured, those features fall back to deterministic offline templates."
        )
        if st.button("Test Gemini connection", type="primary"):
            with st.spinner("Contacting Gemini..."):
                st.session_state["gemini_status"] = check_connection()

        result = st.session_state.get("gemini_status")
        if result:
            if result["status"] == "connected":
                st.success(result["detail"])
            elif result["status"] == "no_key":
                st.warning(
                    "No GEMINI_API_KEY found. Add it to `.streamlit/secrets.toml` or as an environment "
                    "variable, then restart the app."
                )
            else:
                st.error(f"Gemini call failed: {result['detail']}")

    # -----------------------------
    # Log Out / Clear Workspace Data (real: clears the database and session state, then logs out)
    # -----------------------------
    with tab_danger:
        st.subheader("Log Out / Clear Workspace Data")
        st.warning("These actions are irreversible or will sign you out of the application. Proceed with caution.")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Log Out", use_container_width=True):
                st.session_state.logged_in = False
                st.session_state.pop("current_user", None)
                st.session_state.pop("user_settings", None)
                st.session_state.pop("_settings_seeded_for", None)
                st.rerun()
        with col2:
            if st.button("Clear all workspace data", use_container_width=True, type="primary"):
                st.session_state.confirm_delete = True

        if st.session_state.get("confirm_delete"):
            st.error("Are you sure? This will permanently delete all ingested feedback, features, "
                     "documents, and roadmap items in this workspace.")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Yes, delete all data", use_container_width=True):
                    for table in ["feedback", "feature_requests", "prioritization", "documents",
                                  "roadmap_items", "chat_history"]:
                        execute(f"DELETE FROM {table} WHERE workspace_id = ?", (ws["id"],))
                    for key in ["uploads_log", "file_previews", "analysis_results", "chat_history", "exec_summary"]:
                        st.session_state.pop(key, None)
                    st.session_state.confirm_delete = False
                    st.success("Workspace data cleared.")
                    st.rerun()
            with c2:
                if st.button("Cancel", use_container_width=True):
                    st.session_state.confirm_delete = False
                    st.rerun()