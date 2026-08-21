import json
import re

from src.agents import _get_llm, _run_crew_with_resilience

VALID_RISKS = {"Low", "Medium", "High"}


# ---------------- Deterministic calculators (the design doc's "tools") ----------------

def compute_rice(reach: float, impact: float, confidence: float, effort: float) -> float:
    """RICE = (Reach x Impact x Confidence%) / Effort."""
    return (reach * impact * (confidence / 100)) / max(effort, 0.1)


def compute_ice(impact: float, confidence: float, effort: float) -> float:
    """
    ICE = average of Impact, Confidence, and Ease — each normalized to a
    1-10 scale (Ease is the inverse of effort: lower effort -> easier).
    """
    confidence_10 = confidence / 10
    ease_10 = max(1.0, 11 - (effort * 2))  # effort 1(trivial)->10 ease, 5(huge)->1 ease
    return round((impact * 2 + confidence_10 + ease_10) / 3, 2)


def recommend_priority(rice_score, risk: str) -> str:
    """Combines RICE with the assessed delivery risk into one recommendation."""
    if rice_score is None:
        return "Medium"
    base = "High" if rice_score >= 60 else "Medium" if rice_score >= 25 else "Low"
    if risk == "High" and base == "High":
        return "Medium"  # a high-risk item gets bumped down a notch even if RICE is high
    return base


# ---------------- AI-assisted scoring: impact / effort / confidence / risk ----------------

def _safe_int(val, default, lo, hi):
    try:
        n = int(round(float(val)))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _safe_float(val, default, lo, hi):
    try:
        n = float(val)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


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


def run_prioritization_engine(features: list, timeout: int = 45):
    try:
        from crewai import Agent, Task, Crew, Process
    except Exception as e:
        return None, f"crewai is not installed/importable: {e}"

    if not features:
        return None, "No feature requests to analyze yet."

    features_block = "\n\n".join(
        f"ID: {f['id']}\nTitle: {f['title']}\nTheme: {f.get('theme') or 'Unclassified'}\n"
        f"Customer votes: {f.get('votes', 0)}\nDescription: {f.get('description') or '(none)'}\n"
        "Representative feedback:\n" + "\n".join(f"- {s}" for s in (f.get("sample_feedback") or [])[:3])
        for f in features
    )

    def _build_and_run(model_id):
        llm = _get_llm(model_id, temperature=0.3)

        analyst = Agent(
            role="Impact & Risk Analyst",
            goal="Rank product opportunities by estimating business impact, delivery effort, "
                 "confidence, and delivery risk for each requested feature.",
            backstory=(
                "You are a pragmatic product analyst on the Prioritization team. You read customer "
                "demand signals and feature descriptions and turn them into decisive, comparable "
                "scores a PM can plug straight into a RICE/ICE model — you never hedge with ranges."
            ),
            llm=llm,
            verbose=False,
        )

        task = Task(
            description=(
                "For EACH feature below, estimate: (1) impact — business impact of shipping it, "
                "1 (minimal) to 5 (massive); (2) effort — engineering effort in person-months, 1 "
                "(trivial) to 5 (very large); (3) confidence — how confident you are in this "
                "assessment given the evidence, 0-100; (4) risk — delivery/adoption risk, exactly "
                "one of Low, Medium, High; (5) rationale — one concise sentence justifying the "
                "scores.\n\n"
                f"{features_block}\n\n"
                "Respond with ONLY a JSON array (no prose, no markdown fences), one object per "
                "feature, each shaped exactly as: "
                '{"id": <feature id as given, integer>, "impact": <1-5>, "effort": <1-5>, '
                '"confidence": <0-100>, "risk": "Low|Medium|High", "rationale": "<one sentence>"}'
            ),
            expected_output="A JSON array of per-feature impact/effort/confidence/risk objects.",
            agent=analyst,
        )

        crew = Crew(agents=[analyst], tasks=[task], process=Process.sequential, verbose=False)
        return crew.kickoff()

    result, error = _run_crew_with_resilience(_build_and_run, timeout_per_attempt=timeout)
    if result is None:
        return None, error or "Unknown error calling the Prioritization Engine."

    parsed = _extract_json_array(str(result))
    if not isinstance(parsed, list):
        return None, f"Model response wasn't valid JSON: {str(result)[:200]!r}"

    cleaned = []
    for item in parsed:
        if not isinstance(item, dict) or "id" not in item:
            continue
        try:
            fid = int(item["id"])
        except (TypeError, ValueError):
            continue
        risk = item.get("risk") if item.get("risk") in VALID_RISKS else "Medium"
        cleaned.append({
            "id": fid,
            "impact": _safe_int(item.get("impact"), 3, 1, 5),
            "effort": _safe_int(item.get("effort"), 2, 1, 5),
            "confidence": _safe_float(item.get("confidence"), 70.0, 0, 100),
            "risk": risk,
            "rationale": str(item.get("rationale", "")).strip() or "—",
        })

    if not cleaned:
        return None, "Model returned no usable feature scores."
    return cleaned, None