"""
CrewAI-based agent orchestration — this is what makes the AI Product Manager
Copilot match its finalized architecture (CrewAI as the orchestration
framework, Gemini as the sole LLM), rather than being plain single-shot API
calls.

Covers the three genuinely agent-shaped modules:
 - Module 6: AI-Based Prioritization & Impact Analysis (single-agent crew)
 - Module 7: PRD Generation (two-agent crew: Insights Analyst -> PRD Writer)
 - Module 9: Conversational Product Intelligence Assistant (single-agent crew)

Every function here returns None on ANY failure (no key, crewai not
installed, API error, timeout) so callers in llm.py can fall back to a
direct single-shot Gemini call, and finally to an offline template — the
same layered-fallback design already used throughout the app.

Resilience, matching llm.py:
 - Every crew.kickoff() runs through a hard wall-clock timeout via a worker
   thread, since CrewAI has no reliable built-in per-call timeout.
 - Transient errors (503 UNAVAILABLE / high demand, 429, 500) are retried
   with backoff before giving up.
 - If the primary model is unavailable/overloaded after retries, we
   automatically rebuild the crew against a secondary model.
 - Auth errors fail immediately — retrying won't fix a bad key.
"""
import os
import time
import concurrent.futures
import streamlit as st

# Disable CrewAI's anonymous telemetry/tracing (network calls to
# telemetry.crewai.com) before crewai is ever imported. This is a local
# product-management tool, not a shared SaaS deployment, and on networks
# that block that host these calls otherwise produce noisy errors/hangs
# on process exit with no functional benefit. setdefault() so an explicit
# choice already set in the environment is respected.
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")

# LiteLLM naming convention CrewAI expects: "<provider>/<model-id>".
# Tried in order — if the first is overloaded/retired/unavailable, we
# automatically rebuild the crew against the next one.
GEMINI_MODEL_CANDIDATES = ["gemini/gemini-3.5-flash", "gemini/gemini-3.1-flash-lite"]

_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4)

_AUTH_ERROR_MARKERS = ["api_key_invalid", "api key not valid", "permission_denied", "unauthenticated", "401", "403"]
_MODEL_UNAVAILABLE_MARKERS = ["404", "not found", "no longer available"]
_TRANSIENT_MARKERS = ["503", "unavailable", "429", "resource_exhausted", "high demand", "overloaded", "500"]


def _classify_error(detail: str) -> str:
    d = (detail or "").lower()
    if any(m in d for m in _AUTH_ERROR_MARKERS):
        return "auth"
    if any(m in d for m in _MODEL_UNAVAILABLE_MARKERS):
        return "model_unavailable"
    if any(m in d for m in _TRANSIENT_MARKERS):
        return "transient"
    return "other"


def _run_with_timeout(fn, timeout: int):
    future = _EXECUTOR.submit(fn)
    return future.result(timeout=timeout)


def _get_api_key():
    if hasattr(st, "secrets"):
        try:
            key = st.secrets.get("GEMINI_API_KEY", None)
            if key:
                return key
        except Exception:
            pass
    return os.environ.get("GEMINI_API_KEY")


def _get_llm(model_id: str, temperature: float = 0.7):
    """Returns a crewai.LLM configured for the given Gemini model, or None if unavailable."""
    api_key = _get_api_key()
    if not api_key:
        return None
    try:
        from crewai import LLM
        return LLM(model=model_id, api_key=api_key, temperature=temperature)
    except Exception:
        return None


def _run_crew_with_resilience(build_and_run_fn, timeout_per_attempt: int, retries_per_model: int = 2):
    """
    build_and_run_fn(model_id) -> should build a fresh LLM/Agent(s)/Task(s)/Crew
    for the given model id, call crew.kickoff(), and return the result
    (raising an exception on failure).

    Tries each candidate model in order, retrying transient errors with
    backoff, skipping straight to the next model on a model_unavailable
    error, and failing immediately on an auth error.

    Returns (result_or_None, last_error_detail_or_None).
    """
    if not _get_api_key():
        return None, "No GEMINI_API_KEY configured."

    last_error = None
    for model_id in GEMINI_MODEL_CANDIDATES:
        for attempt in range(retries_per_model):
            try:
                result = _run_with_timeout(lambda: build_and_run_fn(model_id), timeout=timeout_per_attempt)
                return result, None
            except concurrent.futures.TimeoutError:
                last_error = f"Request to {model_id} timed out after {timeout_per_attempt}s"
                break  # try the next model rather than retrying a timeout
            except Exception as e:
                detail = str(e)
                last_error = detail
                kind = _classify_error(detail)
                if kind == "auth":
                    return None, detail
                if kind == "model_unavailable":
                    break
                if kind == "transient" and attempt < retries_per_model - 1:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                break
    return None, last_error


