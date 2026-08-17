# AI Product Manager Copilot — Combined Build

This build combines:
- **Frontend UI** from `AI_Product_Manager_Copilot.zip` (the polished Streamlit screens: Dashboard,
  AI Chat, Reports, Roadmap, Settings, Login).
- **Complete backend** from `AI-Product-Manager-Copilot-Streamlit.zip` (`src/`: SQLite data layer,
  TF-IDF/KMeans theme & sentiment classification, column-agnostic CSV ingestion, and Gemini/CrewAI-powered
  PRD generation, impact scoring, executive summaries, and the chat assistant).

Every screen that previously used hardcoded/mock data now reads from and writes to the real SQLite
workspace (`data/copilot.db`, created automatically on first run) and calls the real AI backend.

There is **no manual upload screen**. `data/customer_feedback_dataset.csv` is bundled with the app and
loaded straight into the database automatically the first time it runs — via `ensure_dataset_seeded()`
in `utils/helpers.py`, which is called once at startup in `app.py`. That data is immediately run through
the same AI pipeline (theme clustering, sentiment scoring, feature-request auto-promotion) and the
Dashboard reads the processed results directly from the database. Settings → **Data** shows what's
currently stored and has a "Reload dataset" button to wipe and re-run the pipeline on demand.

## What's wired up

| Screen | Backed by |
|---|---|
| **Startup seeding** | `utils/helpers.ensure_dataset_seeded()` → reads `data/customer_feedback_dataset.csv`, ingests into `feedback` via the same pipeline as `ingest_and_classify` (theme clustering + sentiment via `src/nlp_utils.py`), auto-promotes feature-request-like feedback into `feature_requests` |
| **Dashboard** | Live aggregates from `feedback`, `feature_requests`, `documents`, `roadmap_items` — reflects whatever is currently in the database |
| **AI Chat** | `src/llm.chat_response` (CrewAI agent → direct Gemini call → offline fallback), grounded in your real feedback/feature/roadmap data |
| **Reports** | PRD/User Story generation via `src/llm.generate_prd` / `generate_user_stories`; RICE prioritization stored in `prioritization` table; executive summary via `src/llm.generate_executive_summary`; **Quick PRD from raw feedback** via `src/llm.generate_quick_prd_from_feedback` (4-agent Feedback → Feature → Priority → PRD chain, ported from `Team3_AICopilot_backend`) |
| **Roadmap** | Real `roadmap_items` table, quarter-grouped, with AI recommendations based on RICE-ranked unscheduled features |
| **Settings** | Live Gemini connection test (`src/llm.check_connection`), editable workspace name persisted to `workspaces` table, **Data** tab to inspect/reload the seeded dataset |

## Running it

```bash
pip install -r requirements.txt
streamlit run app.py
```

### Enabling real Gemini AI features (optional)

Without a key, PRD generation, impact scoring, executive summaries, and chat all fall back to
deterministic offline templates — the app runs end-to-end with zero setup. To enable full generative
output:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# then edit .streamlit/secrets.toml and set GEMINI_API_KEY
```

`crewai` and `google-genai` are optional extras used only when a key is configured; core functionality
(ingestion, classification, RICE scoring, dashboards) works fully offline via `scikit-learn`.

## Project layout

```
app.py                  # Entry point: login gate + sidebar navigation
screens/                # UI screens (from the frontend project)
src/                     # Backend: db.py, nlp_utils.py, csv_utils.py, llm.py, agents.py, style.py
utils/helpers.py         # Glue layer composing src/ functions for the screens
data/                     # SQLite database + bundled seed dataset (created on first run)
assets/                   # Images/CSS from the original frontend
```

### Quick PRD from raw feedback

`Reports → PRD Documents → ⚡ Quick PRD from raw feedback` lets you paste any unstructured customer
feedback or support ticket text and get a mini-PRD immediately — no need to ingest it into the database
first. This ports the 4-agent CrewAI chain (Feedback Agent → Feature Agent → Priority Agent → PRD Agent)
from the team's standalone `Team3_AICopilot_backend` FastAPI service into this app's existing
Gemini/CrewAI backend (`src/agents.run_quick_prd_from_text_crew`, wrapped by
`src/llm.generate_quick_prd_from_feedback`), following the same three-layer fallback used everywhere
else in the app: CrewAI crew → direct Gemini call → offline template.
