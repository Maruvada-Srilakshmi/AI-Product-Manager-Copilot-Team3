"""
Column-agnostic CSV ingestion helpers.

Lets the Data Ingestion page accept ANY CSV — regardless of what its columns
are named — by:
 1. Reading the file robustly (handles different delimiters/encodings).
 2. Guessing which column corresponds to each expected field, using common
    aliases first, then a content-based heuristic as a fallback.
 3. Still letting the user override every guess via a dropdown before
    ingesting, so nothing is ever silently mis-mapped.
"""
import io
import pandas as pd

# Common header aliases per expected field, ordered roughly by likelihood.
FEEDBACK_ALIASES = {
    "text": ["text", "feedback", "review", "comment", "comments", "description",
             "message", "body", "content", "summary", "ticket", "complaint",
             "review_text", "feedback_text", "notes"],
    "source": ["source", "channel", "platform", "origin", "review_source"],
    "customer": ["customer", "user", "username", "name", "author", "reviewer",
                 "company", "client", "customer_name"],
    "rating": ["rating", "score", "stars", "star_rating", "satisfaction"],
    "date": ["date", "created_at", "timestamp", "review_date", "submitted_at", "time"],
}

ANALYTICS_ALIASES = {
    "event_name": ["event_name", "event", "action", "activity", "event_type"],
    "feature": ["feature", "module", "component", "screen", "page"],
    "user_count": ["user_count", "users", "count", "sessions", "hits", "value",
                   "usage", "occurrences"],
    "date": ["date", "event_date", "created_at", "timestamp", "day"],
}


def read_csv_robust(uploaded_file) -> pd.DataFrame:
    """
    Reads a CSV from a Streamlit UploadedFile even if it uses an unusual
    delimiter or encoding. A comma-delimited parse of a semicolon/tab file
    will "succeed" but collapse everything into one column, so we keep
    trying delimiters until one actually splits into multiple columns,
    falling back to the best single-column result only if nothing better
    is found.
    """
    raw_bytes = uploaded_file.getvalue()
    attempts = [
        dict(encoding="utf-8"),
        dict(encoding="utf-8-sig"),
        dict(sep=";", encoding="utf-8"),
        dict(sep="\t", encoding="utf-8"),
        dict(sep=None, engine="python", encoding="utf-8"),
        dict(encoding="latin-1"),
        dict(sep=";", encoding="latin-1"),
        dict(sep=None, engine="python", encoding="latin-1"),
    ]
    best_fallback = None
    last_err = None
    for kwargs in attempts:
        try:
            df = pd.read_csv(io.BytesIO(raw_bytes), **kwargs)
        except Exception as e:
            last_err = e
            continue
        if df.shape[1] > 1:
            return df
        if best_fallback is None and df.shape[1] == 1:
            best_fallback = df

    if best_fallback is not None:
        return best_fallback
    if last_err is not None:
        raise ValueError(f"Could not parse this file as CSV. Last error: {last_err}")
    raise ValueError("Could not parse this file as CSV.")


IDENTIFIER_TOKENS = {"id", "key", "index", "no", "num", "number", "code", "uuid", "pk"}


def _normalize(col: str) -> str:
    return str(col).strip().lower().replace(" ", "_").replace("-", "_")


def _tokens(col: str) -> set:
    return set(t for t in _normalize(col).split("_") if t)


def guess_column(columns, aliases):
    """
    Finds the best-matching column for a list of alias strings, in three
    passes so a generic alias (e.g. "review") can't accidentally grab an
    identifier column (e.g. "review_id") before a better match (e.g.
    "review_comment") is considered:
      1. Exact full-name match.
      2. Alias matches a whole underscore-token, skipping columns that look
         like identifiers (unless the alias itself is identifier-like).
      3. Loose substring match, still skipping identifier-looking columns.
    """
    normalized = {c: _normalize(c) for c in columns}
    tokens_map = {c: _tokens(c) for c in columns}

    # Pass 1: exact match
    for alias in aliases:
        for orig, norm in normalized.items():
            if norm == alias:
                return orig

    # Pass 2: whole-token match, skipping identifier-like columns
    for alias in aliases:
        for orig in columns:
            toks = tokens_map[orig]
            if (IDENTIFIER_TOKENS & toks) and (alias not in IDENTIFIER_TOKENS):
                continue
            if alias in toks:
                return orig

    # Pass 3: loose substring match, still skipping identifier-like columns
    for alias in aliases:
        for orig, norm in normalized.items():
            if IDENTIFIER_TOKENS & tokens_map[orig]:
                continue
            if alias in norm:
                return orig

    return None


def guess_free_text_column(df: pd.DataFrame, exclude: list = None):
    """
    Fallback when no alias matches: pick the text/object column with the
    longest average string length (the most "sentence-like" column), since
    that's almost always the actual feedback content.
    """
    exclude = exclude or []
    candidates = []
    for col in df.columns:
        if col in exclude:
            continue
        series = df[col]
        if pd.api.types.is_string_dtype(series) or series.dtype == object:
            avg_len = series.dropna().astype(str).str.len().mean()
            if pd.notna(avg_len):
                candidates.append((col, avg_len))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0]


def guess_numeric_column(df: pd.DataFrame, exclude: list = None):
    """Fallback: pick the first numeric-looking column not already used."""
    exclude = exclude or []
    for col in df.columns:
        if col in exclude:
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            return col
        coerced = pd.to_numeric(df[col], errors="coerce")
        if coerced.notna().mean() > 0.8:
            return col
    return None


def guess_date_column(df: pd.DataFrame, exclude: list = None):
    """
    Content-based fallback when no header alias matches a date field:
    picks the column whose values parse as dates most successfully.
    Numeric-typed columns are skipped — pandas can otherwise misread small
    integers (e.g. an ID column) as Unix-epoch timestamps.
    """
    exclude = exclude or []
    best_col, best_score = None, 0.0
    for col in df.columns:
        if col in exclude:
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            continue
        try:
            parsed = pd.to_datetime(df[col], errors="coerce")
            score = parsed.notna().mean()
        except Exception:
            score = 0.0
        if score > 0.7 and score > best_score:
            best_col, best_score = col, score
    return best_col


def build_field_options(df: pd.DataFrame):
    """Returns ['— None / use default —', col1, col2, ...] for select boxes."""
    return ["— None / use default —"] + list(df.columns)
