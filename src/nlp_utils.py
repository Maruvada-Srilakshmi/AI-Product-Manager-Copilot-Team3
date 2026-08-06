"""
Module 4: Feedback Classification & Theme Extraction Engine
Module 5 support: clustering helper reused for feature request aggregation

Uses TF-IDF + KMeans so it works fully offline with no LLM key required.
A lexicon-based sentiment scorer keeps things dependency-light (no heavy
model download needed inside the sandbox).
"""
import re
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans

POSITIVE_WORDS = {
    "great", "good", "love", "excellent", "amazing", "helpful", "easy",
    "fast", "intuitive", "reliable", "smooth", "awesome", "like", "happy",
    "impressed", "useful", "simple", "clean", "nice", "works"
}
NEGATIVE_WORDS = {
    "bad", "slow", "confusing", "broken", "crash", "bug", "hate", "difficult",
    "frustrating", "annoying", "poor", "fail", "error", "issue", "problem",
    "terrible", "awful", "missing", "lacking", "complicated", "unusable",
    "delay", "delayed", "disappointed", "unreliable"
}


def clean_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"http\S+", "", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def score_sentiment(text: str):
    words = clean_text(text).split()
    if not words:
        return "Neutral", 0.0
    pos = sum(1 for w in words if w in POSITIVE_WORDS)
    neg = sum(1 for w in words if w in NEGATIVE_WORDS)
    score = (pos - neg) / max(len(words), 1)
    if pos == neg:
        label = "Neutral"
    elif pos > neg:
        label = "Positive"
    else:
        label = "Negative"
    return label, round(float(score), 3)


def extract_themes(texts: list, n_clusters: int = None):
    """
    Cluster a list of feedback strings into themes.
    Returns: (labels: list[int], theme_names: dict[int -> str])
    """
    cleaned = [clean_text(t) for t in texts]
    non_empty_idx = [i for i, t in enumerate(cleaned) if t]
    if len(non_empty_idx) < 2:
        return [0] * len(texts), {0: "General Feedback"}

    n = len(non_empty_idx)
    if n_clusters is None:
        n_clusters = max(2, min(6, n // 4 if n // 4 >= 2 else 2))
    n_clusters = min(n_clusters, n)

    vectorizer = TfidfVectorizer(max_features=500, stop_words="english", ngram_range=(1, 2))
    X = vectorizer.fit_transform([cleaned[i] for i in non_empty_idx])

    km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    sub_labels = km.fit_predict(X)

    # Build human-readable theme names from top TF-IDF terms per cluster
    terms = np.array(vectorizer.get_feature_names_out())
    theme_names = {}
    for cluster_id in range(n_clusters):
        centroid = km.cluster_centers_[cluster_id]
        top_idx = centroid.argsort()[::-1][:3]
        top_terms = [t for t in terms[top_idx] if t]
        theme_names[cluster_id] = " / ".join(top_terms).title() if top_terms else f"Theme {cluster_id + 1}"

    labels = [0] * len(texts)
    for pos, orig_idx in enumerate(non_empty_idx):
        labels[orig_idx] = int(sub_labels[pos])

    return labels, theme_names


def top_keywords(texts: list, k: int = 15):
    cleaned = [clean_text(t) for t in texts if clean_text(t)]
    if not cleaned:
        return pd.DataFrame(columns=["keyword", "score"])
    vectorizer = TfidfVectorizer(max_features=200, stop_words="english", ngram_range=(1, 2))
    X = vectorizer.fit_transform(cleaned)
    scores = np.asarray(X.sum(axis=0)).flatten()
    terms = vectorizer.get_feature_names_out()
    df = pd.DataFrame({"keyword": terms, "score": scores}).sort_values("score", ascending=False).head(k)
    return df.reset_index(drop=True)
