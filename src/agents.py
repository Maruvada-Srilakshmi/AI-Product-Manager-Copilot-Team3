"""
CrewAI-based agent orchestration — matches finalized architecture 
(CrewAI as orchestration framework, Gemini as the sole LLM).
"""
import os
import time
import concurrent.futures
import streamlit as st

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")

# Standard, highly stable Gemini model identifiers for LiteLLM/CrewAI
GEMINI_MODEL_CANDIDATES = ["gemini/gemini-2.5-flash"]

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
    api_key = _get_api_key()
    if not api_key:
        return None
    try:
        from crewai import LLM
        return LLM(
            model=model_id, 
            api_key=api_key, 
            temperature=temperature, 
            max_tokens=8192,
            max_output_tokens=8192  # This is the magic key for Gemini
        )
    except Exception:
        return None


def _run_crew_with_resilience(build_and_run_fn, timeout_per_attempt: int, retries_per_model: int = 2):
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
                break
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
    print(f"⚠️ AGENT FAILED. HIDDEN ERROR: {last_error}")            
    return None, last_error


def run_prd_crew(feature_title: str, description: str, theme: str, feedback_samples: list, timeout: int = 40):
    try:
        from crewai import Agent, Task, Crew, Process
    except Exception:
        return None

    samples_text = "\n".join(f"- {s}" for s in feedback_samples[:6]) or "(no representative feedback captured yet)"

    def _build_and_run(model_id):
        llm = _get_llm(model_id, temperature=0.6)

        insights_analyst = Agent(
            role="Customer Insights Analyst",
            goal="Identify underlying customer pain points and business rationale behind requested features",
            backstory="You are a meticulous product analyst who distills customer feedback into clear insights.",
            llm=llm,
            verbose=False,
        )

        prd_writer = Agent(
            role="Senior Product Manager",
            goal="Write clear, structured Product Requirements Documents with actionable roadmaps.",
            backstory="You are a senior PM known for well-structured PRDs that leave no ambiguity for engineering.",
            llm=llm,
            verbose=False,
        )

        analyze_task = Task(
            description=(
                f"Analyze customer feedback for feature '{feature_title}' (theme: {theme}). "
                f"Summarize in 3-5 bullet points the core pain points and business rationale.\n\nFeedback:\n{samples_text}"
            ),
            expected_output="3-5 bullet points summarizing customer pain points and business rationale.",
            agent=insights_analyst,
        )

        write_task = Task(
            description=(
                f"Using the analyst's insights, write a Product Requirements Document in Markdown "
                f"for the feature '{feature_title}'.\n\n"
                "CRITICAL INSTRUCTION: You MUST start the document with the Implementation Roadmap before anything else.\n\n"
                "Required Structure:\n"
                "1. **Implementation Roadmap**: A detailed **2-Sprint Breakdown** (Sprint 1: Core Backend, Sprint 2: Frontend & UI) with estimated effort.\n"
                "2. **Overview & Problem Statement**\n"
                "3. **User Stories & Acceptance Criteria**"
            ),
            expected_output="A complete Markdown PRD that explicitly begins with the Implementation Roadmap.",
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
    try:
        from crewai import Agent, Task, Crew, Process
    except Exception:
        return None

    def _build_and_run(model_id):
        llm = _get_llm(model_id, temperature=0.3)

        analyst = Agent(
            role="Business Impact Analyst",
            goal="Rate the likely business impact of shipping a requested feature on a 1-5 scale",
            backstory="You are a pragmatic product analyst who rates feature impact based on customer demand signals.",
            llm=llm,
            verbose=False,
        )

        task = Task(
            description=(
                f"Feature: {feature_title}\nDescription: {description or '(none provided)'}\n"
                f"Customer votes requesting this: {votes}\n\n"
                "Rate business impact on a scale of 1 (minimal) to 5 (massive). Respond with ONLY the single integer."
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
            role="Technical PRD Writer",
            goal="Write complete Product Requirements Documents containing implementation roadmaps.",
            backstory="You are a Technical Product Manager specializing in developer execution roadmaps.",
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
                "Using the previous analysis, write a mini-PRD in Markdown for the top-priority feature.\n\n"
                "CRITICAL INSTRUCTION: You MUST start the document with the Implementation Roadmap before anything else.\n\n"
                "Required Structure:\n"
                "1. **Implementation Roadmap**: A detailed **2-Sprint Execution Plan** (Sprint 1: Core, Sprint 2: UI).\n"
                "2. **Overview & Problem Statement**\n"
                "3. **User Stories & Acceptance Criteria**"
            ),
            expected_output="A mini-PRD that explicitly begins with the Implementation Roadmap.",
            agent=prd_agent,
            context=[t1, t2, t3],
        )

        crew = Crew(
            agents=[feedback_agent, feature_agent, priority_agent, prd_agent],
            tasks=[t1, t2, t3, t4],
            process=Process.sequential,
            max_rpm=6,
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
            backstory="You are an assistant embedded in a product management tool, grounded in workspace data.",
            llm=llm,
            verbose=False,
        )

        task = Task(
            description=(
                f"Conversation so far:\n{transcript}\n\n"
                f"Workspace context:\n{context}\n\n"
                f"Answer the user's latest question: {last_question}"
            ),
            expected_output="A concise, actionable answer grounded in workspace context.",
            agent=assistant,
        )

        crew = Crew(agents=[assistant], tasks=[task], process=Process.sequential, verbose=False)
        return crew.kickoff()

    result, _error = _run_crew_with_resilience(_build_and_run, timeout_per_attempt=timeout)
    if result is None:
        return None
    text = str(result).strip()
    return text if text else None