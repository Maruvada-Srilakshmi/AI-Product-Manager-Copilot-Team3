import streamlit as st

from src.db import init_db, get_default_workspace
from src.style import apply_style
from utils.helpers import ensure_dataset_seeded

from screens.login import show_login
from screens.register import show_register
from screens.dashboard import show_dashboard
from screens import theme_extraction_panel
from screens.ai_chat import show_ai_chat
from screens.reports import show_reports
from screens.roadmap import show_roadmap
from screens.settings import show_settings

# -----------------------------
# Page Configuration
# -----------------------------
st.set_page_config(
    page_title="AI Product Manager Copilot",
    page_icon="🤖",
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

    st.sidebar.title("🤖 AI Product Manager")
    st.sidebar.caption(f"Workspace: {ws['name']}")
    st.sidebar.markdown("---")

    page = st.sidebar.radio(
        "Navigation",
        [
            "Dashboard",
            "Theme Insights",
            "AI Chat",
            "Reports",
            "Roadmap",
            "Settings"
        ]
    )

    st.sidebar.markdown("---")
    st.sidebar.caption("AI Product Manager Copilot v1.0")

    if page == "Dashboard":
        show_dashboard()

    elif page == "Theme Insights":
        st.subheader("🧠 Theme Insights")
        st.caption("Recurring pain points clustered from feedback, with optional AI enrichment "
                    "(sentiment, pain-point summary, intent) via the Theme Extraction Agent.")
        theme_extraction_panel.render()

    elif page == "AI Chat":
        show_ai_chat()

    elif page == "Reports":
        show_reports()

    elif page == "Roadmap":
        show_roadmap()

    elif page == "Settings":
        show_settings()
