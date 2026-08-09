"""
Purely cosmetic styling shared across every page of the AI Product Manager
Copilot. Import `apply_style()` and call it once, right after
`st.set_page_config(...)`, on each page. Nothing in here touches app logic,
session state, or data — it only injects CSS.

Palette: dark navy sidebar + indigo/purple accent + shadowed cards, matching
the reference dashboard mock (dark nav rail, purple primary actions, soft
card shadows instead of flat borders). Supports both a Light and a Dark
content area — `apply_style(dark_mode=True/False)` picks which set of
`--pm-*` variables gets resolved into :root, and every rule below is written
against those variables so the whole app (including the custom-CSS blocks
in individual screens) repaints correctly when the theme changes.
"""
import streamlit as st

# ---------------------------------------------------------------------------
# Palettes. The sidebar stays a dark navy rail in both themes (it's part of
# the brand identity), only the content-area colors flip.
# ---------------------------------------------------------------------------
_LIGHT_VARS = {
    "--pm-sidebar-bg-start": "#3B1E8C",
    "--pm-sidebar-bg-end": "#1A0F3D",
    "--pm-sidebar-bg-active": "linear-gradient(135deg, #7C3AED, #5B21B6)",
    "--pm-sidebar-text": "#C9BFEE",
    "--pm-sidebar-text-active": "#FFFFFF",
    "--pm-sidebar-border": "rgba(255, 255, 255, 0.08)",

    "--pm-primary": "#6C5CE7",
    "--pm-primary-dark": "#5A47D6",
    "--pm-primary-light": "#EFECFD",

    "--pm-navy": "#1E2233",
    "--pm-border": "#E9EAF2",
    "--pm-bg": "#FFFFFF",
    "--pm-bg-soft": "#F7F7FB",
    "--pm-text": "#1E2233",
    "--pm-text-muted": "#8A8FA3",

    "--pm-green": "#1FAE73",
    "--pm-green-bg": "#E6F9F1",
    "--pm-amber": "#D08A1F",
    "--pm-amber-bg": "#FDF2E1",
    "--pm-red": "#E4574C",
    "--pm-red-bg": "#FDEAE8",

    "--pm-scrollbar-thumb": "#D3D6E4",
    "--pm-scrollbar-thumb-hover": "#B7BBD4",
    "--pm-header-bg": "#FFFFFF",

    "--pm-shadow": "0 1px 2px rgba(20, 26, 46, 0.04), 0 4px 14px rgba(20, 26, 46, 0.06)",
    "--pm-shadow-hover": "0 2px 6px rgba(20, 26, 46, 0.06), 0 10px 24px rgba(20, 26, 46, 0.09)",
}

_DARK_VARS = {
    "--pm-sidebar-bg-start": "#2A1665",
    "--pm-sidebar-bg-end": "#0B0818",
    "--pm-sidebar-bg-active": "linear-gradient(135deg, #8B7CF6, #6C3FE0)",
    "--pm-sidebar-text": "#B4ABDD",
    "--pm-sidebar-text-active": "#FFFFFF",
    "--pm-sidebar-border": "rgba(255, 255, 255, 0.07)",

    "--pm-primary": "#8B7CF6",
    "--pm-primary-dark": "#7C6AF0",
    "--pm-primary-light": "#292347",

    "--pm-navy": "#F1F2F8",
    "--pm-border": "#2A2F48",
    "--pm-bg": "#171B2E",
    "--pm-bg-soft": "#10131F",
    "--pm-text": "#E7E8F2",
    "--pm-text-muted": "#9298B5",

    "--pm-green": "#34D399",
    "--pm-green-bg": "#0F2E24",
    "--pm-amber": "#F5A524",
    "--pm-amber-bg": "#332208",
    "--pm-red": "#F87171",
    "--pm-red-bg": "#3A1518",

    "--pm-scrollbar-thumb": "#2E3350",
    "--pm-scrollbar-thumb-hover": "#3E4468",
    "--pm-header-bg": "#10131F",

    "--pm-shadow": "0 1px 2px rgba(0, 0, 0, 0.25), 0 4px 14px rgba(0, 0, 0, 0.35)",
    "--pm-shadow-hover": "0 2px 6px rgba(0, 0, 0, 0.3), 0 10px 24px rgba(0, 0, 0, 0.4)",
}

_SHARED_VARS = """
    --pm-radius-sm: 8px;
    --pm-radius-md: 12px;
    --pm-radius-lg: 16px;
    --pm-transition: all 0.16s cubic-bezier(0.4, 0, 0.2, 1);
"""