def run_prd_crew(feature_title: str, description: str, theme: str, feedback_samples: list, timeout: int = 40):
    """
    Two-agent crew:
      1. Customer Insights Analyst — distills raw feedback into pain points
      2. Senior Product Manager — writes the PRD using those insights
    Returns the final PRD markdown, or None on any failure.
    """
    try:
        from crewai import Agent, Task, Crew, Process
    except Exception:
        return None

    samples_text = "\n".join(f"- {s}" for s in feedback_samples[:6]) or \
        "(no representative feedback captured yet)"

    def _build_and_run(model_id):
        llm = _get_llm(model_id, temperature=0.6)

        insights_analyst = Agent(
            role="Customer Insights Analyst",
            goal="Identify the underlying customer pain points and business rationale behind a requested feature",
            backstory=(
                "You are a meticulous product analyst who reads raw customer feedback and distills it "
                "into clear, evidence-backed insights a PM can act on."
            ),
            llm=llm,
            verbose=False,
        )

        prd_writer = Agent(
            role="Senior Product Manager",
            goal="Write clear, structured Product Requirements Documents that engineering teams can build from",
            backstory=(
                "You are a senior PM known for concise, well-structured PRDs that leave no ambiguity "
                "about scope, acceptance criteria, or success metrics."
            ),
            llm=llm,
            verbose=False,
        )

        analyze_task = Task(
            description=(
                f"Analyze the following customer feedback related to the feature '{feature_title}' "
                f"(theme: {theme}). Summarize in 3-5 bullet points the core pain points and why this "
                f"feature matters to customers.\n\nFeedback:\n{samples_text}"
            ),
            expected_output="3-5 bullet points summarizing customer pain points and business rationale.",
            agent=insights_analyst,
        )

        write_task = Task(
            description=(
                f"Using the analyst's insights, write a complete Product Requirements Document in "
                f"Markdown for the feature '{feature_title}'. Team-provided description: "
                f"{description or '(none provided)'}. Include sections: Overview, Problem Statement, "
                "Goals & Non-Goals, User Stories, Acceptance Criteria, Success Metrics, and Risks."
            ),
            expected_output="A complete PRD in Markdown format with all required sections.",
            agent=prd_writer,
            context=[analyze_task],
        )

        crew = Crew(
            agents=[insights_analyst, prd_writer],
            tasks=[analyze_task, write_task],
            process=Process.sequential,
            verbose=False,
        )
        return crew.kickoff()

    result, _error = _run_crew_with_resilience(_build_and_run, timeout_per_attempt=timeout)
    if result is None:
        return None
    text = str(result).strip()
    return text if text else None


def run_impact_scoring_crew(feature_title: str, description: str, votes: int, timeout: int = 20):
    """
    Single-agent crew: Business Impact Analyst rates 1-5 business impact.
    Returns an int 1-5, or None on any failure.
    """
    try:
        from crewai import Agent, Task, Crew, Process
    except Exception:
        return None

    def _build_and_run(model_id):
        llm = _get_llm(model_id, temperature=0.3)

        analyst = Agent(
            role="Business Impact Analyst",
            goal="Rate the likely business impact of shipping a requested feature on a 1-5 scale",
            backstory=(
                "You are a pragmatic product analyst who rates feature impact based on customer demand "
                "signals and stated value, always returning a single decisive number."
            ),
            llm=llm,
            verbose=False,
        )

        task = Task(
            description=(
                f"Feature: {feature_title}\nDescription: {description or '(none provided)'}\n"
                f"Customer votes requesting this: {votes}\n\n"
                "Rate the business impact of shipping this feature on a scale of 1 (minimal) to 5 "
                "(massive). Respond with ONLY the single integer, nothing else."
            ),
            expected_output="A single integer from 1 to 5.",
            agent=analyst,
        )

        crew = Crew(agents=[analyst], tasks=[task], process=Process.sequential, verbose=False)
        return crew.kickoff()

    result, _error = _run_crew_with_resilience(_build_and_run, timeout_per_attempt=timeout)
    if result is None:
        return None
    text = str(result).strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits:
        return max(1, min(5, int(digits[0])))
    return None


