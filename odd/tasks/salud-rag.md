# salud-rag — Feature Tasks

Spanish informational health Q&A assistant (RAG) with source citations,
abstention, guardrails, and rigorous evaluation. Portfolio project 1 of 2 for an
AI Engineer application (Databricks-focused role). Target: hiring event ~2 months
from 2026-10-01.

## Scope

- **Does:** answers general health questions using only retrieved source
  documents; always cites the source; abstains when evidence is insufficient;
  refuses diagnosis and personalized dosing; detects emergencies and redirects.
- **Does not:** diagnose, recommend individual treatment, schedule
  appointments, or store patient data.
- **Not medical advice** — stated in the UI, API, and README.

## Decisions

| Area | Decision | Notes |
|---|---|---|
| Corpus | MedlinePlus health topics, Spanish XML | Public-domain summaries only; filter copyrighted content; attribute MedlinePlus.gov |
| Optional 2nd corpus | WHO publications | CC BY-NC-SA 3.0 IGO; non-commercial, attribution, share-alike |
| Rejected corpus | Colombian Minsalud clinical practice guidelines | Copyright notice forbids reproduction |
| Platform | Databricks Free Edition | Serverless only, quota-limited, non-commercial |
| Generator | `workspace.default.llm` → `system.ai.qwen3-next-80b-a3b-instruct` | Unity Gateway model service |
| Judge | `workspace.default.judge` → `system.ai.gpt-oss-120b` | Different model family than generator; reasoning model, needs high `max_tokens` |
| Embeddings | `intfloat/multilingual-e5-small` (384 dims) | Open model via sentence-transformers; requires `query:` / `passage:` prefixes |
| LLM access | OpenAI client, `base_url={host}/ai-gateway/mlflow/v1`, model = `catalog.schema.name` | `DatabricksOpenAI`, `get_open_ai_client`, and `ai_query` hit legacy endpoints (404) |
| Framework | LangChain / LangGraph | Most cited in the job posting |
| Optional | Amazon Bedrock (Kimi K3) | Comparison experiment only, via AI Gateway model provider service; credentials never in code |
| Demo hosting | External (AWS or similar) | Databricks Apps auto-stop after 24 h on Free Edition |

## Tasks

### Weeks 1–2: foundations

- [x] **1. Smoke-test models from a Databricks notebook** — generator, judge,
  and embeddings respond. Evidence: notebook run 2026-10-01 (generator and
  judge returned text; embeddings returned shape `(1, 384)`).
- [x] **2. Python project base** — `uv`, FastAPI, Pydantic, pytest; one
  endpoint with a passing test. Evidence: `GET /health` test written first
  (failed), then passed; `ruff check` and `ruff format --check` clean; live
  `uvicorn` returned `{"status":"ok"}`.
- [ ] **3. Databricks Academy learning pathway** — completed inside the
  Learning Festival window (ends 2026-10-14) for the 50% certification voucher.
  Owner: Andres (not code).
- [ ] **4. Download MedlinePlus Spanish XML** — file stored in a Unity Catalog
  volume. Source: <https://medlineplus.gov/xml.html> publishes
  `mplus_topics_compressed_YYYY-MM-DD.zip` (~4.7 MB; English and Spanish topics
  in one XML) Tuesday–Saturday. Branch: `feat/medlineplus-download`.
  - [x] 4a. Find the latest compressed topics file from the index page (pure
    function, tested against a saved HTML fixture).
  - [x] 4b. Download, extract the XML, and write a manifest (source URL, file
    date, SHA-256, size, download time); skip if already present. Standard
    library only; network injected so tests run offline. Evidence: test-first
    in five RED→GREEN cycles; independent check 8 passed, ruff clean, no new
    dependencies. `fetch_url` (real network) is not unit-tested; covered by 4d.
  - [x] 4c. Databricks notebook `notebooks/01_download_medlineplus.py` creates
    schema `workspace.salud_rag` and volume `raw`, then stores the file under
    `/Volumes/workspace/salud_rag/raw/medlineplus/`. Evidence: local end-to-end
    run against the real 2026-10-02 file (30,143,948 bytes; second run skipped;
    no `.part` left); notebook count logic gives 1016 Spanish of 2033 topics.
    Databricks runtime (volume rename, Git folder path, egress) checked in 4d.
  - [ ] 4d. Publish the repository to GitHub and clone it as a Databricks Git
    folder; run the notebook (Andres).

### Weeks 3–4: data and index

- [ ] **5. Parse XML into a Delta table** — URL, date, language, and license per
  document; copyrighted content filtered out.
- [ ] **6. Chunking v1 (fixed size)** — versioned chunk table in Delta.
- [ ] **7. Embeddings and vector index** — query returns relevant chunks.
- [ ] **8. Minimal RAG pipeline** — retrieve, generate with citation; 10 test
  questions answered and reviewed by hand.

### Weeks 4–5: evaluation (core differentiator)

- [ ] **9. Evaluation dataset (60–80 questions)** — written and reviewed by
  Andres; three groups: answerable, out of scope, trap (diagnosis/dosing
  requests).
- [ ] **10. Metrics** — retrieval hit rate, faithfulness, citation correctness,
  correct-abstention rate; run with one command, logged to MLflow.
- [ ] **11. Compared experiments** — chunking, reranking, hybrid search;
  before/after table in the README (negative results included).
- [ ] **12. Guardrails** — emergency detection, diagnosis refusal, not-medical-
  advice notice; trap cases pass a defined threshold.

### Weeks 5–6: product and close

- [ ] **13. FastAPI API and simple UI** — works locally.
- [ ] **14. MLflow tracing** — each query shows its retrieved chunks.
- [ ] **15. README** — architecture, metrics, and decisions; understandable in
  five minutes.
- [ ] **16. Two-minute demo video.**

## Risks

1. Free Edition quotas: evaluation runs are call-heavy; start small.
2. MedlinePlus summaries are short; retrieval may be too easy — add WHO corpus
   if so.
3. Task 3 deadline (2026-10-14) competes with weeks 1–2 work.

## Evidence log

| Task | Commit | Notes |
|---|---|---|
| 1 | — | Notebook-only; no repository change |
| 2 | `909033e` (`feat/project-bootstrap`) | `feat: bootstrap Python project with health endpoint` |
| 4a–4b | `3e1f8cd` (`feat/medlineplus-download`) | RDD review `review-acf8d1b6c0867032` approved (reliability lens); 5 non-blocking findings below |

## Follow-ups

Non-blocking findings from the 4a–4b review (reliability lens):

- ~~**Warning:** manifest is written non-atomically.~~ Fixed: manifest now
  goes through `.part` + replace; interrupted-write test added.
- A corrupt zip raises `zipfile.BadZipFile`, not a clear `ValueError`.
- A malformed date in a matching link aborts the whole parse.
- `dest_dir` is created before the zip is validated (test asserts emptiness of
  an existing directory).
- Partial state (XML without manifest) is not covered by a test.