def _build_root_vars(dark_mode: bool) -> str:
    palette = _DARK_VARS if dark_mode else _LIGHT_VARS
    lines = "\n".join(f"    {k}: {v};" for k, v in palette.items())
    return f":root {{\n{lines}\n{_SHARED_VARS}}}"


_CSS_TEMPLATE = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

__ROOT_VARS__

/* Typography */
html, body, .stApp, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

/* Top toolbar / header strip and hamburger menu popover also follow the
   theme, so switching to Dark doesn't leave a bright white bar at the top. */
header[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stDecoration"] {
    background-color: var(--pm-header-bg) !important;
}
div[data-baseweb="popover"] ul,
div[data-baseweb="menu"] {
    background-color: var(--pm-bg) !important;
    color: var(--pm-text) !important;
}

/* App background */
.stApp {
    background-color: var(--pm-bg-soft);
    color: var(--pm-text);
}
.block-container {
    padding-top: 2.5rem;
    padding-bottom: 3rem;
    max-width: 1200px;
}

/* Comfortable vertical rhythm between stacked elements */
[data-testid="stVerticalBlock"] > div {
    gap: 0.9rem;
}

/* ---------------- Typography color enforcement (main content) ----------------
   Streamlit's own base theme sets explicit text colors directly on the
   headings/paragraphs/labels/captions it renders. In Dark mode those
   built-in defaults are near-black and silently win over our
   `.stApp { color: var(--pm-text) }` default, leaving page titles,
   captions, tab labels, and widget labels unreadable against the dark
   background (e.g. Settings > Appearance). Re-asserting color directly on
   every element Streamlit actually renders text into fixes this
   regardless of load order. Scoped to the main content area only — the
   sidebar already sets its own text colors via `section[data-testid=
   "stSidebar"] *` above and must not be touched here.
*/
section[data-testid="stMain"] [data-testid="stMarkdownContainer"],
section[data-testid="stMain"] [data-testid="stMarkdownContainer"] *:not(a),
section[data-testid="stMain"] [data-testid="stWidgetLabel"] p,
section[data-testid="stMain"] label,
section[data-testid="stMain"] span,
section[data-testid="stMain"] h1,
section[data-testid="stMain"] h2,
section[data-testid="stMain"] h3,
section[data-testid="stMain"] h4,
section[data-testid="stMain"] h5,
section[data-testid="stMain"] h6,
section[data-testid="stMain"] p {
    color: var(--pm-text) !important;
}
section[data-testid="stMain"] [data-testid="stCaptionContainer"],
section[data-testid="stMain"] [data-testid="stCaptionContainer"] *,
section[data-testid="stMain"] small {
    color: var(--pm-text-muted) !important;
}
/* Tabs keep their own muted (inactive) / primary (active) coloring rather
   than the blanket fix above — these are more specific so they still win. */
section[data-testid="stMain"] .stTabs [data-baseweb="tab"] p {
    color: var(--pm-text-muted) !important;
}
section[data-testid="stMain"] .stTabs [aria-selected="true"] p {
    color: var(--pm-primary) !important;
}

/* Custom scrollbar */
::-webkit-scrollbar {
    width: 10px;
    height: 10px;
}
::-webkit-scrollbar-track {
    background: transparent;
}
::-webkit-scrollbar-thumb {
    background-color: var(--pm-scrollbar-thumb);
    border-radius: 10px;
    border: 2px solid var(--pm-bg-soft);
}
::-webkit-scrollbar-thumb:hover {
    background-color: var(--pm-scrollbar-thumb-hover);
}

/* ---------------- Sidebar (purple gradient rail) ---------------- */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, var(--pm-sidebar-bg-start) 0%, var(--pm-sidebar-bg-end) 100%);
    border-right: 1px solid var(--pm-sidebar-border);
    box-shadow: 4px 0 24px rgba(0, 0, 0, 0.18);
}
section[data-testid="stSidebar"] * {
    color: var(--pm-sidebar-text);
}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {
    color: #FFFFFF !important;
    letter-spacing: -0.01em;
}

/* Subtle divider glow under headings/hr inside the sidebar */
section[data-testid="stSidebar"] hr {
    border-color: var(--pm-sidebar-border) !important;
    margin: 1rem 0 !important;
}

