"""
Central SQLite data layer for the AI Product Manager Copilot.
Every module reads/writes through these helpers so the schema lives in one place.
"""
import sqlite3
import os
import datetime as dt

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "data", "copilot.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_column(cursor, table, column, coltype):
    """
    Adds `column` to `table` if it doesn't already exist. SQLite has no
    `ADD COLUMN IF NOT EXISTS`, so this checks PRAGMA table_info first —
    lets init_db() safely evolve the schema on databases that already exist
    on disk (like data/copilot.db) without dropping any data.
    """
    existing = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def init_db():
    conn = get_conn()
    c = conn.cursor()

    # Module 1: Users & Workspaces
    c.execute("""
        CREATE TABLE IF NOT EXISTS workspaces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'Product Manager',
            workspace_id INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
        )
    """)
    # The "Full Name" collected at sign-up (screens/register.py) previously
    # had nowhere to go, so the Profile page fell back to guessing a display
    # name from the email's local part (e.g. "sri1234" for
    # sri1234@gmail.com) -- reads nothing like an actual name. This column
    # stores the real one so it round-trips correctly.
    _ensure_column(c, "users", "name", "TEXT")

    # Module 2: Feedback & Support Tickets
    c.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER,
            source TEXT,
            customer TEXT,
            text TEXT NOT NULL,
            rating REAL,
            created_at TEXT NOT NULL,
            theme TEXT,
            sentiment TEXT,
            sentiment_score REAL
        )
    """)

    # Module 3: Product analytics events
    c.execute("""
        CREATE TABLE IF NOT EXISTS analytics_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER,
            event_name TEXT,
            feature TEXT,
            user_count INTEGER,
            event_date TEXT
        )
    """)

    # Module 5: Feature requests (aggregated from feedback + direct entry)
    c.execute("""
        CREATE TABLE IF NOT EXISTS feature_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER,
            title TEXT NOT NULL,
            description TEXT,
            votes INTEGER DEFAULT 1,
            theme TEXT,
            status TEXT DEFAULT 'New',
            created_at TEXT NOT NULL
        )
    """)

    # Module 6: Prioritization / RICE scoring
    c.execute("""
        CREATE TABLE IF NOT EXISTS prioritization (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER,
            feature_id INTEGER,
            reach INTEGER,
            impact INTEGER,
            confidence INTEGER,
            effort INTEGER,
            rice_score REAL,
            notes TEXT,
            FOREIGN KEY (feature_id) REFERENCES feature_requests (id)
        )
    """)
    # Added for the AI-Based Prioritization & Impact Analysis Engine
    # (src/prioritization_engine.py): ICE score, assessed delivery risk, and
    # the AI's one-line rationale. Added via safe ALTER TABLE migration so
    # existing databases (with rows already in `prioritization`) don't need
    # to be dropped/recreated.
    _ensure_column(c, "prioritization", "ice_score", "REAL")
    _ensure_column(c, "prioritization", "risk_level", "TEXT")
    _ensure_column(c, "prioritization", "ai_rationale", "TEXT")

    # Module 7: Generated PRDs / user stories
    c.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER,
            doc_type TEXT,
            title TEXT,
            content TEXT,
            created_at TEXT NOT NULL
        )
    """)

    # Module 8: Roadmap items
    c.execute("""
        CREATE TABLE IF NOT EXISTS roadmap_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER,
            feature_id INTEGER,
            title TEXT,
            quarter TEXT,
            start_date TEXT,
            end_date TEXT,
            status TEXT DEFAULT 'Planned'
        )
    """)
    # Added for the Roadmap Planning Agent (src/roadmap_agent.py): sprint
    # allocation, dependency planning, milestone planning, release
    # sequencing, and the agent's rationale. Added via safe ALTER TABLE
    # migration so existing databases (with roadmap items already scheduled)
    # don't need to be dropped/recreated.
    _ensure_column(c, "roadmap_items", "sprint", "TEXT")
    _ensure_column(c, "roadmap_items", "depends_on_feature_id", "INTEGER")
    _ensure_column(c, "roadmap_items", "is_milestone", "INTEGER DEFAULT 0")
    _ensure_column(c, "roadmap_items", "sequence_rank", "INTEGER")
    _ensure_column(c, "roadmap_items", "ai_rationale", "TEXT")

    # Module 9: Chat history for conversational assistant
    c.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER,
            role TEXT,
            content TEXT,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def now():
    return dt.datetime.utcnow().isoformat()


# ---------- Auth helpers (used by the Register / Login screens) ----------

def hash_password(password):
    import hashlib
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def get_user_by_username(username):
    """Returns the user row (as a dict) for this username/email, or None."""
    df = fetch_df("SELECT * FROM users WHERE username = ?", (username,))
    if df.empty:
        return None
    return dict(df.iloc[0])


def create_user(username, password, role="Product Manager", workspace_id=None, name=None):
    """
    Creates a new user with a hashed password. Returns the new user's id.
    Raises sqlite3.IntegrityError if the username already exists.
    """
    hashed = hash_password(password)
    return execute(
        "INSERT INTO users (username, password, role, workspace_id, created_at, name) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (username, hashed, role, workspace_id, now(), name),
    )


def verify_user(username, password):
    """Returns the user dict if username/password match a registered user, else None."""
    user = get_user_by_username(username)
    if user and user["password"] == hash_password(password):
        return user
    return None


def get_default_workspace():
    """
    Returns the workspace this single-tenant deployment uses, creating it on
    first run if it doesn't exist yet. Replaces the old login/signup flow —
    there's no multi-account auth anymore, just one shared workspace.

    Also ensures the schema exists: a page can now be the first script run
    in a session (no login step forces app.py to run first), so init_db()
    is called here too rather than relying solely on app.py's call.
    """
    init_db()
    ws = fetch_df("SELECT * FROM workspaces ORDER BY id LIMIT 1")
    if ws.empty:
        ws_id = execute(
            "INSERT INTO workspaces (name, created_at) VALUES (?, ?)",
            ("My Product Workspace", now()),
        )
        ws = fetch_df("SELECT * FROM workspaces WHERE id = ?", (ws_id,))
    return dict(ws.iloc[0])


# ---------- Generic helpers ----------

def fetch_df(query, params=()):
    import pandas as pd
    conn = get_conn()
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def execute(query, params=()):
    conn = get_conn()
    cur = conn.execute(query, params)
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id