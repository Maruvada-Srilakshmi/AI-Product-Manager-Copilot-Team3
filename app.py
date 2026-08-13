import streamlit as st

from src.db import init_db, get_default_workspace, get_user_by_username
from src.style import apply_style
from utils.helpers import ensure_dataset_seeded

from screens.login import show_login
from screens.register import show_register
from screens.dashboard import show_dashboard
from screens import theme_extraction_panel
from screens.prioritization_engine import show_prioritization_engine
from screens.ai_chat import show_ai_chat
from screens.reports import show_reports
from screens.roadmap import show_roadmap
from screens.settings import show_settings

# -----------------------------
# Page Configuration
# -----------------------------
st.set_page_config(
    page_title="AI Product Manager Copilot",
    layout="wide"
)

# -----------------------------
# Shared theme (dark navy sidebar + indigo accents + light/dark cards).
# This is the single source of truth for global styling, applied on
# every page so widgets never fall back to browser/OS dark-mode
# defaults (which was making text invisible against forced-light
# backgrounds set by individual screens).
#
# `st.session_state["theme"]` is the single source of truth for which
# palette is active; Settings > Appearance flips it and reruns, and this
# line re-applies the CSS on every page load so the whole app (sidebar,
# cards, inputs, dashboard/report/chat panels) updates together.
# -----------------------------
if "theme" not in st.session_state:
    st.session_state["theme"] = "Light"
apply_style(dark_mode=(st.session_state["theme"] == "Dark"))

# -----------------------------
# Backend bootstrap (SQLite schema + single-tenant workspace)
# -----------------------------
init_db()
if "workspace" not in st.session_state:
    st.session_state["workspace"] = get_default_workspace()

# -----------------------------
# Auto-seed the database from the bundled dataset (no manual upload step —
# runs once, only if this workspace's `feedback` table is still empty).
# -----------------------------
if not st.session_state.get("dataset_seeded"):
    ensure_dataset_seeded()
    st.session_state["dataset_seeded"] = True

# -----------------------------
# Session State
# -----------------------------
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "auth_page" not in st.session_state:
    st.session_state.auth_page = "login"

# -----------------------------
# Restore session across a browser refresh. A hard refresh (F5) resets
# st.session_state entirely -- that's why every page was bouncing back to
# the login screen -- but it doesn't touch the URL's query string, so the
# logged-in user and the page they were on are persisted there instead and
# restored here before any login check happens.
# -----------------------------
if not st.session_state.logged_in:
    remembered_user = st.query_params.get("user")
    if remembered_user:
        restored = get_user_by_username(remembered_user) or (
            {"username": remembered_user, "role": "Product Manager"}
            if remembered_user == "sathvika@gmail.com" else None
        )
        if restored:
            st.session_state.current_user = restored
            st.session_state.logged_in = True

# -----------------------------
# Login / Register Pages
# -----------------------------
if not st.session_state.logged_in:
    if st.session_state.auth_page == "register":
        show_register()
    else:
        show_login()

# -----------------------------
# Main Application
# -----------------------------
else:

    ws = st.session_state["workspace"]

    st.sidebar.title("AI Product Manager")
    st.sidebar.caption(f"Workspace: {ws['name']}")
    st.sidebar.markdown("---")

    _NAV_PAGES = [
        "Dashboard",
        "Theme Insights",
        "Prioritization Engine",
        "AI Chat",
        "Reports",
        "Roadmap",
        "Settings"
    ]
    # The currently selected page is also kept in the URL's query string, the
    # same mechanism used above to survive a refresh -- otherwise a reload
    # always snapped back to "Dashboard" (the first radio option) instead of
    # staying on whatever page was open.
    remembered_page = st.query_params.get("page", "Dashboard")
    if remembered_page not in _NAV_PAGES:
        remembered_page = "Dashboard"

    page = st.sidebar.radio(
        "Navigation", _NAV_PAGES,
        index=_NAV_PAGES.index(remembered_page),
        key="nav_page",
    )
    if st.query_params.get("page") != page:
        st.query_params["page"] = page

    st.sidebar.markdown("---")
    st.sidebar.caption("AI Product Manager Copilot v1.0")

    # -----------------------------
    # Appearance toggle -- a single icon-free button in the top-right of the
    # main content area (replacing the old Settings > Appearance tab). One
    # click flips the theme immediately.
    # -----------------------------
    _, top_right_col = st.columns([11, 1])
    with top_right_col:
        is_dark = st.session_state["theme"] == "Dark"
        toggle_label = "Light" if is_dark else "Dark"
        toggle_help = "Switch to Light mode" if is_dark else "Switch to Dark mode"
        if st.button(toggle_label, use_container_width=True, help=toggle_help, key="theme_toggle_btn"):
            st.session_state["theme"] = "Light" if is_dark else "Dark"
            if "user_settings" in st.session_state:
                st.session_state.user_settings["theme"] = st.session_state["theme"]
            st.rerun()

    if page == "Dashboard":
        show_dashboard()

    elif page == "Theme Insights":
        st.subheader("Theme Insights")
        st.caption("Recurring pain points clustered from feedback, with optional AI enrichment "
                    "(sentiment, pain-point summary, intent) via the Theme Extraction Agent.")
        theme_extraction_panel.render()

    elif page == "Prioritization Engine":
        show_prioritization_engine()

    elif page == "AI Chat":
        show_ai_chat()

    elif page == "Reports":
        show_reports()

    elif page == "Roadmap":
        show_roadmap()

    elif page == "Settings":
        show_settings()