/* Auto-generated page nav links */
section[data-testid="stSidebarNav"] {
    padding-top: 0.75rem;
}
section[data-testid="stSidebarNav"] a {
    border-radius: 999px;
    margin: 3px 10px;
    padding: 9px 16px !important;
    color: var(--pm-sidebar-text) !important;
    transition: var(--pm-transition);
}
section[data-testid="stSidebarNav"] a:hover {
    background-color: rgba(255, 255, 255, 0.09);
    color: #FFFFFF !important;
    transform: translateX(2px);
}
section[data-testid="stSidebarNav"] a[aria-current="page"] {
    background: var(--pm-sidebar-bg-active);
    color: #FFFFFF !important;
    font-weight: 600;
    box-shadow: 0 4px 14px rgba(124, 58, 237, 0.45);
}
section[data-testid="stSidebarNav"] a[aria-current="page"] span {
    color: #FFFFFF !important;
}

/* Radio-style nav (st.radio used for Navigation) rendered as pills */
section[data-testid="stSidebar"] div[role="radiogroup"] label {
    border-radius: 999px;
    padding: 9px 14px;
    margin-bottom: 4px;
    transition: var(--pm-transition);
}
section[data-testid="stSidebar"] div[role="radiogroup"] label:hover {
    background-color: rgba(255, 255, 255, 0.08);
}
section[data-testid="stSidebar"] div[role="radiogroup"] label[data-checked="true"] {
    background: var(--pm-sidebar-bg-active);
    box-shadow: 0 4px 14px rgba(124, 58, 237, 0.45);
}
section[data-testid="stSidebar"] div[role="radiogroup"] label[data-checked="true"] p {
    color: #FFFFFF !important;
    font-weight: 600;
}

/* Sidebar buttons (e.g. Log out) styled like ghost pills on dark bg */
section[data-testid="stSidebar"] .stButton > button {
    background-color: rgba(255, 255, 255, 0.07);
    color: #FFFFFF;
    border: 1px solid var(--pm-sidebar-border);
    border-radius: 999px;
}
section[data-testid="stSidebar"] .stButton > button:hover {
    background: var(--pm-sidebar-bg-active);
    border-color: transparent;
    box-shadow: 0 4px 14px rgba(124, 58, 237, 0.45);
}

/* Sidebar text inputs / selects on dark background */
section[data-testid="stSidebar"] .stTextInput input,
section[data-testid="stSidebar"] .stTextArea textarea,
section[data-testid="stSidebar"] div[data-baseweb="select"] > div {
    background-color: rgba(255, 255, 255, 0.07) !important;
    border: 1px solid var(--pm-sidebar-border) !important;
    border-radius: var(--pm-radius-sm) !important;
    color: #FFFFFF !important;
}

/* Workspace / caption text sits a bit dimmer than nav labels */
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
section[data-testid="stSidebar"] small {
    color: var(--pm-sidebar-text) !important;
    opacity: 0.75;
}

/* ---------------- Headings ---------------- */
h1, h2, h3 {
    color: var(--pm-navy) !important;
    font-weight: 700 !important;
    letter-spacing: -0.02em;
}
h1 { font-size: 1.9rem !important; margin-bottom: 0.15rem !important; }
h2 { font-size: 1.35rem !important; }
h3 { font-size: 1.1rem !important; }

/* Captions directly under a title read as a page subtitle */
h1 + div [data-testid="stCaptionContainer"] p {
    font-size: 0.95rem !important;
    margin-bottom: 1.4rem !important;
}

/* Captions */
[data-testid="stCaptionContainer"], .stCaption, small {
    color: var(--pm-text-muted) !important;
    line-height: 1.5;
}

/* ---------------- Buttons (indigo/purple primary) ---------------- */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
    background-color: var(--pm-bg);
    color: var(--pm-primary);
    border: 1px solid var(--pm-primary);
    border-radius: var(--pm-radius-sm);
    font-weight: 600;
    padding: 0.5rem 1.1rem;
    box-shadow: var(--pm-shadow);
    transition: var(--pm-transition);
}
.stButton > button:hover, .stDownloadButton > button:hover, .stFormSubmitButton > button:hover {
    background-color: var(--pm-primary);
    color: #FFFFFF;
    border-color: var(--pm-primary);
    box-shadow: var(--pm-shadow-hover);
    transform: translateY(-1px);
}
.stButton > button:active, .stDownloadButton > button:active, .stFormSubmitButton > button:active {
    transform: translateY(0);
}
.stButton > button:focus-visible, .stDownloadButton > button:focus-visible, .stFormSubmitButton > button:focus-visible {
    outline: 2px solid var(--pm-primary);
    outline-offset: 2px;
}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
    background-color: var(--pm-primary);
    color: #FFFFFF;
    border: 1px solid var(--pm-primary);
}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover {
    background-color: var(--pm-primary-dark);
    border-color: var(--pm-primary-dark);
}

