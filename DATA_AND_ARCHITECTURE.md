# AI Product Manager Copilot — Data & System Architecture

This document explains the dataset, database schema, system architecture, and the
reasoning behind how data flows through the AI Product Manager Copilot application.

---

## 1. Overview

The AI Product Manager Copilot is a Streamlit application that turns raw customer
feedback into product-management artifacts — sentiment/theme analysis, prioritized
feature requests, PRDs, user stories, roadmaps, and an AI chat assistant grounded in
the workspace's own data. It is designed to run **fully offline** (no API key needed)
using classical ML for classification, with an **optional Gemini + CrewAI layer** that
upgrades the generative pieces (PRD writing, executive summaries, chat) when a key is
configured.

The core idea: seed the app with one bundled CSV of customer feedback, automatically
classify it, and let every downstream screen (Dashboard, Reports, Roadmap, AI Chat)
read from the same processed data in a single SQLite database.

---

## 2. The Dataset

**File:** `data/customer_feedback_dataset.csv`
**Size:** 100 rows × 9 columns

| Column | Type | Description |
|---|---|---|
| `feedback_id` | string | Unique ID per row (e.g. `FB-0001`) |
| `source` | string | Channel the feedback came from (CRM, NPS Survey, In-App Survey, Jira, App Store Review, Community Forum, Support Email, Zendesk, Sales Call Notes, Twitter/X) |
| `date` | string (DD-MM-YYYY) | When the feedback was captured |
| `customer_id` | string | Anonymized customer identifier (e.g. `CUST-1017`) |
| `author_role` | string | Role of the person giving feedback (Trial User, IT Manager, Product Owner, Ops Analyst, Finance Lead, Team Lead, Support Contact, Verified Customer, Enterprise Admin, Anonymous User) |
| `product_area` | string | Which part of the product the feedback concerns (Export/Reporting, Dashboard, Login & Auth, Dark Mode/UI, Mobile App, Customer Support, Notifications, Collaboration, Search, Onboarding, Data Security, Integrations, Performance, API, Pricing/Billing) |
| `feedback_text` | string | The raw, free-text feedback/complaint/request — this is the field the AI pipeline actually analyzes |
| `sentiment` | string | Pre-labeled sentiment from the source data (positive/neutral/negative) — **not used by the app**; the app computes its own sentiment (see §5) |
| `rating` | int (1–5) | A satisfaction score accompanying the feedback |

**Why this dataset shape:** it mirrors what a real product team would export from a mix
of support tools, survey tools, and social channels — multiple sources, free text,
and a numeric signal (rating) — which is exactly the mixed, messy input the app's
CSV ingestion is built to handle (see §4).

