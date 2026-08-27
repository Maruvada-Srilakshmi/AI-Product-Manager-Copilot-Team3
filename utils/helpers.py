"""
Frontend-side glue between the Streamlit screens (UI) and the backend data
layer in `src/` (db, nlp_utils, csv_utils, llm). Nothing in `src/` is modified
here — this module only composes those backend functions for the specific
screens in this app.
"""
import os
import re
import streamlit as st
import pandas as pd

from src.db import fetch_df, execute, now, get_conn
from src.nlp_utils import extract_themes, score_sentiment, top_keywords, clean_text
from src.csv_utils import guess_column, guess_free_text_column, guess_numeric_column, \
    guess_date_column, FEEDBACK_ALIASES, ANALYTICS_ALIASES

# Bundled dataset that the workspace is auto-seeded from (no manual upload
# step anymore — see `ensure_dataset_seeded()` below).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATASET_PATH = os.path.join(PROJECT_ROOT, "data", "customer_feedback_dataset.csv")

# Bundled sample usage-event dataset for the Product Analytics Data
# Integration Module (Module 3) — auto-seeded the same way the feedback
# dataset is, so the Product Analytics page always has data to show.
DEFAULT_ANALYTICS_PATH = os.path.join(PROJECT_ROOT, "data", "product_analytics_dataset.csv")

REQUEST_KEYWORDS = [
    "would like", "wish", "please add", "request", "add a", "add an",
    "suggest", "could you", "hope you", "it would be great", "feature request",
    "can you add", "would love",
]

PRIORITY_STATUSES = ["New", "Under Review", "Planned", "In Progress", "Shipped", "Declined"]
ROADMAP_STATUSES = ["Planned", "In Progress", "Completed", "Delayed"]


def ws_id() -> int:
    return st.session_state["workspace"]["id"]


def _truncate_title(text: str, limit: int = 70) -> str:
    """
    Turns a raw feedback string into a short feature title, breaking at the
    nearest word boundary instead of a hard character slice. A plain
    text[:60] regularly cut through the middle of a word — e.g. "...bundling
    Reporting training into onboarding..." became "...bundling Reporting
    training into onboardi..." — which read as a broken/incomplete sentence
    everywhere the title is shown (Dashboard, Reports, Prioritization Engine).
    """
    text = " ".join(text.strip().split())  # collapse internal whitespace/newlines
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last_space = cut.rfind(" ")
    if last_space > limit * 0.5:  # only snap back if it doesn't lose too much of the title
        cut = cut[:last_space]
    return cut.rstrip(",.;:") + "…"


# ---------------- Fetch helpers ----------------

def fetch_feedback() -> pd.DataFrame:
    return fetch_df("SELECT * FROM feedback WHERE workspace_id = ?", (ws_id(),))


def _dedupe_by_feedback_text(df: pd.DataFrame, text_col: str = "description", title_col: str = "title") -> pd.DataFrame:
    """
    Collapses feature-request rows that represent the same underlying
    customer feedback down to one row each. The same feedback can end up
    inserted twice -- once through normal ingestion, and again through the
    "Quick PRD" tool on the PRD Generation page if the same text gets
    pasted in there -- because the two flows compute the row's `title`
    differently (a different character-limit cut of the text), so a
    title-only duplicate check misses it. This showed the same feature
    request twice on the Dashboard, Prioritization Engine, Product
    Analytics, and Reports, all of which read feature requests through
    fetch_features() or fetch_prioritized_backlog() below.

    Matches on the full feedback text instead (normalized: trimmed,
    lowercased, whitespace-collapsed), and keeps whichever duplicate is
    sorted first -- both callers already sort by votes/RICE descending,
    so that's the more complete, higher-voted copy.
    """
    if df.empty:
        return df
    normalized = (df[text_col].fillna(df[title_col]).astype(str)
                  .str.strip().str.lower().str.split().str.join(" "))
    return df[~normalized.duplicated()]


def fetch_features() -> pd.DataFrame:
    df = fetch_df(
        "SELECT * FROM feature_requests WHERE workspace_id = ? ORDER BY votes DESC", (ws_id(),)
    )
    return _dedupe_by_feedback_text(df)


def fetch_documents() -> pd.DataFrame:
    return fetch_df(
        "SELECT * FROM documents WHERE workspace_id = ? ORDER BY created_at DESC", (ws_id(),)
    )


def fetch_roadmap() -> pd.DataFrame:
    return fetch_df("SELECT * FROM roadmap_items WHERE workspace_id = ?", (ws_id(),))


def fetch_analytics() -> pd.DataFrame:
    return fetch_df(
        "SELECT * FROM analytics_events WHERE workspace_id = ? ORDER BY event_date", (ws_id(),)
    )


def fetch_prioritized_backlog() -> pd.DataFrame:
    df = fetch_df(
        """SELECT f.id as feature_id, f.title, f.description, f.theme, f.votes, f.status,
                  p.reach, p.impact, p.confidence, p.effort, p.rice_score,
                  p.ice_score, p.risk_level, p.ai_rationale
           FROM feature_requests f LEFT JOIN prioritization p ON p.feature_id = f.id
           WHERE f.workspace_id = ? ORDER BY p.rice_score DESC""",
        (ws_id(),),
    )
    return _dedupe_by_feedback_text(df)