/* ---------------- Cards (bordered containers) ---------------- */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background-color: var(--pm-bg);
    border: 1px solid var(--pm-border) !important;
    border-radius: var(--pm-radius-lg);
    padding: 0.25rem;
    box-shadow: var(--pm-shadow);
    transition: var(--pm-transition);
}
div[data-testid="stVerticalBlockBorderWrapper"]:hover {
    box-shadow: var(--pm-shadow-hover);
}

/* ---------------- Metrics (white shadowed card, purple value) ---------------- */
div[data-testid="stMetric"] {
    background-color: var(--pm-bg);
    border: 1px solid var(--pm-border);
    border-radius: var(--pm-radius-lg);
    padding: 1rem 1.1rem 0.7rem 1.1rem;
    box-shadow: var(--pm-shadow);
    transition: var(--pm-transition);
}
div[data-testid="stMetric"]:hover {
    box-shadow: var(--pm-shadow-hover);
    transform: translateY(-1px);
}
div[data-testid="stMetricLabel"] {
    color: var(--pm-text-muted) !important;
    font-weight: 500;
}
div[data-testid="stMetricValue"] {
    color: var(--pm-navy) !important;
    font-weight: 700 !important;
}
div[data-testid="stMetricDelta"] svg {
    color: var(--pm-green) !important;
}

/* ---------------- Tabs ---------------- */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    border-bottom: 1px solid var(--pm-border);
}
.stTabs [data-baseweb="tab"] {
    background-color: transparent;
    border-radius: var(--pm-radius-sm) var(--pm-radius-sm) 0 0;
    color: var(--pm-text-muted);
    padding: 8px 18px;
    font-weight: 500;
    transition: var(--pm-transition);
}
.stTabs [data-baseweb="tab"]:hover {
    background-color: var(--pm-bg-soft);
    color: var(--pm-text);
}
.stTabs [aria-selected="true"] {
    background-color: var(--pm-primary-light);
    color: var(--pm-primary) !important;
    font-weight: 700;
}
.stTabs [aria-selected="true"]:hover {
    background-color: var(--pm-primary-light);
    color: var(--pm-primary) !important;
}
.stTabs [data-baseweb="tab-highlight"] {
    background-color: var(--pm-primary) !important;
    height: 2.5px !important;
    border-radius: 2px;
}

/* ---------------- Inputs ---------------- */
.stTextInput input, .stTextArea textarea, .stNumberInput input,
div[data-baseweb="select"] > div, div[data-baseweb="input"] {
    background-color: var(--pm-bg) !important;
    color: var(--pm-text) !important;
    border: 1px solid var(--pm-border) !important;
    border-radius: var(--pm-radius-sm) !important;
    transition: var(--pm-transition);
}
.stTextInput input::placeholder, .stTextArea textarea::placeholder {
    color: var(--pm-text-muted) !important;
    opacity: 1;
}
.stTextInput input:focus, .stTextArea textarea:focus,
div[data-baseweb="select"] > div:focus-within {
    border-color: var(--pm-primary) !important;
    box-shadow: 0 0 0 1px var(--pm-primary) !important;
}
/* The BaseWeb select's visible value, its dropdown arrow icon, and any
   nested wrapper divs aren't reached by the shallow selector above, so
   without this the select control is left showing its light default
   background/text regardless of theme — the fix here forces every layer
   of it (not just the outer box) to follow the active palette. Scoped to
   the main content area so it doesn't fight the sidebar's own select
   styling (which intentionally stays white-on-dark in both themes).
*/
section[data-testid="stMain"] div[data-baseweb="select"] div,
section[data-testid="stMain"] div[data-baseweb="select"] span {
    background-color: transparent !important;
    color: var(--pm-text) !important;
}
section[data-testid="stMain"] div[data-baseweb="select"] svg {
    fill: var(--pm-text-muted) !important;
}
.stSlider [data-baseweb="slider"] div[role="slider"] {
    background-color: var(--pm-primary) !important;
    border-color: var(--pm-primary) !important;
}
.stCheckbox input[type="checkbox"]:checked ~ span,
.stRadio [role="radiogroup"] label[data-checked="true"] span:first-child {
    accent-color: var(--pm-primary);
}
div[role="radiogroup"] label span:first-child {
    accent-color: var(--pm-primary);
}

