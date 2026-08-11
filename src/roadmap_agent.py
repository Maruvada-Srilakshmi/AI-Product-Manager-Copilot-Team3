"""
Roadmap Planning Agent
(design doc: AI PM Copilot Multi-Agent System Design -> "9. Roadmap Agent")

Responsibilities implemented here, matching the design doc's Roadmap Agent
section:
 - Dependency planning  -> AI-suggested depends_on_id per feature
 - Sprint allocation    -> AI-suggested sprint number within the quarter
 - Quarterly roadmap    -> AI-suggested target quarter
 - Milestone planning   -> AI-flagged milestone initiatives
 - Release sequencing   -> topological_sequence() (deterministic tool)

Like src/theme_agent.py and src/prioritization_engine.py, this is a
standalone module built as a single CrewAI agent on top of the same Gemini
LLM and resilience plumbing already used across the app (src/agents.py):
auth errors fail fast, transient errors retry with backoff, model
candidates are tried in order. Planning runs as ONE batched crew call
across every unscheduled feature being planned, not one call per feature.

run_roadmap_planning_agent() returns (result, error): result is None on
any failure, so callers (utils.helpers.run_ai_roadmap_planning) fall back
to a deterministic heuristic, the same layered-fallback design used
throughout the app.
"""
import json
import re

from src.agents import _get_llm, _run_crew_with_resilience

VALID_QUARTERS = ["Q1", "Q2", "Q3", "Q4"]


# ---------------- Deterministic tool: release sequencing ----------------

def topological_sequence(items: list) -> list:
    """
    Orders items (each a dict with "id" and "depends_on_id") so that every
    item appears after whatever it depends on, i.e. dependency-respecting
    release sequencing (Kahn's algorithm). Any cyclic or unresolved
    dependency is appended in its original position rather than raising,
    since a stale dependency link should never break the roadmap view.
    """
    by_id = {it["id"]: it for it in items}
    indegree = {it["id"]: 0 for it in items}
    graph = {it["id"]: [] for it in items}  # dependency id -> [dependent ids]

    for it in items:
        dep = it.get("depends_on_id")
        if dep in by_id and dep != it["id"]:
            indegree[it["id"]] += 1
            graph[dep].append(it["id"])

    queue = sorted(iid for iid, deg in indegree.items() if deg == 0)
    ordered_ids = []

    while queue:
        queue.sort()
        current = queue.pop(0)
        ordered_ids.append(current)
        for dependent in graph.get(current, []):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                queue.append(dependent)

    leftover = [it["id"] for it in items if it["id"] not in ordered_ids]
    ordered_ids.extend(leftover)

    return [by_id[iid] for iid in ordered_ids]


# ---------------- AI-assisted planning ----------------

def _safe_int(val, default, lo, hi):
    try:
        n = int(round(float(val)))
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


def run_roadmap_planning_agent(features: list, current_quarter: str = "Q1", timeout: int = 45):
    """
    Runs the Roadmap Planner agent over a batch of prioritized, not-yet-
    scheduled feature requests.

    `features` is a list of dicts, each shaped:
        {"id": int, "title": str, "theme": str, "rice_score": float|None,
         "votes": int}

    Returns (result, error):
        result: list of {"id", "quarter", "sprint", "depends_on_id",
                 "is_milestone", "rationale"} dicts, or None on failure.
                 depends_on_id, if set, is the "id" of another feature in
                 this same batch that should ship first.
        error:  None on success, otherwise a human-readable reason (no key,
                crewai/litellm import error, the actual API error string, a
                timeout message, or a parse failure).
    """
    try:
        from crewai import Agent, Task, Crew, Process
    except Exception as e:
        return None, f"crewai is not installed/importable: {e}"

    if not features:
        return None, "No unscheduled features to plan."

    features_block = "\n".join(
        f"ID: {f['id']} | Title: {f['title']} | Theme: {f.get('theme') or 'Unclassified'} | "
        f"RICE: {f.get('rice_score') if f.get('rice_score') is not None else 'unscored'} | "
        f"Votes: {f.get('votes', 0)}"
        for f in features
    )

    def _build_and_run(model_id):
        llm = _get_llm(model_id, temperature=0.3)

        planner = Agent(
            role="Roadmap Planner",
            goal="Sequence prioritized feature requests into a realistic quarterly roadmap, "
                 "identifying dependencies, sprint slots, and milestone initiatives.",
            backstory=(
                "You are a delivery-focused technical program manager. You take a prioritized "
                "backlog and turn it into an executable plan: which quarter and sprint each item "
                "ships in, which items block others, and which are big enough to call out as a "
                "milestone. You favor shipping foundational/high-RICE work earlier and sequencing "
                "dependent work after whatever it depends on."
            ),
            llm=llm,
            verbose=False,
        )

        task = Task(
            description=(
                f"The current quarter is {current_quarter}. For EACH feature below, decide: "
                "(1) quarter - one of Q1, Q2, Q3, Q4, at or after the current quarter; "
                "(2) sprint - an integer 1-6 representing which sprint within that quarter; "
                "(3) depends_on_id - the ID of another feature IN THIS LIST that should ship "
                "first, if this feature is genuinely blocked by it (use null if none); "
                "(4) is_milestone - true if this is a significant, roadmap-worthy milestone "
                "rather than routine work; (5) rationale - one concise sentence.\n\n"
                f"{features_block}\n\n"
                "Respond with ONLY a JSON array (no prose, no markdown fences), one object per "
                "feature, shaped exactly as: "
                '{"id": <int>, "quarter": "Q1|Q2|Q3|Q4", "sprint": <1-6>, '
                '"depends_on_id": <int or null>, "is_milestone": <true|false>, '
                '"rationale": "<one sentence>"}'
            ),
            expected_output="A JSON array of per-feature roadmap planning objects.",
            agent=planner,
        )

        crew = Crew(agents=[planner], tasks=[task], process=Process.sequential, verbose=False)
        return crew.kickoff()

    result, error = _run_crew_with_resilience(_build_and_run, timeout_per_attempt=timeout)
    if result is None:
        return None, error or "Unknown error calling the Roadmap Planning Agent."

    parsed = _extract_json_array(str(result))
    if not isinstance(parsed, list):
        return None, f"Model response wasn't valid JSON: {str(result)[:200]!r}"

    valid_ids = {f["id"] for f in features}
    cleaned = []
    for item in parsed:
        if not isinstance(item, dict) or "id" not in item:
            continue
        try:
            fid = int(item["id"])
        except (TypeError, ValueError):
            continue
        if fid not in valid_ids:
            continue

        quarter = item.get("quarter") if item.get("quarter") in VALID_QUARTERS else current_quarter

        dep = item.get("depends_on_id")
        try:
            dep_id = int(dep) if dep is not None else None
        except (TypeError, ValueError):
            dep_id = None
        if dep_id == fid or dep_id not in valid_ids:
            dep_id = None  # no self-dependency, no dangling references

        cleaned.append({
            "id": fid,
            "quarter": quarter,
            "sprint": _safe_int(item.get("sprint"), 1, 1, 6),
            "depends_on_id": dep_id,
            "is_milestone": bool(item.get("is_milestone", False)),
            "rationale": str(item.get("rationale", "")).strip() or "No rationale provided.",
        })

    if not cleaned:
        return None, "Model returned no usable planning results."
    return cleaned, None