def run_quick_prd_from_text_crew(raw_text: str, timeout: int = 60):
    """
    Four-agent crew, ported from the team's standalone FastAPI/CrewAI backend
    (`Team3_AICopilot_backend/app/agents/orchestrator.py`), that takes raw,
    unstructured customer feedback / support tickets pasted directly by a PM
    and turns it into a mini-PRD in one pass — no need to have already
    ingested/classified the feedback into the `feedback` table first:

      1. Feedback Agent  — extracts pain points & sentiment from the raw text
      2. Feature Agent   — groups the pain points into 2-3 feature concepts
      3. Priority Agent  — scores those concepts High/Med/Low impact vs. effort
      4. PRD Agent       — writes a mini-PRD (user stories + acceptance criteria)
         for the top feature, grounded in the prior three agents' outputs

    Returns a list of {"stage": str, "output": str} dicts (one per agent, in
    order, so the UI can show each stage) or None on any failure — the same
    None-on-failure contract as the other run_*_crew() helpers, so callers
    can fall back to a direct single-shot Gemini call and then an offline
    template.
    """
    try:
        from crewai import Agent, Task, Crew, Process
    except Exception:
        return None

    def _build_and_run(model_id):
        llm = _get_llm(model_id, temperature=0.6)

        feedback_agent = Agent(
            role="Feedback Agent",
            goal="Extract key pain points and sentiment from raw user input.",
            backstory="You are an expert User Researcher.",
            llm=llm,
            verbose=False,
        )
        feature_agent = Agent(
            role="Feature Agent",
            goal="Group feedback into 2-3 actionable feature concepts.",
            backstory="You are a Product Strategist.",
            llm=llm,
            verbose=False,
        )
        priority_agent = Agent(
            role="Priority Agent",
            goal="Score features using High/Med/Low Impact vs Effort.",
            backstory="You are a Data-Driven Product Manager.",
            llm=llm,
            verbose=False,
        )
        prd_agent = Agent(
            role="PRD Agent",
            goal="Write a mini-PRD with user stories and acceptance criteria.",
            backstory="You are a Technical Product Manager.",
            llm=llm,
            verbose=False,
        )

        t1 = Task(
            description=f"Analyze this input: '{raw_text}'",
            expected_output="Categorized feedback summary with key pain points and overall sentiment.",
            agent=feedback_agent,
        )
        t2 = Task(
            description="Convert the feedback analysis into 2-3 concrete feature proposals.",
            expected_output="A short list of proposed features, each with a one-line rationale.",
            agent=feature_agent,
            context=[t1],
        )
        t3 = Task(
            description="Score each proposed feature as High/Medium/Low impact vs. High/Medium/Low effort.",
            expected_output="A prioritization matrix ranking the proposed features.",
            agent=priority_agent,
            context=[t2],
        )
        t4 = Task(
            description=(
                "Using the feedback analysis, feature proposals, and prioritization above, write a "
                "complete mini-PRD in Markdown for the top-priority feature. Include sections: Overview, "
                "Problem Statement, Goals & Non-Goals, User Stories, Acceptance Criteria, Success Metrics, "
                "and Risks."
            ),
            expected_output="A complete mini-PRD in Markdown with all required sections.",
            agent=prd_agent,
            context=[t1, t2, t3],
        )

        crew = Crew(
            agents=[feedback_agent, feature_agent, priority_agent, prd_agent],
            tasks=[t1, t2, t3, t4],
            process=Process.sequential,
            max_rpm=6,  # keeps requests within the Gemini free-tier limit
            verbose=False,
        )
        result = crew.kickoff()

        stage_names = ["Feedback Analysis", "Feature Proposals", "Prioritization", "PRD"]
        outputs = list(getattr(result, "tasks_output", []) or [])
        return [
            {"stage": name, "output": str(getattr(out, "raw", out))}
            for name, out in zip(stage_names, outputs)
        ]

    result, _error = _run_crew_with_resilience(_build_and_run, timeout_per_attempt=timeout)
    if not result:
        return None
    return result


def run_chat_crew(history: list, context: str, timeout: int = 25):
    """
    Single-agent crew: AI Product Manager Copilot answers grounded in
    workspace context. Returns the reply text, or None on any failure.
    """
    try:
        from crewai import Agent, Task, Crew, Process
    except Exception:
        return None

    transcript = "\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}" for m in history
    )
    last_question = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")

    def _build_and_run(model_id):
        llm = _get_llm(model_id, temperature=0.5)

        assistant = Agent(
            role="AI Product Manager Copilot",
            goal="Answer product team questions using workspace feedback, feature, and roadmap data",
            backstory=(
                "You are an assistant embedded in a product management tool, grounded in the team's "
                "own feedback, feature requests, and roadmap. You are concise, actionable, and honest "
                "when the data doesn't cover a question."
            ),
            llm=llm,
            verbose=False,
        )

        task = Task(
            description=(
                f"Conversation so far:\n{transcript}\n\n"
                f"Workspace context (feedback, feature requests, roadmap):\n{context}\n\n"
                f"Answer the user's latest question: {last_question}"
            ),
            expected_output="A concise, actionable answer grounded in the workspace context.",
            agent=assistant,
        )

        crew = Crew(agents=[assistant], tasks=[task], process=Process.sequential, verbose=False)
        return crew.kickoff()

    result, _error = _run_crew_with_resilience(_build_and_run, timeout_per_attempt=timeout)
    if result is None:
        return None
    text = str(result).strip()
    return text if text else None