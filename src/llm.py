import os
import time
import concurrent.futures
import streamlit as st

GEMINI_MODEL_CANDIDATES = ["gemini-3.5-flash", "gemini-3.1-flash-lite"]

_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4)

_LAST_INIT_ERROR = {"stage": None, "detail": None}

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


def _get_api_key():
    if hasattr(st, "secrets"):
        try:
            key = st.secrets.get("GEMINI_API_KEY", None)
            if key:
                return key
        except Exception:
            pass
    return os.environ.get("GEMINI_API_KEY")


def _get_client():
    global _LAST_INIT_ERROR
    api_key = _get_api_key()
    if not api_key:
        _LAST_INIT_ERROR = {
            "stage": "key",
            "detail": "No GEMINI_API_KEY found in st.secrets or environment variables.",
        }
        return None
    try:
        from google import genai
    except Exception as e:
        _LAST_INIT_ERROR = {"stage": "import", "detail": f"google-genai package not installed: {e}"}
        return None
    try:
        client = genai.Client(api_key=api_key)
        _LAST_INIT_ERROR = {"stage": None, "detail": None}
        return client
    except Exception as e:
        _LAST_INIT_ERROR = {"stage": "init", "detail": str(e)}
        return None


def _run_with_timeout(fn, timeout: int):
    """
    Runs fn() in a worker thread and enforces a real wall-clock timeout.
    Raises concurrent.futures.TimeoutError if it doesn't finish in time,
    regardless of whether the underlying SDK/network ever gives up.
    """
    future = _EXECUTOR.submit(fn)
    return future.result(timeout=timeout)


def _request_with_resilience(make_request_fn, timeout_per_attempt: int = 20, retries_per_model: int = 2):
    last_error = None
    for model_name in GEMINI_MODEL_CANDIDATES:
        for attempt in range(retries_per_model):
            try:
                resp = _run_with_timeout(lambda: make_request_fn(model_name), timeout=timeout_per_attempt)
                return resp, None
            except concurrent.futures.TimeoutError:
                last_error = f"Request to {model_name} timed out after {timeout_per_attempt}s"
                break  # don't retry a timeout on the same model; try the next model
            except Exception as e:
                detail = str(e)
                last_error = detail
                kind = _classify_error(detail)
                if kind == "auth":
                    return None, detail  # fail fast, no point retrying or switching models
                if kind == "model_unavailable":
                    break  # skip straight to the next model
                if kind == "transient" and attempt < retries_per_model - 1:
                    time.sleep(1.5 * (attempt + 1))  # brief backoff, then retry same model
                    continue
                break  # give up on this model, try the next one
    return None, last_error


def _call(system: str, user: str, max_tokens: int = 1200, timeout: int = 20) -> str:
    client = _get_client()
    if client is None:
        return None
    from google.genai import types

    def _do(model_name):
        return client.models.generate_content(
            model=model_name,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
            ),
        )

    resp, error = _request_with_resilience(_do, timeout_per_attempt=timeout)
    if resp is not None:
        return (resp.text or "").strip()
    return f"__ERROR__: {error}"


def generate_prd(feature_title: str, description: str, theme: str, feedback_samples: list) -> str:
    # 1) Try the CrewAI multi-agent crew first — matches the project's
    #    finalized architecture (CrewAI orchestration + Gemini).
    try:
        from src.agents import run_prd_crew
        crew_result = run_prd_crew(feature_title, description, theme, feedback_samples)
        if crew_result:
            return crew_result
    except Exception:
        pass

    # 2) Fall back to a direct Gemini call (with retry + model fallback)
    system = (
        "You are a senior product manager. Write a concise, structured Product "
        "Requirements Document in Markdown with sections: Overview, Problem "
        "Statement, Goals & Non-Goals, User Stories, Acceptance Criteria, "
        "Success Metrics, and Risks."
    )
    samples = "\n".join(f"- {s}" for s in feedback_samples[:6])
    user = (
        f"Feature: {feature_title}\nDescription: {description}\nTheme: {theme}\n"
        f"Representative customer feedback:\n{samples}"
    )
    result = _call(system, user)
    if result and not result.startswith("__ERROR__"):
        return result

    # 3) Offline fallback template
    return f"""# PRD: {feature_title}

## Overview
{description or 'No description provided.'}

## Problem Statement
Customers in the **{theme}** theme have repeatedly raised related issues, including:
{samples if samples else '- (no representative feedback captured yet)'}

## Goals
- Address the core pain point behind "{feature_title}".
- Improve satisfaction for the affected user segment.

## Non-Goals
- Full redesign of unrelated workflows.

## User Stories
1. As a user, I want {feature_title.lower()} so that my workflow is less frustrating.
2. As a user, I want clear feedback when this feature is used, so I trust the system.

## Acceptance Criteria
- [ ] Feature is available to all target users.
- [ ] No regression in related workflows.
- [ ] Positive shift in related satisfaction / support ticket volume within one release cycle.

## Success Metrics
- Reduction in support tickets tagged "{theme}".
- Adoption rate of the new capability.

## Risks
- Scope creep beyond the immediate pain point.
- Engineering effort underestimated.

*(Generated offline — connect a GEMINI_API_KEY to enable full generative PRD writing.)*
"""


