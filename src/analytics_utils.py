"""
Module 3: Product Analytics Data Integration Module

Ingests product usage / event data (feature clicks, sessions, adoption
counts, etc.) into the `analytics_events` table (already defined in
src/db.py) and provides deterministic aggregation helpers the UI reads from.

Mirrors the shape of src/nlp_utils.py: no LLM call needed here, everything
is computed directly from the ingested rows, so the Product Analytics page
never depends on an API key being configured. Column-agnostic CSV ingestion
reuses the same guess_column()/ANALYTICS_ALIASES machinery in
src/csv_utils.py that the Feedback Ingestion path already uses for the
`feedback` table.
"""
import pandas as pd


def clean_feature_name(name: str) -> str:
    """Normalizes a feature/module name for matching and display."""
    return " ".join(str(name).strip().split())


def usage_by_feature(events: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregates total usage (sum of user_count) per feature, sorted highest
    first. Returns columns: feature, usage, events.
    """
    if events.empty or "feature" not in events.columns:
        return pd.DataFrame(columns=["feature", "usage", "events"])

    df = events.copy()
    df["feature"] = df["feature"].fillna("Unlabeled").apply(clean_feature_name)
    df["user_count"] = pd.to_numeric(df["user_count"], errors="coerce").fillna(0)

    grouped = df.groupby("feature").agg(
        usage=("user_count", "sum"),
        events=("feature", "count"),
    ).reset_index()
    return grouped.sort_values("usage", ascending=False).reset_index(drop=True)


def usage_trend(events: pd.DataFrame) -> pd.DataFrame:
    """
    Buckets total usage by day (falling back to whatever granularity the
    data actually spans), for the adoption-over-time chart.
    Returns columns: date, usage.
    """
    if events.empty or "event_date" not in events.columns:
        return pd.DataFrame(columns=["date", "usage"])

    df = events.copy()
    df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce")
    df = df.dropna(subset=["event_date"])
    if df.empty:
        return pd.DataFrame(columns=["date", "usage"])

    df["user_count"] = pd.to_numeric(df["user_count"], errors="coerce").fillna(0)
    daily = df.groupby(df["event_date"].dt.date)["user_count"].sum().reset_index()
    daily.columns = ["date", "usage"]
    return daily.sort_values("date").reset_index(drop=True)


def event_mix(events: pd.DataFrame) -> pd.DataFrame:
    """Breakdown of total usage by event_name (feature_used, session_start, etc.)."""
    if events.empty or "event_name" not in events.columns:
        return pd.DataFrame(columns=["event_name", "usage"])

    df = events.copy()
    df["event_name"] = df["event_name"].fillna("Unspecified")
    df["user_count"] = pd.to_numeric(df["user_count"], errors="coerce").fillna(0)
    grouped = df.groupby("event_name")["user_count"].sum().reset_index()
    grouped.columns = ["event_name", "usage"]
    return grouped.sort_values("usage", ascending=False).reset_index(drop=True)


def summarize(events: pd.DataFrame) -> dict:
    """Headline metrics for the Product Analytics page's metric cards."""
    if events.empty:
        return {
            "total_events": 0,
            "total_usage": 0,
            "tracked_features": 0,
            "top_feature": None,
            "date_range": None,
        }

    by_feature = usage_by_feature(events)
    trend = usage_trend(events)

    date_range = None
    if not trend.empty:
        date_range = (trend["date"].min(), trend["date"].max())

    return {
        "total_events": int(len(events)),
        "total_usage": int(pd.to_numeric(events.get("user_count"), errors="coerce").fillna(0).sum()),
        "tracked_features": int(by_feature["feature"].nunique()) if not by_feature.empty else 0,
        "top_feature": by_feature.iloc[0]["feature"] if not by_feature.empty else None,
        "date_range": date_range,
    }


# ---------------- Usage vs. demand correlation (ties Module 3 to Module 5) ----------------

_STOPWORD_TOKENS = {
    "the", "a", "an", "and", "or", "for", "to", "of", "in", "on", "with",
    "please", "add", "would", "like", "feature", "request", "support",
    "our", "we", "us", "my", "i",
}


def _tokens(text: str) -> set:
    import re
    words = re.sub(r"[^a-z0-9\s]", " ", str(text).lower()).split()
    return {w for w in words if w not in _STOPWORD_TOKENS and len(w) > 2}


def usage_vs_demand(events: pd.DataFrame, features_df: pd.DataFrame) -> pd.DataFrame:
    """
    Cross-references tracked product features (from analytics_events) with
    customer-requested features (from feature_requests, i.e. Module 5's
    Feature Request Aggregation output) by keyword overlap on their names.

    For every requested feature this surfaces whether the team already has
    usage data for it -- e.g. a heavily-requested feature with zero tracked
    usage is either not shipped yet or shipped-but-undiscovered, while a
    shipped feature with strong usage and few requests is quietly working.

    Returns columns: requested_feature, votes, tracked_feature, usage,
    status (one of "Shipped & used", "Shipped, low usage", "No usage data").

    `requested_feature` is the full, untruncated feedback text (falling
    back to the title only if no description was captured) -- feature_requests.title
    is truncated to ~70 characters for use elsewhere in the app (e.g. the
    Dashboard's "Top Requested Features" legend), which reads as a sentence
    cut off mid-way when shown here at full width. Matching still runs
    against the short title + theme, since that doesn't affect match quality.
    """
    if features_df.empty:
        return pd.DataFrame(columns=["requested_feature", "votes", "tracked_feature", "usage", "status"])

    by_feature = usage_by_feature(events)
    feature_tokens = [(row["feature"], _tokens(row["feature"]), row["usage"]) for _, row in by_feature.iterrows()]

    rows = []
    for _, req in features_df.iterrows():
        title = req.get("title") or ""
        display_text = (req.get("description") or title or "").strip()
        req_tokens = _tokens(title) | _tokens(req.get("theme") or "")

        best_match, best_overlap, best_usage = None, 0, 0
        for name, toks, usage in feature_tokens:
            overlap = len(req_tokens & toks)
            if overlap > best_overlap:
                best_match, best_overlap, best_usage = name, overlap, usage

        if best_match is None:
            status = "No usage data"
            tracked_name, usage_val = None, 0
        elif best_usage < 50:
            status = "Shipped, low usage"
            tracked_name, usage_val = best_match, best_usage
        else:
            status = "Shipped & used"
            tracked_name, usage_val = best_match, best_usage

        rows.append({
            "requested_feature": display_text,
            "votes": int(req.get("votes") or 0),
            "tracked_feature": tracked_name,
            "usage": int(usage_val),
            "status": status,
        })

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values("votes", ascending=False).reset_index(drop=True)