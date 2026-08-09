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
from src.csv_utils import guess_column, guess_free_text_column, FEEDBACK_ALIASES

# Bundled dataset that the workspace is auto-seeded from (no manual upload
# step anymore — see `ensure_dataset_seeded()` below).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATASET_PATH = os.path.join(PROJECT_ROOT, "data", "customer_feedback_dataset.csv")

REQUEST_KEYWORDS = [
    "would like", "wish", "please add", "request", "add a", "add an",
    "suggest", "could you", "hope you", "it would be great", "feature request",
    "can you add", "would love",
]

PRIORITY_STATUSES = ["New", "Under Review", "Planned", "In Progress", "Shipped", "Declined"]
ROADMAP_STATUSES = ["Planned", "In Progress", "Completed", "Delayed"]


def ws_id() -> int:
    return st.session_state["workspace"]["id"]


# ---------------- Fetch helpers ----------------

def fetch_feedback() -> pd.DataFrame:
    return fetch_df("SELECT * FROM feedback WHERE workspace_id = ?", (ws_id(),))


def fetch_features() -> pd.DataFrame:
    return fetch_df(
        "SELECT * FROM feature_requests WHERE workspace_id = ? ORDER BY votes DESC", (ws_id(),)
    )


def fetch_documents() -> pd.DataFrame:
    return fetch_df(
        "SELECT * FROM documents WHERE workspace_id = ? ORDER BY created_at DESC", (ws_id(),)
    )


def fetch_roadmap() -> pd.DataFrame:
    return fetch_df("SELECT * FROM roadmap_items WHERE workspace_id = ?", (ws_id(),))


def fetch_prioritized_backlog() -> pd.DataFrame:
    return fetch_df(
        """SELECT f.id as feature_id, f.title, f.theme, f.votes, f.status,
                  p.reach, p.impact, p.confidence, p.effort, p.rice_score,
                  p.ice_score, p.risk_level, p.ai_rationale
           FROM feature_requests f LEFT JOIN prioritization p ON p.feature_id = f.id
           WHERE f.workspace_id = ? ORDER BY p.rice_score DESC""",
        (ws_id(),),
    )


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
        title = (info["sample"][:60] + "...") if len(info["sample"]) > 60 else info["sample"]
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
    for table in ["prioritization", "feature_requests", "feedback"]:
        conn.execute(f"DELETE FROM {table} WHERE workspace_id = ?", (ws_id(),))
    conn.commit()
    conn.close()

    df = pd.read_csv(DEFAULT_DATASET_PATH)
    return ingest_and_classify(df, os.path.basename(DEFAULT_DATASET_PATH))


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