def generate_quick_prd_from_feedback(raw_text: str) -> list:
    # 1) Try the CrewAI 4-agent crew first (matches the project's finalized
    #    architecture: CrewAI orchestration + Gemini).
    try:
        from src.agents import run_quick_prd_from_text_crew
        crew_result = run_quick_prd_from_text_crew(raw_text)
        if crew_result:
            return crew_result
    except Exception:
        pass

    # 2) Fall back to a single direct Gemini call producing just the PRD
    #    (skips the intermediate stages, but still grounded in the raw text).
    system = (
        "You are a product team compressed into one assistant. Given raw customer feedback or "
        "support tickets, do four things internally (extract pain points, propose 2-3 features, "
        "pick the highest-priority one, then write it up) but respond with ONLY the final mini-PRD "
        "in Markdown, with sections: Overview, Problem Statement, Goals & Non-Goals, User Stories, "
        "Acceptance Criteria, Success Metrics, and Risks."
    )
    result = _call(system, raw_text, max_tokens=1200)
    if result and not result.startswith("__ERROR__"):
        return [{"stage": "PRD", "output": result}]

    # 3) Offline fallback template
    first_line = next((l.strip() for l in raw_text.splitlines() if l.strip()), "Untitled Feature")
    offline_prd = f"""# Mini-PRD (offline mode)

## Overview
Drafted from raw feedback: "{first_line[:120]}"

## Problem Statement
{raw_text[:400] or 'No feedback text provided.'}

## Goals
- Address the core pain point described above.

## Non-Goals
- Full redesign of unrelated workflows.

## User Stories
1. As a user, I want this pain point resolved so my workflow is less frustrating.

## Acceptance Criteria
- [ ] Feature is available to all target users.
- [ ] No regression in related workflows.

## Success Metrics
- Reduction in related support tickets / complaints.

## Risks
- Scope creep beyond the immediate pain point.

*(Generated offline — connect a GEMINI_API_KEY to enable full generative multi-agent output.)*
"""
    return [{"stage": "PRD", "output": offline_prd}]


def generate_user_stories(feature_title: str, description: str) -> str:
    system = "You write crisp Agile user stories with acceptance criteria in Markdown, 3-5 stories."
    user = f"Feature: {feature_title}\nDescription: {description}"
    result = _call(system, user, max_tokens=700)
    if result and not result.startswith("__ERROR__"):
        return result
    return f"""### User Stories: {feature_title}

1. **As a** user, **I want** {feature_title.lower()}, **so that** I can accomplish my task faster.
   - *Acceptance criteria:* Feature is discoverable, functions without errors, documented.
2. **As a** support agent, **I want** visibility into this feature's status, **so that** I can help customers.
   - *Acceptance criteria:* Status is logged and queryable.
3. **As a** product manager, **I want** usage metrics on this feature, **so that** I can validate impact.
   - *Acceptance criteria:* Event tracking implemented and visible on the dashboard.

*(Generated offline — connect a GEMINI_API_KEY for tailored stories.)*
"""


def suggest_impact_score(feature_title: str, description: str, votes: int) -> int:
    """Returns a 1-5 impact suggestion."""
    # 1) Try the CrewAI single-agent "Business Impact Analyst" crew first
    try:
        from src.agents import run_impact_scoring_crew
        crew_score = run_impact_scoring_crew(feature_title, description, votes)
        if crew_score is not None:
            return crew_score
    except Exception:
        pass

    # 2) Fall back to a direct Gemini call (with retry + model fallback)
    system = "You are a product analyst. Respond with ONLY a single integer from 1 to 5 rating business impact."
    user = f"Feature: {feature_title}\nDescription: {description}\nCustomer votes: {votes}\nRate impact 1(low)-5(massive)."
    result = _call(system, user, max_tokens=10, timeout=15)
    if result and not result.startswith("__ERROR__"):
        digits = "".join(ch for ch in result if ch.isdigit())
        if digits:
            return max(1, min(5, int(digits[0])))
    # 3) Offline heuristic fallback
    if votes >= 20:
        return 5
    if votes >= 10:
        return 4
    if votes >= 5:
        return 3
    if votes >= 2:
        return 2
    return 1


