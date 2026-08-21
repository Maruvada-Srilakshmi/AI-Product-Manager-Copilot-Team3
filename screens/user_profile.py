import streamlit as st

from src.db import execute


def _seed_profile():
    """
    Seeds the profile fields from the actually logged-in user
    (st.session_state.current_user, set at login time) instead of a
    hardcoded account. Falls back gracefully if that's somehow missing.
    """
    user = st.session_state.get("current_user") or {}
    username = user.get("username", "")
    stored_name = (user.get("name") or "").strip()

    if stored_name:
        # The real name collected at sign-up (or a name saved here before).
        display_name = stored_name
    elif username and "@" in username:
        # Accounts created before the `users.name` column existed (or the
        # login page's demo shortcut) have no stored name yet -- this is
        # only ever a rough placeholder (e.g. "sri1234" for
        # sri1234@gmail.com) until the person fills in and saves their own.
        display_name = username.split("@")[0].replace(".", " ").replace("_", " ").title()
    else:
        display_name = username or ""

    return {
        "name": display_name,
        "email": username,
        "role": user.get("role", "Product Manager"),
    }


def show_user_profile():

    # Re-seed whenever the logged-in user changes (e.g. someone logs out
    # and a different account logs back in) rather than only on first load,
    # so the profile never keeps showing a stale/previous account.
    active_username = (st.session_state.get("current_user") or {}).get("username")
    if (
        "user_profile" not in st.session_state
        or st.session_state.get("_profile_seeded_for") != active_username
    ):
        st.session_state.user_profile = _seed_profile()
        st.session_state["_profile_seeded_for"] = active_username

    profile = st.session_state.user_profile
    ws = st.session_state["workspace"]

    st.markdown("## User Profile")
    st.caption(f"Signed in to {ws['name']}.")
    st.write("")

    with st.container(border=True):
        st.subheader("Profile Information")

        with st.form("profile_form"):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("Full Name", value=profile["name"])
                email = st.text_input("Email", value=profile["email"])
            with col2:
                role_options = ["Product Manager", "Senior Product Manager", "Product Owner", "Team Lead"]
                role = st.selectbox(
                    "Role", role_options,
                    index=role_options.index(profile["role"]) if profile["role"] in role_options else 0,
                )
                st.text_input("Company", value="AI Product Manager Copilot", disabled=True)

            saved = st.form_submit_button("Save Profile", type="primary")

            if saved:
                if name.strip() and email.strip():
                    profile["name"] = name.strip()
                    profile["email"] = email.strip()
                    profile["role"] = role

                    # Keep the logged-in user's session record and the
                    # `users` table in sync with the edit, so this doesn't
                    # get overwritten on the next re-seed (e.g. after
                    # navigating away and back).
                    user = st.session_state.get("current_user")
                    if user and user.get("id") is not None:
                        execute("UPDATE users SET role = ?, name = ? WHERE id = ?",
                                (role, name.strip(), user["id"]))
                        user["role"] = role
                        user["name"] = name.strip()
                        st.session_state.current_user = user
                        st.session_state["_profile_seeded_for"] = user.get("username")

                    st.session_state.profile_saved = True
                    st.rerun()
                else:
                    st.warning("Name and email can't be empty.")

        if st.session_state.pop("profile_saved", False):
            st.success("Profile updated successfully!")

    st.write("")

    # -----------------------------
    # Account actions (real: clears the database and session state, then
    # logs out). Kept alongside the profile rather than in a separate
    # Settings area, since these are the account-level actions tied
    # directly to the signed-in user.
    # -----------------------------
    with st.container(border=True):
        st.subheader("Account")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Log Out", use_container_width=True):
                st.session_state.logged_in = False
                st.session_state.pop("current_user", None)
                st.session_state.pop("user_profile", None)
                st.session_state.pop("_profile_seeded_for", None)
                # Clear the persisted session from the URL too, or a refresh
                # (or even just reopening the tab) would silently log the
                # user back in via the leftover query param.
                st.query_params.pop("user", None)
                st.query_params.pop("page", None)
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
                                  "roadmap_items", "chat_history", "analytics_events",
                                  "theme_validations"]:
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