# ---------------- Roadmap Planning Agent ----------------
# (design doc: Roadmap Agent -- quarterly roadmap, sprint allocation,
# dependency planning, milestone planning, release sequencing. Agent logic
# lives in src/roadmap_agent.py; this section wires it to the
# `roadmap_items` table the same way run_ai_prioritization_engine wires up
# the Prioritization Engine.)

_QUARTER_ORDER = ["Q1", "Q2", "Q3", "Q4"]


def _current_quarter() -> str:
    import datetime as dt
    month = dt.date.today().month
    return _QUARTER_ORDER[(month - 1) // 3]


def _sprint_dates(quarter: str, sprint: int):
    """Maps a (quarter, sprint) pair to a concrete two-week date range,
    anchored to the current calendar year and today's date for the current
    quarter, so AI-planned items land on real, orderable dates the same way
    manually-added items already do."""
    import datetime as dt
    today = dt.date.today()
    quarter_index = _QUARTER_ORDER.index(quarter) if quarter in _QUARTER_ORDER else 0
    current_index = _QUARTER_ORDER.index(_current_quarter())
    quarter_start_month = quarter_index * 3 + 1

    if quarter_index == current_index:
        quarter_start = today
    else:
        year = today.year if quarter_index >= current_index else today.year + 1
        quarter_start = dt.date(year, quarter_start_month, 1)

    sprint_start = quarter_start + dt.timedelta(days=14 * max(sprint - 1, 0))
    sprint_end = sprint_start + dt.timedelta(days=13)
    return sprint_start, sprint_end


def resequence_roadmap():
    """
    Recomputes `sequence_rank` for every roadmap item in the workspace using
    the deterministic release-sequencing tool (topological_sequence), so
    dependent items are always numbered after whatever they depend on.
    Safe to call any time the roadmap or its dependencies change.
    """
    from src.roadmap_agent import topological_sequence

    roadmap = fetch_roadmap()
    if roadmap.empty:
        return

    feature_to_item = {
        int(row["feature_id"]): int(row["id"])
        for _, row in roadmap.iterrows() if pd.notna(row["feature_id"])
    }
    items = []
    for _, row in roadmap.iterrows():
        depends_on_feature = row.get("depends_on_feature_id")
        depends_on_item = (
            feature_to_item.get(int(depends_on_feature))
            if pd.notna(depends_on_feature) else None
        )
        items.append({"id": int(row["id"]), "depends_on_id": depends_on_item})

    for rank, item in enumerate(topological_sequence(items), start=1):
        execute("UPDATE roadmap_items SET sequence_rank = ? WHERE id = ?", (rank, item["id"]))


def run_ai_roadmap_planning(top_n: int = 10):
    """
    Runs the Roadmap Planning Agent over the top `top_n` prioritized
    features that aren't on the roadmap yet: assigns quarter, sprint, and
    milestone flag, and identifies dependencies, via the CrewAI "Roadmap
    Planner" agent in src/roadmap_agent.py (one batched call, not one per
    feature), then schedules everything onto the `roadmap_items` table and
    recomputes release sequencing.

    Any feature the AI call doesn't return a plan for (including a total
    engine failure) falls back to a deterministic heuristic: features are
    spread round-robin across quarters starting at the current quarter,
    sprint 1, no dependency, not flagged as a milestone -- so every
    requested feature always ends up scheduled.

    Returns (summary_dict, error). summary_dict is None only when there
    were no unscheduled features to plan; error is None on a fully
    successful AI run.
    """
    from src.roadmap_agent import run_roadmap_planning_agent

    backlog = fetch_prioritized_backlog().sort_values("rice_score", ascending=False, na_position="last")
    roadmap = fetch_roadmap()
    scheduled_ids = set(roadmap["feature_id"].dropna().astype(int).tolist()) if not roadmap.empty else set()
    unscheduled = backlog[~backlog["feature_id"].isin(scheduled_ids)].head(top_n)

    if unscheduled.empty:
        return None, "No unscheduled features to plan -- everything prioritized is already on the roadmap."

    current_quarter = _current_quarter()
    batch = [
        {
            "id": int(row["feature_id"]),
            "title": row["title"],
            "theme": row.get("theme"),
            "rice_score": float(row["rice_score"]) if pd.notna(row["rice_score"]) else None,
            "votes": int(row["votes"]),
        }
        for _, row in unscheduled.iterrows()
    ]

    results, error = run_roadmap_planning_agent(batch, current_quarter=current_quarter)
    plan_by_id = {p["id"]: p for p in results} if results else {}

    planned = fallback_count = 0
    for idx, f in enumerate(batch):
        plan = plan_by_id.get(f["id"])
        if plan:
            quarter, sprint = plan["quarter"], plan["sprint"]
            depends_on_feature_id = plan["depends_on_id"]
            is_milestone = plan["is_milestone"]
            rationale = plan["rationale"]
            planned += 1
        else:
            quarter = _QUARTER_ORDER[(_QUARTER_ORDER.index(current_quarter) + idx // 3) % 4]
            sprint = 1
            depends_on_feature_id = None
            is_milestone = False
            rationale = "AI planning unavailable -- default quarter assignment used."
            fallback_count += 1

        start, end = _sprint_dates(quarter, sprint)
        execute(
            """INSERT INTO roadmap_items
               (workspace_id, feature_id, title, quarter, start_date, end_date, status,
                sprint, depends_on_feature_id, is_milestone, ai_rationale)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (ws_id(), f["id"], f["title"], quarter, str(start), str(end), "Planned",
             f"Sprint {sprint}", depends_on_feature_id, int(is_milestone), rationale),
        )

    resequence_roadmap()

    summary = {"planned": planned, "fallback": fallback_count, "total": len(batch)}
    return summary, (error if results is None else None)


def schedule_feature_on_roadmap(feature_id: int, title: str, theme: str = None, votes: int = 1):
    """
    Schedules a single feature onto the roadmap immediately after a PRD is
    generated for it -- the "PRD -> Roadmap" handoff: once a PRD exists for
    a feature, it's real enough to plan, so it's placed on the roadmap
    automatically via the Roadmap Planning Agent instead of waiting for a
    separate manual "Run AI Roadmap Planning" pass over the whole backlog.

    If the feature is already scheduled, returns the existing roadmap item
    unchanged (no duplicate). Falls back to a deterministic heuristic
    (current quarter, sprint 1, no dependency, not a milestone) if the AI
    call fails, so the feature always ends up scheduled either way.

    Returns (roadmap_item_dict, error). error is None on success or when
    already scheduled; otherwise it's the AI failure reason (the item is
    still created via the fallback, just not AI-planned).
    """
    from src.roadmap_agent import run_roadmap_planning_agent

    existing = fetch_df(
        "SELECT * FROM roadmap_items WHERE workspace_id = ? AND feature_id = ?", (ws_id(), feature_id)
    )
    if not existing.empty:
        return existing.iloc[0].to_dict(), None

    backlog = fetch_prioritized_backlog()
    rice_row = backlog[backlog["feature_id"] == feature_id]
    rice_score = (
        float(rice_row.iloc[0]["rice_score"])
        if not rice_row.empty and pd.notna(rice_row.iloc[0]["rice_score"]) else None
    )

    current_quarter = _current_quarter()
    batch = [{"id": feature_id, "title": title, "theme": theme, "rice_score": rice_score, "votes": votes}]
    results, error = run_roadmap_planning_agent(batch, current_quarter=current_quarter)
    plan = results[0] if results else None

    if plan:
        quarter, sprint = plan["quarter"], plan["sprint"]
        depends_on_feature_id = plan["depends_on_id"]  # always None for a single-item batch
        is_milestone = plan["is_milestone"]
        rationale = plan["rationale"]
    else:
        quarter, sprint = current_quarter, 1
        depends_on_feature_id, is_milestone = None, False
        rationale = "AI planning unavailable -- default quarter assignment used."

    start, end = _sprint_dates(quarter, sprint)
    execute(
        """INSERT INTO roadmap_items
           (workspace_id, feature_id, title, quarter, start_date, end_date, status,
            sprint, depends_on_feature_id, is_milestone, ai_rationale)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (ws_id(), feature_id, title, quarter, str(start), str(end), "Planned",
         f"Sprint {sprint}", depends_on_feature_id, int(is_milestone), rationale),
    )
    resequence_roadmap()

    new_item = fetch_df(
        "SELECT * FROM roadmap_items WHERE workspace_id = ? AND feature_id = ? ORDER BY id DESC LIMIT 1",
        (ws_id(), feature_id),
    )
    return new_item.iloc[0].to_dict(), (error if plan is None else None)


# ---------------- Ingestion + classification ----------------

def read_any_table(uploaded_file) -> pd.DataFrame:
    """Reads CSV/XLSX into a DataFrame. Returns None for non-tabular files (pdf/docx/txt)."""
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        from src.csv_utils import read_csv_robust
        return read_csv_robust(uploaded_file)
    if name.endswith(".xlsx"):
        return pd.read_excel(uploaded_file)
    return None


def _looks_like_request(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in REQUEST_KEYWORDS)


def ingest_and_classify(df: pd.DataFrame, source_name: str) -> dict:
    """
    Ingests a raw, column-agnostic DataFrame of feedback into the `feedback`
    table (auto-detecting the text column), classifies it into themes +
    sentiment (TF-IDF/KMeans + lexicon scoring, fully offline), and
    auto-promotes request-like feedback into `feature_requests`.

    Returns a summary dict used to render the "AI Analysis" results.
    """
    text_col = guess_column(df.columns, FEEDBACK_ALIASES["text"]) or guess_free_text_column(df)
    if text_col is None:
        return {"ingested": 0, "error": "Couldn't find a text/feedback column in this file."}

    source_col = guess_column(df.columns, FEEDBACK_ALIASES["source"])
    customer_col = guess_column(df.columns, FEEDBACK_ALIASES["customer"])
    rating_col = guess_column(df.columns, FEEDBACK_ALIASES["rating"])
    date_col = guess_column(df.columns, FEEDBACK_ALIASES["date"])

    texts = []
    rows_meta = []
    for _, row in df.iterrows():
        text = str(row.get(text_col, "")).strip()
        if not text or text.lower() == "nan":
            continue
        texts.append(text)
        rows_meta.append({
            "source": str(row.get(source_col)) if source_col else source_name,
            "customer": str(row.get(customer_col)) if customer_col else "Unknown",
            "rating": pd.to_numeric(row.get(rating_col), errors="coerce") if rating_col else None,
            "date": row.get(date_col) if date_col else None,
        })

    if not texts:
        return {"ingested": 0, "error": "No non-empty feedback text found in this file."}

    labels, theme_names = extract_themes(texts)

    conn = get_conn()
    theme_sentiment_counts = {}
    positive = neutral = negative = 0
    promoted_themes = {}

    for text, meta, label in zip(texts, rows_meta, labels):
        theme = theme_names[label]
        sentiment, score = score_sentiment(text)
        rating_val = float(meta["rating"]) if meta["rating"] is not None and pd.notna(meta["rating"]) else None

        # Use the row's own submitted/created date when the file provides one
        # (e.g. a "date_submitted" column) so imported feedback keeps its real
        # timeline instead of every row collapsing onto the moment it was
        # ingested — that collapse is what made trend charts show a single
        # point for bulk imports.
        parsed_date = pd.to_datetime(meta["date"], errors="coerce") if meta["date"] is not None else None
        created_at = parsed_date.isoformat() if parsed_date is not None and pd.notna(parsed_date) else now()

        conn.execute(
            """INSERT INTO feedback
               (workspace_id, source, customer, text, rating, created_at, theme, sentiment, sentiment_score)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (ws_id(), meta["source"], meta["customer"], text, rating_val, created_at, theme, sentiment, score),
        )

        if sentiment == "Positive":
            positive += 1
        elif sentiment == "Negative":
            negative += 1
        else:
            neutral += 1

        theme_sentiment_counts.setdefault(theme, {"Positive": 0, "Neutral": 0, "Negative": 0})
        theme_sentiment_counts[theme][sentiment] += 1

        if _looks_like_request(text):
            promoted_themes.setdefault(theme, {"count": 0, "sample": text})
            promoted_themes[theme]["count"] += 1

    conn.commit()
    conn.close()

    # Auto-promote request-like feedback into tracked feature requests (dedupe by theme+title)
    for theme, info in promoted_themes.items():
        title = _truncate_title(info["sample"])
        existing = fetch_df(
            "SELECT id, votes FROM feature_requests WHERE workspace_id = ? AND theme = ?",
            (ws_id(), theme),
        )
        if existing.empty:
            execute(
                """INSERT INTO feature_requests
                   (workspace_id, title, description, votes, theme, status, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (ws_id(), title, info["sample"], info["count"], theme, "New", now()),
            )
        else:
            execute(
                "UPDATE feature_requests SET votes = votes + ? WHERE id = ?",
                (info["count"], int(existing.iloc[0]["id"])),
            )

    total = len(texts)
    top_issue_themes = sorted(
        ((t, c["Negative"]) for t, c in theme_sentiment_counts.items() if c["Negative"] > 0),
        key=lambda x: x[1], reverse=True,
    )[:5]

    return {
        "ingested": total,
        "positive_pct": round(100 * positive / total),
        "neutral_pct": round(100 * neutral / total),
        "negative_pct": round(100 * negative / total),
        "top_issues": top_issue_themes,
        "promoted_features": sorted(promoted_themes.items(), key=lambda x: x[1]["count"], reverse=True)[:5],
        "keywords": top_keywords(texts, k=8)["keyword"].tolist(),
    }


# ---------------- Automatic dataset seeding (replaces manual upload) ----------------

def dataset_already_loaded() -> bool:
    """True once this workspace's `feedback` table has been populated."""
    df = fetch_df("SELECT COUNT(*) AS c FROM feedback WHERE workspace_id = ?", (ws_id(),))
    return not df.empty and int(df.iloc[0]["c"]) > 0


def ensure_dataset_seeded() -> dict | None:
    """
    Loads the bundled `data/customer_feedback_dataset.csv` straight into the
    database and runs it through the same AI classification pipeline used
    everywhere else in the app (theme clustering, sentiment scoring,
    feature-request auto-promotion). There is no manual upload step anymore:
    this runs once automatically (on first launch, when `feedback` is empty)
    so the Dashboard always reflects data that's already in the database.

    Returns the ingestion summary dict the first time it seeds, or None if
    the workspace already has data (or the bundled file is missing).
    """
    if dataset_already_loaded():
        return None
    if not os.path.exists(DEFAULT_DATASET_PATH):
        return None

    df = pd.read_csv(DEFAULT_DATASET_PATH)
    return ingest_and_classify(df, os.path.basename(DEFAULT_DATASET_PATH))


def reload_dataset() -> dict:
    """
    Wipes this workspace's derived data (feedback / feature requests /
    prioritization) and re-ingests the bundled dataset from scratch. Used by
    the "Reload dataset" control in Settings so the database can be
    reprocessed on demand without a manual upload screen.
    """
    conn = get_conn()
    # Delete child tables before the parent they reference — `prioritization`
    # has a FOREIGN KEY on feature_requests.id, so it must be cleared first or
    # SQLite raises "FOREIGN KEY constraint failed" when feature_requests rows
    # (still referenced by leftover prioritization rows) are deleted.
    for table in ["prioritization", "theme_validations", "feature_requests", "feedback"]:
        conn.execute(f"DELETE FROM {table} WHERE workspace_id = ?", (ws_id(),))
    conn.commit()
    conn.close()

    df = pd.read_csv(DEFAULT_DATASET_PATH)
    return ingest_and_classify(df, os.path.basename(DEFAULT_DATASET_PATH))


# ---------------- Product Analytics Data Integration (Module 3) ----------------

def ingest_analytics(df: pd.DataFrame, source_name: str) -> dict:
    """
    Ingests a raw, column-agnostic DataFrame of product usage/analytics
    events into the `analytics_events` table, auto-detecting which column
    is which via ANALYTICS_ALIASES (same guess_column() approach
    ingest_and_classify() uses for feedback), with content-based fallbacks
    for whichever fields don't match a known header alias.

    Returns a summary dict: {"ingested": int} or {"ingested": 0, "error": str}.
    """
    feature_col = guess_column(df.columns, ANALYTICS_ALIASES["feature"])
    event_col = guess_column(df.columns, ANALYTICS_ALIASES["event_name"])
    count_col = guess_column(df.columns, ANALYTICS_ALIASES["user_count"]) or \
        guess_numeric_column(df, exclude=[feature_col, event_col])
    date_col = guess_column(df.columns, ANALYTICS_ALIASES["date"]) or \
        guess_date_column(df, exclude=[feature_col, event_col, count_col])

    if feature_col is None:
        feature_col = guess_free_text_column(df, exclude=[event_col, date_col])
    if feature_col is None:
        return {"ingested": 0, "error": "Couldn't find a feature/module column in this file."}

    conn = get_conn()
    ingested = 0
    for _, row in df.iterrows():
        feature = str(row.get(feature_col, "")).strip()
        if not feature or feature.lower() == "nan":
            continue

        event_name = str(row.get(event_col)).strip() if event_col and pd.notna(row.get(event_col)) else "feature_used"
        count_val = pd.to_numeric(row.get(count_col), errors="coerce") if count_col else None
        user_count = int(count_val) if count_val is not None and pd.notna(count_val) else 1
        event_date = row.get(date_col) if date_col else None
        parsed_date = pd.to_datetime(event_date, errors="coerce") if event_date is not None else None
        event_date_str = parsed_date.date().isoformat() if parsed_date is not None and pd.notna(parsed_date) else now()[:10]

        conn.execute(
            """INSERT INTO analytics_events
               (workspace_id, event_name, feature, user_count, event_date)
               VALUES (?,?,?,?,?)""",
            (ws_id(), event_name, feature, user_count, event_date_str),
        )
        ingested += 1

    conn.commit()
    conn.close()

    if ingested == 0:
        return {"ingested": 0, "error": "No usable rows found in this file."}
    return {"ingested": ingested, "source": source_name}


def analytics_already_loaded() -> bool:
    """True once this workspace's `analytics_events` table has been populated."""
    df = fetch_df("SELECT COUNT(*) AS c FROM analytics_events WHERE workspace_id = ?", (ws_id(),))
    return not df.empty and int(df.iloc[0]["c"]) > 0


def ensure_analytics_seeded() -> dict | None:
    """
    Loads the bundled `data/product_analytics_dataset.csv` straight into
    the `analytics_events` table on first launch (mirrors
    `ensure_dataset_seeded()` for feedback), so the Product Analytics page
    always has data without requiring a manual upload step.

    Returns the ingestion summary the first time it seeds, or None if the
    workspace already has analytics data (or the bundled file is missing).
    """
    if analytics_already_loaded():
        return None
    if not os.path.exists(DEFAULT_ANALYTICS_PATH):
        return None

    df = pd.read_csv(DEFAULT_ANALYTICS_PATH)
    return ingest_analytics(df, os.path.basename(DEFAULT_ANALYTICS_PATH))


def reload_analytics() -> dict:
    """Wipes this workspace's analytics_events rows and re-ingests the bundled dataset from scratch."""
    conn = get_conn()
    conn.execute("DELETE FROM analytics_events WHERE workspace_id = ?", (ws_id(),))
    conn.commit()
    conn.close()

    df = pd.read_csv(DEFAULT_ANALYTICS_PATH)
    return ingest_analytics(df, os.path.basename(DEFAULT_ANALYTICS_PATH))


def analytics_summary() -> dict:
    """Headline metrics + trend/usage tables for the Product Analytics page."""
    from src.analytics_utils import summarize, usage_by_feature, usage_trend, event_mix
    events = fetch_analytics()
    return {
        "metrics": summarize(events),
        "by_feature": usage_by_feature(events),
        "trend": usage_trend(events),
        "event_mix": event_mix(events),
    }


def analytics_vs_demand() -> pd.DataFrame:
    """Cross-references tracked usage with customer-requested features (Module 3 x Module 5)."""
    from src.analytics_utils import usage_vs_demand
    return usage_vs_demand(fetch_analytics(), fetch_features())


# ---------------- Theme Extraction Agent (Module: Theme Agent) ----------------

def theme_frequency_table(top_n: int = 6) -> pd.DataFrame:
    """
    Theme + frequency table for the Dashboard's Theme Extraction Agent panel —
    mirrors the design doc's Theme Agent example output (Theme | Frequency).
    Built instantly from the `feedback.theme` column already populated by the
    offline TF-IDF/KMeans clustering step in `ingest_and_classify()`, so it
    needs no LLM call to render.
    """
    feedback = fetch_feedback()
    if feedback.empty or "theme" not in feedback.columns or feedback["theme"].isna().all():
        return pd.DataFrame(columns=["theme", "frequency"])
    counts = feedback["theme"].value_counts().head(top_n).reset_index()
    counts.columns = ["theme", "frequency"]
    return counts


def run_theme_agent_enrichment(top_n: int = 6, timeout: int = 45):
    """
    Runs the LLM-based Theme Extraction Agent (`src/theme_agent.py`) over the
    workspace's top N themes, adding pain-point identification + intent
    detection on top of the theme/frequency/sentiment already stored in the
    DB. Returns a (result, error) tuple — result is a list of dicts (theme,
    sentiment, pain_points, intent) or None; error is None on success or a
    human-readable reason otherwise — callers should fall back to
    `theme_frequency_table()` and may show `error` to the user.
    """
    feedback = fetch_feedback()
    if feedback.empty or "theme" not in feedback.columns:
        return None, "No classified feedback yet."

    freq = theme_frequency_table(top_n=top_n)
    if freq.empty:
        return None, "No themes to enrich yet."

    samples_by_theme = {
        theme: feedback.loc[feedback["theme"] == theme, "text"].dropna().head(4).tolist()
        for theme in freq["theme"]
    }

    from src.theme_agent import run_theme_extraction_agent
    return run_theme_extraction_agent(samples_by_theme, timeout=timeout)


# ---------------- Accuracy Validation (issue detection + feature grouping) ----------------
# Lets a reviewer confirm or correct the theme the TF-IDF/KMeans clustering
# step (src/nlp_utils.extract_themes, run from ingest_and_classify) assigned
# to a piece of feedback ("issue detection") or a feature request ("feature
# grouping"), and reports the resulting accuracy — closing the loop the
# app previously had no way to measure.

VALIDATION_ITEM_TABLES = {
    "feedback": {"table": "feedback", "label_col": "text", "theme_col": "theme"},
    # Feature requests store a shortened `title` (see _truncate_title above,
    # used for compact display on the Dashboard/Reports/Prioritization
    # Engine) separately from the full, untruncated `description`. The
    # validation queue needs the reviewer to see the complete original
    # feedback text, so it reads `description` here, not `title`.
    "feature_request": {"table": "feature_requests", "label_col": "description", "theme_col": "theme"},
}


def available_theme_labels() -> list:
    """
    Distinct themes already assigned across feedback and feature requests,
    used to populate the "correct theme" choices when a reviewer marks an
    item as incorrectly clustered/grouped.
    """
    feedback = fetch_feedback()
    features = fetch_features()
    themes = set()
    if not feedback.empty and "theme" in feedback.columns:
        themes.update(t for t in feedback["theme"].dropna().unique().tolist() if t)
    if not features.empty and "theme" in features.columns:
        themes.update(t for t in features["theme"].dropna().unique().tolist() if t)
    return sorted(themes)


def theme_validation_queue(item_type: str, limit: int = 10) -> pd.DataFrame:
    """
    Returns up to `limit` items of the given type ("feedback" or
    "feature_request") that haven't been reviewed yet, alongside the theme
    the clustering step assigned. Drives the review queue in the accuracy
    validation panel so a reviewer works through unreviewed items instead of
    re-seeing ones already validated.
    """
    spec = VALIDATION_ITEM_TABLES[item_type]
    already_validated = fetch_df(
        "SELECT item_id FROM theme_validations WHERE workspace_id = ? AND item_type = ?",
        (ws_id(), item_type),
    )
    validated_ids = set(already_validated["item_id"].tolist()) if not already_validated.empty else set()

    df = fetch_df(
        f"SELECT id, {spec['label_col']} as label, {spec['theme_col']} as theme "
        f"FROM {spec['table']} WHERE workspace_id = ? AND theme IS NOT NULL AND theme != ''",
        (ws_id(),),
    )
    if df.empty:
        return df
    if validated_ids:
        df = df[~df["id"].isin(validated_ids)]
    return df.head(limit)


def record_theme_validation(item_type: str, item_id: int, original_theme: str,
                             is_correct: bool, corrected_theme: str = None):
    """
    Records a reviewer's verdict on a single item's AI-assigned theme.
    Upserts on (workspace, item_type, item_id) so re-reviewing an item
    updates its existing verdict instead of creating a duplicate. On an
    "incorrect" verdict with a corrected theme supplied, also writes that
    correction back onto the source row (feedback.theme or
    feature_requests.theme) so the review actually fixes the grouping, not
    just the accuracy tally.
    """
    spec = VALIDATION_ITEM_TABLES[item_type]
    conn = get_conn()
    conn.execute(
        """INSERT INTO theme_validations
           (workspace_id, item_type, item_id, original_theme, is_correct, corrected_theme, validated_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(workspace_id, item_type, item_id) DO UPDATE SET
             original_theme = excluded.original_theme,
             is_correct = excluded.is_correct,
             corrected_theme = excluded.corrected_theme,
             validated_at = excluded.validated_at""",
        (ws_id(), item_type, int(item_id), original_theme, 1 if is_correct else 0,
         corrected_theme, now()),
    )
    if not is_correct and corrected_theme:
        conn.execute(
            f"UPDATE {spec['table']} SET {spec['theme_col']} = ? WHERE id = ? AND workspace_id = ?",
            (corrected_theme, int(item_id), ws_id()),
        )
    conn.commit()
    conn.close()


def theme_validation_summary() -> dict:
    """
    Aggregate accuracy metrics for issue detection (feedback theming) and
    feature grouping (feature-request theming), plus an overall figure
    across both, computed from every review recorded so far. Returns a dict
    the accuracy validation panel renders as metric cards; every count is 0
    and accuracy is None until at least one item has been reviewed.
    """
    rows = fetch_df(
        "SELECT item_type, is_correct FROM theme_validations WHERE workspace_id = ?",
        (ws_id(),),
    )

    def _bucket(df: pd.DataFrame) -> dict:
        total = len(df)
        correct = int(df["is_correct"].sum()) if total else 0
        accuracy = round(100.0 * correct / total, 1) if total else None
        return {"total": total, "correct": correct, "incorrect": total - correct, "accuracy": accuracy}

    overall = _bucket(rows)
    feedback_rows = rows[rows["item_type"] == "feedback"] if not rows.empty else rows
    feature_rows = rows[rows["item_type"] == "feature_request"] if not rows.empty else rows

    return {
        "overall": overall,
        "feedback": _bucket(feedback_rows),
        "feature_request": _bucket(feature_rows),
    }


# ---------------- Prioritization (RICE) ----------------

def priority_bucket(rice_score) -> str:
    if rice_score is None or pd.isna(rice_score):
        return "Medium"
    if rice_score >= 60:
        return "High"
    if rice_score >= 25:
        return "Medium"
    return "Low"


def ensure_rice_score(feature_row) -> dict:
    """
    Fetches the saved RICE score for a feature request, or computes a
    reasonable default (Reach = votes*10, Impact = 3, Confidence = 80%,
    Effort = 2 person-months) and persists it, so every feature always has
    a prioritized score without requiring manual data entry per feature.
    """
    existing = fetch_df(
        "SELECT * FROM prioritization WHERE workspace_id = ? AND feature_id = ?",
        (ws_id(), int(feature_row["id"])),
    )
    if not existing.empty:
        return dict(existing.iloc[0])

    reach = int(feature_row["votes"]) * 10
    impact, confidence, effort = 3, 80, 2.0
    rice = (reach * impact * (confidence / 100)) / max(effort, 0.1)
    execute(
        """INSERT INTO prioritization
           (workspace_id, feature_id, reach, impact, confidence, effort, rice_score, notes)
           VALUES (?,?,?,?,?,?,?,?)""",
        (ws_id(), int(feature_row["id"]), reach, impact, confidence, effort, rice, ""),
    )
    return {"reach": reach, "impact": impact, "confidence": confidence, "effort": effort, "rice_score": rice}


def save_rice_score(feature_id: int, reach, impact, confidence, effort):
    rice = (reach * impact * (confidence / 100)) / max(effort, 0.1)
    existing = fetch_df(
        "SELECT id FROM prioritization WHERE workspace_id = ? AND feature_id = ?", (ws_id(), feature_id)
    )
    if existing.empty:
        execute(
            """INSERT INTO prioritization
               (workspace_id, feature_id, reach, impact, confidence, effort, rice_score, notes)
               VALUES (?,?,?,?,?,?,?,?)""",
            (ws_id(), feature_id, reach, impact, confidence, effort, rice, ""),
        )
    else:
        execute(
            "UPDATE prioritization SET reach=?, impact=?, confidence=?, effort=?, rice_score=? WHERE id=?",
            (reach, impact, confidence, effort, rice, int(existing.iloc[0]["id"])),
        )
    return rice


# ---------------- AI-Based Prioritization & Impact Analysis Engine ----------------
# (design doc: Prioritization Agent — RICE, ICE, effort estimate, risk
# assessment, priority recommendation. Agent logic lives in
# src/prioritization_engine.py; this section wires it to the `prioritization`
# table the same way run_theme_agent_enrichment wires up the Theme Agent.)

def save_prioritization_result(feature_id: int, reach, impact, confidence, effort, risk=None, rationale=None):
    """
    Like save_rice_score(), but also persists the AI-derived ICE score, the
    assessed delivery risk, and the AI's rationale from the Prioritization
    Engine.
    """
    from src.prioritization_engine import compute_rice, compute_ice
    rice = compute_rice(reach, impact, confidence, effort)
    ice = compute_ice(impact, confidence, effort)

    existing = fetch_df(
        "SELECT id FROM prioritization WHERE workspace_id = ? AND feature_id = ?", (ws_id(), feature_id)
    )
    if existing.empty:
        execute(
            """INSERT INTO prioritization
               (workspace_id, feature_id, reach, impact, confidence, effort, rice_score,
                ice_score, risk_level, ai_rationale, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (ws_id(), feature_id, reach, impact, confidence, effort, rice, ice, risk, rationale, ""),
        )
    else:
        execute(
            """UPDATE prioritization SET reach=?, impact=?, confidence=?, effort=?, rice_score=?,
               ice_score=?, risk_level=?, ai_rationale=? WHERE id=?""",
            (reach, impact, confidence, effort, rice, ice, risk, rationale, int(existing.iloc[0]["id"])),
        )
    return {"rice_score": rice, "ice_score": ice}


def run_ai_prioritization_engine(top_n: int = 15):
    """
    Runs the AI-Based Prioritization & Impact Analysis Engine over the top
    `top_n` feature requests by customer votes: scores impact, effort,
    confidence, and risk via the CrewAI "Impact & Risk Analyst" agent in
    `src/prioritization_engine.py` (one batched call, not one per feature),
    computes RICE + ICE from those scores, and persists everything to the
    `prioritization` table.

    Any feature the AI call doesn't return a score for (including a total
    engine failure — no API key, crewai unavailable, timeout) falls back to
    the same votes-based heuristic `ensure_rice_score()` already uses
    (impact=3, confidence=80%, effort=2 person-months, risk="Medium"), so
    every feature always ends up prioritized.

    Returns (summary_dict, error). summary_dict is None only when there
    were no feature requests at all to analyze; error is None on a fully
    successful AI run, or the engine's failure reason when any/all features
    fell back to the heuristic.
    """
    from src.prioritization_engine import run_prioritization_engine

    features_df = fetch_features()
    if features_df.empty:
        return None, "No feature requests to analyze yet."

    feedback = fetch_feedback()
    top = features_df.sort_values("votes", ascending=False).head(top_n)

    batch = []
    for _, row in top.iterrows():
        samples = []
        if not feedback.empty and "theme" in feedback.columns:
            samples = feedback.loc[feedback["theme"] == row["theme"], "text"].dropna().head(3).tolist()
        batch.append({
            "id": int(row["id"]),
            "title": row["title"],
            "description": row.get("description"),
            "theme": row.get("theme"),
            "votes": int(row["votes"]),
            "sample_feedback": samples,
        })

    results, error = run_prioritization_engine(batch)
    scored_by_id = {r["id"]: r for r in results} if results else {}

    analyzed = fallback_count = 0
    for f in batch:
        reach = f["votes"] * 10
        scored = scored_by_id.get(f["id"])
        if scored:
            save_prioritization_result(
                f["id"], reach, scored["impact"], scored["confidence"], scored["effort"],
                risk=scored["risk"], rationale=scored["rationale"],
            )
            analyzed += 1
        else:
            save_prioritization_result(
                f["id"], reach, 3, 80, 2.0, risk="Medium",
                rationale="AI scoring unavailable — default estimate used.",
            )
            fallback_count += 1

    summary = {"analyzed": analyzed, "fallback": fallback_count, "total": len(batch)}
    return summary, (error if results is None else None)


# ---------------- Chat context (Module 9) ----------------

def build_chat_context(question: str) -> str:
    """Lightweight keyword-overlap retrieval across feedback/features/roadmap, grounding the assistant."""
    q_words = set(clean_text(question).split())
    if not q_words:
        return ""

    parts = []
    feedback = fetch_feedback()
    if not feedback.empty:
        feedback = feedback.copy()
        feedback["overlap"] = feedback["text"].fillna("").apply(
            lambda t: len(q_words & set(clean_text(t).split()))
        )
        top_fb = feedback.sort_values("overlap", ascending=False).head(5)
        if top_fb["overlap"].sum() > 0:
            parts.append("Relevant feedback:\n" + "\n".join(
                f"- ({r.theme}, {r.sentiment}) {r.text}" for r in top_fb.itertuples()
            ))

    features = fetch_prioritized_backlog()
    if not features.empty:
        parts.append("Feature requests (title, theme, votes, status, RICE score):\n" + "\n".join(
            f"- {r.title} | {r.theme} | {r.votes} votes | {r.status} | RICE {r.rice_score}"
            for r in features.itertuples()
        ))

    roadmap = fetch_roadmap()
    if not roadmap.empty:
        parts.append("Roadmap:\n" + "\n".join(
            f"- {r.title} ({r.quarter}, {r.status})" for r in roadmap.itertuples()
        ))

    return "\n\n".join(parts) if parts else "No matching workspace data found for this question."