def generate_executive_summary(context: str) -> str:
    system = "You are a CPO writing a crisp executive summary in Markdown (under 300 words) from the given product data."
    # 300 words needs roughly 450-500 tokens on its own; 600 left almost no
    # headroom for Markdown formatting (headers, bold, bullet points) and
    # was regularly cutting the response off mid-sentence, e.g. ending on
    # "...outpacing **Negative (147" with no closing parenthesis.
    result = _call(system, context, max_tokens=1500)
    if result and not result.startswith("__ERROR__"):
        return result
    return (
        "### Executive Summary (offline mode)\n\n"
        f"{context[:800]}\n\n"
        "*(Connect a GEMINI_API_KEY to generate a narrative executive summary.)*"
    )


def chat_response(history: list, context: str) -> str:
    """
    history: list of {"role": "user"/"assistant", "content": str}
    context: retrieved snippets (feedback, features, roadmap) to ground the answer
    """
    # 1) Try the CrewAI "AI Product Manager Copilot" agent crew first
    try:
        from src.agents import run_chat_crew
        crew_reply = run_chat_crew(history, context)
        if crew_reply:
            return crew_reply
    except Exception:
        pass

    # 2) Fall back to a direct Gemini call (with retry + model fallback)
    system = (
        "You are the AI Product Manager Copilot, a conversational assistant for a product team. "
        "Answer using the provided workspace context (feedback, feature requests, roadmap data) "
        "when relevant. Be concise and actionable. If the context doesn't cover the question, say so."
        f"\n\nWORKSPACE CONTEXT:\n{context}"
    )

    client = _get_client()
    if client is None:
        return (
            "*(Offline mode — no GEMINI_API_KEY configured.)*\n\n"
            f"Here's what I found in the workspace related to your question:\n\n{context[:1200] or 'No matching data found.'}"
        )

    from google.genai import types

    # Gemini expects role "model" instead of "assistant".
    contents = [
        {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
        for m in history
    ]

    def _do(model_name):
        return client.models.generate_content(
            model=model_name,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=800,
            ),
        )

    resp, error = _request_with_resilience(_do, timeout_per_attempt=20)
    if resp is not None:
        return (resp.text or "").strip()
    return f"Error calling Gemini: {error}"


def check_connection() -> dict:
    client = _get_client()
    if client is None:
        if _LAST_INIT_ERROR["stage"] == "key":
            return {"status": "no_key", "detail": _LAST_INIT_ERROR["detail"]}
        return {
            "status": "error",
            "detail": _LAST_INIT_ERROR["detail"] or "Could not initialize the Gemini client for an unknown reason.",
        }

    from google.genai import types

    def _do(model_name):
        return client.models.generate_content(
            model=model_name,
            contents="Reply with exactly: OK",
            config=types.GenerateContentConfig(max_output_tokens=10),
        )

    resp, error = _request_with_resilience(_do, timeout_per_attempt=15, retries_per_model=1)
    if resp is not None:
        text = (resp.text or "").strip()
        return {"status": "connected", "detail": f"Gemini responded: {text[:60]!r}"}
    return {"status": "error", "detail": error}

def generate_implementation_roadmap(prd_text: str) -> str:
    """
    Takes an existing PRD and generates a standalone 2-Sprint Implementation Roadmap.
    """
    system = (
        "You are an expert Engineering Manager. Your job is to read the provided Product "
        "Requirements Document (PRD) and translate it into a strict, actionable 2-Sprint Execution Plan. "
        "Sprint 1 must focus entirely on backend/core logic, and Sprint 2 must focus on frontend UI/integration. "
        "Output ONLY the roadmap in clean Markdown format."
    )
    user = f"Here is the approved PRD:\n\n{prd_text}"
    
    # We use a larger max_tokens (like you identified earlier) to ensure it doesn't get cut off
    result = _call(system, user, max_tokens=8192)
    
    if result and not result.startswith("__ERROR__"):
        return result
        
    return f"""### 2-Sprint Execution Plan (Offline Fallback)

**Sprint 1: Core/Backend**
*   Analyze PRD requirements for necessary data structures.
*   Implement foundational APIs and database migrations.

**Sprint 2: UI/Frontend**
*   Build user interfaces based on the PRD user stories.
*   Integrate frontend with Sprint 1 APIs.

*(Generated offline — connect a GEMINI_API_KEY to enable full AI roadmap generation based on the actual PRD.)*
"""