**Distribution (why it's a good demo dataset):**
- Skewed negative (58 negative / 37 neutral / 5 positive, mean rating 2.37/5) — this
  intentionally stresses the "surface problems and turn them into a roadmap" use case
  the app is built for, rather than a happy-path dataset with nothing to act on.
- Spread across 10 sources and 15 product areas — enough variety that theme
  clustering (§5) produces multiple distinct, meaningful clusters instead of one blob.
- Mix of survey feedback, support tickets, forum posts, and sales notes — reflects
  that real feedback is unstructured and comes from channels with different column
  names, which is the exact problem the column-agnostic ingester solves.

This CSV is **bundled with the app**, not uploaded by a user. There is no manual
upload screen; on first run it is auto-loaded into the database (see §6).

---

## 3. Database Schema (SQLite — `data/copilot.db`)

All screens read and write through a single SQLite database via `src/db.py`, which is
the one place the schema is defined. Every table (except `workspaces`) carries a
`workspace_id` foreign key, since the app is architected as multi-workspace even
though the shipped build runs a single default workspace.

```
workspaces
├── id (PK)
├── name
└── created_at

users
├── id (PK)
├── username, password (hashed), role
└── workspace_id (FK → workspaces)

feedback                              ← raw + AI-classified customer feedback
├── id (PK)
├── workspace_id (FK)
├── source, customer, text, rating
├── created_at
└── theme, sentiment, sentiment_score  ← added by the NLP pipeline (§5)

feature_requests                      ← auto-promoted + manually tracked asks
├── id (PK)
├── workspace_id (FK)
├── title, description, votes, theme, status
└── created_at

prioritization                        ← RICE scoring, one row per feature
├── id (PK)
├── workspace_id (FK)
├── feature_id (FK → feature_requests)
└── reach, impact, confidence, effort, rice_score, notes

documents                             ← AI-generated PRDs / user stories / summaries
├── id (PK)
├── workspace_id (FK)
├── doc_type, title, content
└── created_at

roadmap_items                         ← scheduled features by quarter
├── id (PK)
├── workspace_id (FK)
├── feature_id (FK → feature_requests)
├── title, quarter, start_date, end_date
└── status

analytics_events                      ← product usage events (feature adoption signal)
├── id (PK)
├── workspace_id (FK)
├── event_name, feature, user_count
└── event_date

chat_history                          ← AI Chat assistant conversation log
├── id (PK)
├── workspace_id (FK)
├── role, content
└── created_at
```

### Why this schema

- **`feedback` is the single source of truth for raw input.** Every other
  data-derived table (`feature_requests`, `prioritization`, `documents`,
  `roadmap_items`) is downstream of it, so re-running classification on `feedback`
  (via "Reload dataset" in Settings) can regenerate everything else deterministically.
- **`theme` is stored as denormalized text**, not a foreign key to a `themes` table.
  Themes are dynamically discovered per ingestion run by clustering (§5), not a fixed
  taxonomy — so there's nothing stable to normalize against. Duplicate-looking theme
  strings are how features get grouped/deduped (see `ingest_and_classify` dedupe logic).
- **`feature_requests` and `prioritization` are split** so that "what was asked for"
  (title, description, votes, theme) is separate from "how we scored it" (RICE
  inputs). This lets a PM re-score a feature without touching its identity/history.
- **`documents` stores generated content as opaque text/Markdown**, not structured
  fields, because PRDs/user-story docs are free-form prose meant for humans to read
  and export, not to be queried field-by-field.
- **`workspace_id` on every table** exists so the same schema supports multiple
  tenants/workspaces later without a redesign, even though the current build seeds
  one default workspace on startup.

---

## 4. Data Ingestion — Column-Agnostic CSV Handling (`src/csv_utils.py`)

Because feedback can arrive from any tool (Zendesk export, survey tool, CRM, etc.)
with arbitrary column names, ingestion doesn't assume a fixed schema. Instead:

1. **Robust parsing** (`read_csv_robust`) tries several encodings/delimiters
   (comma, semicolon, tab, auto-detect) and keeps the first attempt that actually
   splits into multiple columns, so a semicolon-delimited European export doesn't
   silently collapse into one giant column.
2. **Alias-based column guessing** (`guess_column`) maps arbitrary headers to the
   fields the app needs (`text`, `source`, `customer`, `rating`, `date`) using a
   ranked list of common aliases (e.g. `review`, `comment`, `ticket` all map to
   `text`), in three passes so identifier-like columns (`review_id`) aren't
   mistaken for content columns.
3. **Content-based fallback** (`guess_free_text_column`, `guess_date_column`,
   `guess_numeric_column`) kicks in when no header matches anything — e.g. it picks
   whichever column has the longest average string length as the likely feedback
   text, or whichever column's values mostly parse as dates.

**Why:** this lets the app treat "any CSV of feedback" as valid input without
forcing every team to reformat their export first — the alternative (a rigid
expected-schema upload) would break on the very first real-world file.

---

## 5. AI Classification Pipeline (`src/nlp_utils.py`)

Every row of ingested feedback is run through two fully-offline models so the core
app works with zero external dependencies or API cost:

**Theme extraction — TF-IDF + KMeans clustering**
- Feedback text is cleaned (lowercased, URLs stripped, punctuation removed).
- Vectorized with TF-IDF (unigrams + bigrams, top 500 features, English stopwords
  removed).
- Clustered with KMeans (2–6 clusters, scaled to dataset size: `n // 4`).
- Each cluster is auto-named from its top-3 TF-IDF centroid terms (e.g. "Export /
  Reporting / Slow").

*Why clustering instead of a fixed category list:* the app has no predefined
taxonomy of product areas, and a fixed list would need manual upkeep as the product
changes. TF-IDF/KMeans discovers themes directly from the language customers
actually use, and re-clusters automatically as new feedback is ingested — so themes
stay current without engineering work. It's also why `theme` in the database is a
free-text label, not a foreign key to a lookup table (§3).

**Sentiment scoring — lexicon-based**
- A fixed positive-word / negative-word set is matched against cleaned tokens.
- Score = `(positive_count − negative_count) / word_count`; label is
  Positive/Neutral/Negative by sign.

*Why a lexicon instead of a trained/LLM classifier here:* this keeps the core
classification path dependency-light, instant, deterministic, and reproducible with
no model download or API call — important since it runs synchronously on every
ingestion, including the automatic startup seed.

**Feature-request auto-promotion**
- Any feedback text matching request-intent phrases ("would like", "please add",
  "feature request", "could you", etc.) is treated as a feature ask.
- These are grouped by theme and inserted into (or added as votes on) an existing
  `feature_requests` row — this is how raw complaints/asks become a trackable backlog
  without a PM manually re-typing every request.

**Why classify before storing, not on read:** `theme`, `sentiment`, and
`sentiment_score` are computed once at ingestion time and persisted on the `feedback`
row itself, rather than recomputed on every dashboard load. This keeps the Dashboard
fast (simple SQL aggregation) and keeps classification results stable/auditable even
if the clustering model or its parameters change later.

---

## 6. Automatic Seeding (`utils/helpers.py`)

There is no manual "upload your data" screen. Instead:

- `ensure_dataset_seeded()` runs once at app startup (`app.py`). If the `feedback`
  table for the current workspace is empty, it loads
  `data/customer_feedback_dataset.csv` and runs it through the exact same
  `ingest_and_classify()` pipeline used for any uploaded file.
- Settings → **Data** shows what's currently stored and offers a **"Reload dataset"**
  button, which wipes `feedback` / `feature_requests` / `prioritization` for the
  workspace and re-runs ingestion from scratch — useful for demoing the pipeline
  deterministically or resetting after manual edits.

**Why auto-seed instead of requiring upload:** it guarantees the Dashboard/Reports/
Roadmap/Chat screens always have real, non-empty, already-classified data to show
immediately on first run — critical for a demo/evaluation build — while still
routing through the identical ingestion code path a real user's own CSV would use,
so the seeded data is a realistic proof of the pipeline, not a special-cased mock.

---

## 7. How Each Screen Uses the Data

| Screen | Reads from | Writes to | What it does with the data |
|---|---|---|---|
| **Dashboard** | `feedback`, `feature_requests`, `documents`, `roadmap_items` | — | Live aggregates (sentiment mix, top themes, backlog size) computed directly from whatever is currently in the DB — no cached/mock numbers |
| **Reports** | `feedback` (samples), `feature_requests`, `prioritization` | `documents`, `feature_requests`, `prioritization` | Generates PRDs and user stories grounded in real feedback samples for a theme; computes/stores RICE scores; **Quick PRD** accepts raw pasted text and runs it through the same classification + a 4-agent PRD chain without requiring prior ingestion |
| **Roadmap** | `feature_requests`, `prioritization`, `roadmap_items` | `roadmap_items` | Groups scheduled features by quarter; recommends what to schedule next based on RICE-ranked, not-yet-scheduled features |
| **AI Chat** | `feedback`, `feature_requests`/`prioritization`, `roadmap_items`, `chat_history` | `chat_history` | `build_chat_context()` does lightweight keyword-overlap retrieval across feedback/features/roadmap to ground each answer in the workspace's actual data before calling the LLM (or offline fallback) |
| **Settings** | `feedback` (counts) | `workspaces`, triggers reseed | Shows dataset status; live Gemini connection test; workspace name |

**Why grounding matters here:** every AI-generated artifact (PRD, executive summary,
chat answer) is built by first pulling real rows out of `feedback` /
`feature_requests` / `roadmap_items` and passing them into the prompt as context,
rather than letting the LLM answer from general knowledge. This is what keeps
generated PRDs and chat answers specific to *this* product's actual customer
complaints instead of generic boilerplate.

---

## 8. Generative Layer — Gemini + CrewAI (`src/llm.py`, `src/agents.py`)

For PRD generation, impact scoring, executive summaries, and chat, the app uses a
**three-layer fallback chain**, tried in order:

1. **CrewAI multi-agent crew** (if `crewai` + a Gemini key are available) — chains
   specialized agents, e.g. for PRD writing: `Customer Insights Analyst` (extracts
   pain points/business rationale from feedback) → `Senior Product Manager` (writes
   the structured PRD). The "Quick PRD from raw feedback" feature uses a 4-agent
   chain: `Feedback Agent` → `Feature Agent` → `Priority Agent` → `PRD Agent`.
2. **Direct Gemini call** (`google-genai` SDK) with a fixed system prompt, if CrewAI
   isn't available/fails but a key is configured. Includes hard timeouts, retry with
   backoff on transient errors (503/429/500), and automatic fallback between two
   candidate Gemini models.
3. **Offline deterministic template** — if no key is configured or all API attempts
   fail, a hand-written Markdown template is filled in with the same theme/feedback
   data, so the app always produces a usable (if less polished) output with zero
   external dependency.

**Why multi-agent instead of one prompt:** splitting "understand the customer pain"
from "write the PM document" mirrors how a real PM team works (an analyst surfaces
insight, a PM writes the spec) and produces more grounded PRDs than a single prompt
asked to do both at once. **Why three fallback layers:** it makes the demo/deployment
resilient — a missing API key, a rate-limited model, or a network blip never breaks
the user-facing feature; it just degrades gracefully to the next layer.

---

## 9. End-to-End Data Flow

```
customer_feedback_dataset.csv
        │  (auto-seed on first run, or manual "Reload dataset")
        ▼
csv_utils.read_csv_robust + guess_column   ← column-agnostic mapping
        ▼
nlp_utils.extract_themes (TF-IDF+KMeans)
nlp_utils.score_sentiment (lexicon)
        ▼
feedback table  (theme, sentiment, sentiment_score persisted per row)
        │
        ├─► request-intent rows ─► feature_requests (auto-promoted, deduped by theme)
        │                                   │
        │                                   ▼
        │                         helpers.ensure_rice_score / save_rice_score
        │                                   ▼
        │                            prioritization table
        │                                   │
        ├──────────────► Dashboard (live aggregates)         roadmap_items ◄─┘
        │                                                   (scheduled by quarter)
        ├──────────────► Reports: llm.generate_prd / generate_user_stories
        │                          ─► documents table
        │
        └──────────────► AI Chat: helpers.build_chat_context ─► llm.chat_response
                                    (keyword-overlap retrieval across
                                     feedback + feature_requests + roadmap_items)
```

---

## 10. Summary — Why This Design

- **One bundled, realistic dataset** so every screen has real, classified data to
  show immediately, without requiring a user to prepare or upload anything first.
- **Column-agnostic ingestion** so the same pipeline works on the bundled CSV or on
  any real-world export a team drops in later.
- **Offline-first classification** (TF-IDF/KMeans + lexicon sentiment) so the core
  product works with zero API dependency, zero cost, and fully deterministic output.
- **Persisted classification results** (not recomputed per view) for fast dashboards
  and stable, auditable theme/sentiment history.
- **A single relational schema with `feedback` as the source of truth**, so every
  derived artifact (features, priorities, roadmap, documents) can be regenerated
  consistently from the same raw data.
- **Every AI-generated document is grounded** in real rows pulled from the database
  before being handed to an LLM, and gracefully falls back to CrewAI → direct Gemini
  → offline templates so the product never breaks even without an API key.
