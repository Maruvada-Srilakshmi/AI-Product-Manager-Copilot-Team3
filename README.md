# AI Product Manager Copilot

An AI-native workspace that takes a product team from raw customer feedback all the way
to a prioritized, sequenced roadmap with generated PRDs and user stories — built as a
Streamlit application backed by Google Gemini and a CrewAI multi-agent pipeline.

Every AI-powered feature in the app follows a three-layer resilience pattern: try the
CrewAI multi-agent crew first, fall back to a direct Gemini call if the crew fails, and
fall back again to an offline template if no `GEMINI_API_KEY` is configured at all. This
means the app is fully demoable and testable with zero API keys, while still producing
real generative output whenever a key is present.

---

## Table of Contents

- [Modules](#modules)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Data Model](#data-model)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Architecture Notes](#architecture-notes)

---

## Modules

The app is organized around 10 planned modules. All 10 are implemented.

### 1. User Authentication and Workspace Management
Username/password login and registration (`screens/login.py`, `screens/register.py`)
with hashed credentials, a default workspace created per user, and session persistence
via `st.query_params` so a browser refresh doesn't log the user out. Workspace-level
settings — renaming the workspace, light/dark appearance, a live Gemini connection test,
and dataset status/reload controls — live in a dedicated **Settings** screen
(`screens/settings.py`).

### 2. Customer Feedback and Support Ticket Ingestion
Feedback is ingested from a bundled CSV dataset (`data/customer_feedback_dataset.csv`)
on first run via `ensure_dataset_seeded()`, or reloaded on demand from Settings. Each
row is cleaned, sentiment-scored, and classified into a theme as part of ingestion.

### 3. Product Analytics Data Integration
A separate bundled analytics dataset (`data/product_analytics_dataset.csv`) is ingested
into an `analytics_events` table and surfaced on the **Product Analytics** screen —
feature usage over time, event mix, and a usage-vs-demand comparison against feature
requests (`src/analytics_utils.py`).

### 4. Feedback Classification and Theme Extraction Engine
Feedback text is clustered into themes with a TF-IDF + KMeans pipeline
(`src/nlp_utils.py`), enriched into plain-language theme names and summaries by a
CrewAI/Gemini agent (`src/theme_agent.py`), and displayed on the **Theme Insights**
screen (`screens/theme_extraction_panel.py`). A companion **accuracy validation** view
(`screens/theme_validation.py`) lets a PM review and correct theme groupings, tracked in
the `theme_validations` table.

### 5. Feature Request Aggregation
Feedback that reads as a feature request is aggregated into the `feature_requests`
table, with matching/near-duplicate requests merged and their vote counts combined
rather than creating duplicate entries.

### 6. AI-Based Prioritization and Impact Analysis Engine
RICE and ICE scoring (`src/prioritization_engine.py`) plus an AI impact-scoring crew
(`run_impact_scoring_crew` in `src/agents.py`) that estimates reach, impact, confidence,
and effort for each feature request, surfaced on the **Prioritization Engine** screen
with High/Medium/Low priority buckets.

### 7. PRD and User Story Generation
A four-agent CrewAI pipeline (Feedback Agent → Feature Agent → Priority Agent → PRD
Agent) drafts a full PRD for a feature request, and a second, focused generator produces
a standalone **User Stories** document (3–5 Agile stories with acceptance criteria) for
the same feature. Both live on the **Reports** screen (`screens/reports.py`) as
independently generated, viewable, downloadable documents, alongside an AI-generated
executive summary.

### 8. Roadmap Planning and Visualization
An AI roadmap agent (`src/roadmap_agent.py`) plans dependencies, allocates features to
sprints, and topologically sequences releases; results are shown on the **Roadmap**
screen (`screens/roadmap.py`). Generating a PRD automatically schedules that feature
onto the roadmap.

### 9. Conversational Product Intelligence Assistant
A chat interface (`screens/ai_chat.py`) backed by `run_chat_crew` in `src/agents.py`,
with conversation history persisted per workspace in the `chat_history` table.

### 10. Reporting and Insights Dashboard
The **Dashboard** screen (`screens/dashboard.py`) surfaces top-line metrics, feedback
sentiment, top themes, and top requested features; **Reports** adds an AI-generated
executive summary and a Feedback Insights tab (top issues, top requested features,
sentiment breakdown).

---

## Tech Stack

| Layer | Technology |
|---|---|
| UI | Streamlit |
| Language | Python |
| Database | SQLite |
| AI orchestration | CrewAI (multi-agent crews) |
| LLM | Google Gemini (`google-genai`) |
| Data / ML | pandas, numpy, scikit-learn (TF-IDF + KMeans for theme clustering) |
| Charts | Plotly |
| Styling | Custom CSS via `src/style.py` and `assets/styles.css`, CSS variables for light/dark theming |

See `requirements.txt` for exact version constraints.

---

## Project Structure

```
.
├── app.py                       # Entry point: auth gate, nav, page routing
├── requirements.txt
├── data/
│   ├── customer_feedback_dataset.csv
│   └── product_analytics_dataset.csv
├── src/
│   ├── db.py                    # SQLite schema + query helpers
│   ├── llm.py                   # Gemini calls + offline-template fallbacks
│   ├── agents.py                # CrewAI crews (impact scoring, PRD, chat)
│   ├── theme_agent.py           # Theme enrichment agent
│   ├── prioritization_engine.py # RICE/ICE scoring
│   ├── roadmap_agent.py         # Dependency planning + sprint sequencing
│   ├── nlp_utils.py             # Sentiment scoring, TF-IDF/KMeans theming
│   ├── analytics_utils.py       # Product analytics aggregations
│   └── style.py                 # Theme CSS injection
├── screens/
│   ├── login.py / register.py
│   ├── dashboard.py
│   ├── theme_extraction_panel.py / theme_validation.py
│   ├── prioritization_engine.py
│   ├── product_analytics.py
│   ├── ai_chat.py
│   ├── reports.py                # PRD + User Stories + Executive Summary
│   ├── roadmap.py
│   ├── settings.py                # Workspace, appearance, AI connection, data
│   └── user_profile.py
└── utils/
    └── helpers.py                # Cross-screen helpers (seeding, roadmap scheduling, etc.)
```

---

## Data Model

SQLite tables (all scoped by `workspace_id`):

| Table | Purpose |
|---|---|
| `workspaces` | One row per workspace (name, created_at) |
| `users` | Login credentials, linked to a default workspace |
| `feedback` | Ingested customer feedback: text, sentiment, theme |
| `analytics_events` | Product usage events for the Product Analytics module |
| `feature_requests` | Aggregated feature requests with vote counts |
| `prioritization` | RICE/ICE scores and priority tier per feature |
| `documents` | Generated PRDs, User Stories, Executive Summaries, and Roadmap docs |
| `roadmap_items` | Sprint-sequenced roadmap entries |
| `chat_history` | Conversational assistant history |
| `theme_validations` | PM corrections/approvals of AI theme groupings |

---

## Getting Started

```bash
# 1. Create and activate a virtual environment
python -m venv crew_env
source crew_env/bin/activate      # Windows: crew_env\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. (Optional) Configure a Gemini API key for real generative output
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# then edit .streamlit/secrets.toml and set GEMINI_API_KEY

# 4. Run the app
streamlit run app.py
```

Without a `GEMINI_API_KEY`, the app still runs end-to-end: theme extraction falls back
to TF-IDF/KMeans-only naming, and PRD/user-story/roadmap/chat/executive-summary
generation fall back to their offline templates.

On first run, the app seeds the default workspace with the bundled feedback and
analytics datasets. Both can be re-ingested at any time from **Settings → Data**.

---

## Configuration

Environment variable / secret:

- `GEMINI_API_KEY` — enables live Gemini calls and the CrewAI crews. Test connectivity
  any time from **Settings → AI Connection**.

Streamlit theme (`.streamlit/config.toml`) sets the base light palette; in-app light/dark
mode is a separate toggle (top-right, or **Settings → Appearance**) driven by CSS
variables in `src/style.py`.

---

## Architecture Notes

- **`_ensure_column()`** in `src/db.py` — safe, idempotent SQLite migrations (adds a
  column only if it doesn't already exist), so schema changes don't require a destructive
  reset of `data/copilot.db`.
- **`(result, error)` return tuples** — agent-calling functions return a tuple rather
  than raising, so screens can show a graceful inline error instead of crashing on an
  API hiccup.
- **Three-layer resilience** — CrewAI crew → direct Gemini call → offline template,
  applied consistently to every generative feature (themes, prioritization, PRDs, user
  stories, roadmap, chat, executive summaries).
- **Truncated titles, full text on demand** — `feature_requests.title` is truncated for
  compact display (chart legends, cards); screens that need the full text look it up via
  the untruncated `description` field rather than storing two copies of the truth.
- High-level and low-level architecture diagrams are included as image files
  (`High Level Architecture`, `Low Level Architecture`) alongside a written breakdown in
  `DATA_AND_ARCHITECTURE.md`.
