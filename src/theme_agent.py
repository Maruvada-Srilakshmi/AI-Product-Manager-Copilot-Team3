"""
Theme Extraction Agent (Module: Theme Agent, per AI PM Copilot Multi-Agent
System Design).

Goal (from the architecture doc): "Discover recurring customer pain points."

Responsibilities implemented here, matching the design doc's Theme Agent
section:
 - Topic extraction
 - Theme classification
 - Sentiment analysis
 - Pain point identification
 - Intent detection

Example output shape mirrors the doc:

    | Theme               | Frequency |
    |----------------------|-----------|
    | Login Issues         | 124       |
    | Dashboard Performance | 89       |
    | Export Problems      | 61        |

...extended per-theme with a sentiment label, a one-line pain-point summary,
and a detected intent (Bug Report / Feature Request / Question / Complaint /
Praise), so the Dashboard can surface more than a bare frequency count.

This module is a standalone, single-responsibility agent (its own file,
mirroring `orchestrator_agent.py` / `theme_agent.py` in the design doc's
`backend/agents/` layout) built as a CrewAI single-agent crew on top of the
same Gemini LLM + resilience/fallback plumbing already used by
`src/agents.py` (auth errors fail fast, transient errors retry with
backoff, model candidates are tried in order). It returns `None` on any
failure — no API key, `crewai` missing, timeout, bad response — so callers
can fall back to the offline TF-IDF/lexicon path in `src/nlp_utils.py`,
which already powers the base theme/sentiment columns stored in the
`feedback` table.
"""
import json
import re

from src.agents import _get_llm, _run_crew_with_resilience

VALID_INTENTS = {"Bug Report", "Feature Request", "Question", "Complaint", "Praise"}
VALID_SENTIMENTS = {"Positive", "Neutral", "Negative"}


def _extract_json_array(text: str):
    """Pulls the first JSON array out of a model response, tolerating stray
    prose or ```json fences around it."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    match = re.search(r"\[.*\]", cleaned, flags=re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            return None
    return None


def run_theme_extraction_agent(samples_by_theme: dict, timeout: int = 45):
    """
    Runs the Theme Extraction Agent over a dict of {theme_name: [sample feedback
    strings]} (themes + frequencies are already known from the offline
    clustering step — this agent enriches them with sentiment, pain points,
    and intent, per the design doc's Theme Agent responsibilities).

    Returns a (result, error) tuple:
        result: list of {"theme", "sentiment", "pain_points", "intent"} dicts, or None
        error:  None on success, otherwise a human-readable reason (no key,
                crewai/litellm import error, the actual API error string, a
                timeout message, or a parse failure) so callers can show the
                *real* cause instead of a generic "unavailable" message.
    """
    try:
        from crewai import Agent, Task, Crew, Process
    except Exception as e:
        return None, f"crewai is not installed/importable: {e}"

    if not samples_by_theme:
        return None, "No themes available to enrich yet."

    themes_block = "\n\n".join(
        f"Theme: {theme}\nSample feedback:\n" + "\n".join(f"- {s}" for s in samples[:4])
        for theme, samples in samples_by_theme.items()
    )

    def _build_and_run(model_id):
        llm = _get_llm(model_id, temperature=0.3)

        theme_agent = Agent(
            role="Theme Extraction Agent",
            goal="Discover recurring customer pain points by extracting topics, classifying "
                 "themes, scoring sentiment, identifying pain points, and detecting intent.",
            backstory=(
                "You are a customer-insights specialist who reads clustered product feedback "
                "and turns it into structured, decision-ready theme intelligence for a product "
                "manager: what the theme is really about, how customers feel, the concrete pain "
                "point behind it, and what customers are asking for."
            ),
            llm=llm,
            verbose=False,
        )

        task = Task(
            description=(
                "For EACH theme below, perform: (1) topic extraction — confirm what the theme "
                "is really about from the sample feedback; (2) sentiment analysis — an overall "
                "label of Positive, Neutral, or Negative; (3) pain point identification — a "
                "single concise sentence naming the concrete underlying problem; (4) intent "
                "detection — classify the dominant customer intent as exactly one of: "
                "Bug Report, Feature Request, Question, Complaint, Praise.\n\n"
                f"{themes_block}\n\n"
                "Respond with ONLY a JSON array (no prose, no markdown fences), one object per "
                "theme, each shaped exactly as: "
                '{"theme": "<theme name as given>", "sentiment": "Positive|Neutral|Negative", '
                '"pain_points": "<one concise sentence>", "intent": "<one of the five intents>"}'
            ),
            expected_output="A JSON array of per-theme objects with theme, sentiment, pain_points, and intent.",
            agent=theme_agent,
        )

        crew = Crew(agents=[theme_agent], tasks=[task], process=Process.sequential, verbose=False)
        return crew.kickoff()

    result, error = _run_crew_with_resilience(_build_and_run, timeout_per_attempt=timeout)
    if result is None:
        return None, error or "Unknown error calling the Theme Extraction Agent."

    parsed = _extract_json_array(str(result))
    if not isinstance(parsed, list):
        return None, f"Model response wasn't valid JSON: {str(result)[:200]!r}"

    cleaned = []
    for item in parsed:
        if not isinstance(item, dict) or "theme" not in item:
            continue
        sentiment = item.get("sentiment") if item.get("sentiment") in VALID_SENTIMENTS else "Neutral"
        intent = item.get("intent") if item.get("intent") in VALID_INTENTS else "Complaint"
        cleaned.append({
            "theme": str(item["theme"]),
            "sentiment": sentiment,
            "pain_points": str(item.get("pain_points", "")).strip() or "—",
            "intent": intent,
        })

    if not cleaned:
        return None, "Model returned no usable theme objects."
    return cleaned, None