/* ---------------- File uploader (drag & drop) ---------------- */
[data-testid="stFileUploaderDropzone"] {
    background-color: var(--pm-bg-soft) !important;
    border: 1.5px dashed #C9CCE0 !important;
    border-radius: var(--pm-radius-lg) !important;
    transition: var(--pm-transition);
}
[data-testid="stFileUploaderDropzone"]:hover {
    border-color: var(--pm-primary) !important;
    background-color: var(--pm-primary-light) !important;
}
[data-testid="stFileUploaderDropzoneInstructions"] svg {
    color: var(--pm-primary) !important;
}
[data-testid="stFileUploaderDropzoneInstructions"] span {
    color: var(--pm-text) !important;
    font-weight: 500;
}
[data-testid="stFileUploaderDropzoneInstructions"] small {
    color: var(--pm-text-muted) !important;
}
[data-testid="stFileUploaderDropzone"] button {
    background-color: var(--pm-bg) !important;
    color: var(--pm-primary) !important;
    border: 1px solid var(--pm-primary) !important;
    border-radius: var(--pm-radius-sm) !important;
    font-weight: 600;
    transition: var(--pm-transition);
}
[data-testid="stFileUploaderDropzone"] button:hover {
    background-color: var(--pm-primary) !important;
    color: #FFFFFF !important;
}
[data-testid="stFileUploaderFile"] {
    background-color: var(--pm-bg) !important;
    border: 1px solid var(--pm-border) !important;
    border-radius: var(--pm-radius-sm) !important;
}

/* ---------------- Dataframes / tables ---------------- */
div[data-testid="stDataFrame"] {
    border: 1px solid var(--pm-border);
    border-radius: 12px;
    overflow: hidden;
    box-shadow: var(--pm-shadow);
}

/* ---------------- Dividers ---------------- */
hr {
    border-color: var(--pm-border) !important;
}

/* ---------------- Alerts ---------------- */
div[data-testid="stAlertContainer"] {
    border-radius: var(--pm-radius-sm);
    box-shadow: var(--pm-shadow);
    border-left: 3px solid transparent;
}
div[data-testid="stAlertContainer"][data-baseweb="notification"] {
    align-items: flex-start;
}
div[data-testid="stAlertContentInfo"] { border-left-color: var(--pm-primary); }
div[data-testid="stAlertContentSuccess"] { border-left-color: var(--pm-green); }
div[data-testid="stAlertContentWarning"] { border-left-color: var(--pm-amber); }
div[data-testid="stAlertContentError"] { border-left-color: var(--pm-red); }

/* ---------------- Chat messages ---------------- */
div[data-testid="stChatMessage"] {
    background-color: var(--pm-bg);
    border: 1px solid var(--pm-border);
    border-radius: var(--pm-radius-lg);
    box-shadow: var(--pm-shadow);
}

/* ---------------- Expanders ---------------- */
details {
    border: 1px solid var(--pm-border) !important;
    border-radius: var(--pm-radius-md) !important;
    background-color: var(--pm-bg);
    box-shadow: var(--pm-shadow);
    transition: var(--pm-transition);
}
details summary {
    border-radius: var(--pm-radius-md) !important;
    font-weight: 600;
}
details[open] summary {
    border-bottom: 1px solid var(--pm-border);
    border-radius: var(--pm-radius-md) var(--pm-radius-md) 0 0 !important;
}

/* ---------------- Progress bar / spinner accent ---------------- */
.stProgress > div > div > div {
    background-color: var(--pm-primary) !important;
}

/* ---------------- Login / signup card centering ---------------- */
div[data-testid="stForm"] {
    background-color: var(--pm-bg);
    border: 1px solid var(--pm-border);
    border-radius: var(--pm-radius-lg);
    padding: 1.75rem;
    box-shadow: var(--pm-shadow);
}
div[data-testid="stForm"] .stButton > button,
div[data-testid="stForm"] .stFormSubmitButton > button {
    margin-top: 0.25rem;
}
</style>
"""


def apply_style(dark_mode: bool = False):
    """
    Inject the shared dashboard theme (dark sidebar + indigo accents +
    light/dark content cards). Call once per page, right after
    `st.set_page_config(...)`.

    `dark_mode` controls which palette gets resolved into the `--pm-*` CSS
    variables that every rule in this file (and the per-screen `_inject_css`
    blocks in screens/dashboard.py, reports.py, ai_chat.py) is written
    against, so passing True actually re-themes the whole app instead of
    just the sidebar.
    """
    css = _CSS_TEMPLATE.replace("__ROOT_VARS__", _build_root_vars(dark_mode))
    st.markdown(css, unsafe_allow_html=True)