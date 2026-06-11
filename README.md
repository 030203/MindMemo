# MindMemo

MindMemo is a private AI memory workspace for long-term notes, todos, timelines, and grounded AI Q&A.

## Current status

This repository now includes:

- a complete product requirements and system design document
- a FastAPI backend with auth, memory persistence, timeline, todos, and grounded Q&A
- a React + Vite frontend with a Chinese-first everyday memo experience
- embedding persistence, similarity retrieval, and PostgreSQL + `pgvector` validation
- source-linked AI answers that can jump back to the original memory record
- Memory Relation v1 for explainable related-memory links in detail pages
- Phase 12 insight APIs and source-linked dashboard cards for expense, reflection, learning, and project views

## Verified locally

The current local environment has already been verified with:

- frontend running at [http://127.0.0.1:6100](http://127.0.0.1:6100)
- backend running at [http://127.0.0.1:6200](http://127.0.0.1:6200)
- real login flow with refresh-token renewal
- live memory writes through HTTP API
- PostgreSQL row growth in both `memory_items` and `memory_chunks`
- `pgvector` readiness and retrieval smoke tests
- grounded Q&A with citations
- related-memory graph edges generated from shared facts, topics, entities, categories, and timeline proximity
- repaired Chinese UI copy on the main user-facing pages

## Project structure

```text
docs/                    Product, architecture, and standards documents
docs/standards/          Development rules, process, and acceptance standards
dev_logs/                Daily development logs
frontend/                React + Vite application
backend/                 FastAPI application
```

## Project operating files

- [PROJECT_WORK_GUIDE.md](PROJECT_WORK_GUIDE.md)
- [docs/standards/00_文档导航.md](docs/standards/00_文档导航.md)
- [docs/MySecondBrain_需求分析_V1.1.md](docs/MySecondBrain_需求分析_V1.1.md)
- [dev_logs/README.md](dev_logs/README.md)

## Start the project

### Backend

Install dependencies:

```powershell
cd backend
python -m pip install -r requirements.txt
```

Run with the current `.env`:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 6200
```

### Frontend

```powershell
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 6100
```

## Local URLs

- Frontend: [http://127.0.0.1:6100](http://127.0.0.1:6100)
- Backend health: [http://127.0.0.1:6200/health](http://127.0.0.1:6200/health)
- Backend docs: [http://127.0.0.1:6200/docs](http://127.0.0.1:6200/docs)

## Auth notes

- Backend access now expects a real login by default.
- Temporary anonymous fallback is still available only when `ALLOW_DEV_DEMO_USER=true`.
- Access token and refresh token are issued separately.
- The frontend will try a silent refresh before redirecting to `/auth`.
- Demo account:
  - email: `demo@example.com`
  - password: `demo123456`

## Retrieval and pgvector notes

- The backend stores chunk embeddings in `memory_chunks.embedding`.
- Default local embedding mode is `EMBEDDING_PROVIDER=local_hash`.
- Compatible remote embeddings can be enabled with:
  - `OPENAI_BASE_URL`
  - `OPENAI_API_KEY`
  - `EMBEDDING_MODEL`
- PostgreSQL mode prepares:
  - `CREATE EXTENSION IF NOT EXISTS vector`
  - HNSW index on `memory_chunks.embedding`
  - btree index on `(user_id, created_at DESC)`

Useful commands:

```powershell
cd backend
python scripts/check_pgvector_ready.py
python scripts/smoke_test_pgvector.py
python scripts/smoke_test_phase6.py
python scripts/smoke_test_phase7_facts.py
python scripts/smoke_test_phase7_insights.py
python scripts/smoke_test_phase7_dashboard_insights.py
python scripts/smoke_test_phase7_signal_timeline.py
python scripts/eval_retrieval.py
python scripts/eval_qa_grounding.py
python scripts/eval_relation_expansion.py
python scripts/smoke_test_phase9_traces.py
python scripts/smoke_test_external_tools.py
python scripts/smoke_test_phase10_relations.py
python scripts/smoke_test_phase10_relation_qa.py
python scripts/smoke_test_phase10_understanding.py
python scripts/smoke_test_phase10_citation_rerank.py
python scripts/smoke_test_phase11_agent_runs.py
python scripts/smoke_test_phase12_insights_api.py
python scripts/backfill_memory_understanding.py
```

`smoke_test_phase6.py` does not send external notifications by default. To send exactly one test notification through a configured channel, pass `--send-notification serverchan`, `--send-notification pushdeer`, or `--send-notification wecom`.

Supporting local PostgreSQL files:

- `backend/docker-compose.pgvector.yml`
- `backend/scripts/check_pgvector_ready.py`
- `backend/scripts/smoke_test_pgvector.py`

## Grounded Q&A notes

- `/api/v1/qa/ask` now has:
  1. retrieval and citation selection
  2. grounded LLM answer generation
- When model configuration is available, the backend sends only retrieved memory snippets to the LLM.
- If the LLM request fails, the API safely falls back to rule-based answer assembly.
- Frontend answers now show citation cards and support jumping into the original memory detail page.
- `hybrid_web` can now call configured Tavily web search and OpenWeather current weather tools, while still returning source citations.
- Memory-only QA now expands context through related-memory edges and stores the retrieval strategy in trace metadata.
- Memory citations are reranked with `citation_rerank_v1`, balancing direct chunk score, relation score, recency, and fact confidence.
- Chat QA requests can include recent conversation context, allowing short follow-up questions to be rewritten into a grounded retrieval query.
- QA grounding eval now checks citation hits, answer quality terms, forbidden terms, and follow-up context usage.
- Chat trace UI now shows follow-up query rewriting and Agent workflow steps for routing, retrieval, relation expansion, reranking, and answer generation.
- Phase 11 Agent runs are now persisted in `agent_runs` and `agent_run_steps`, with QA traces linking back through `agent_run_id`.
- Personal insight answers now reuse source-linked dashboard insight cards, so Phase 12 answers can jump back to memory and todo evidence instead of only showing abstract insight labels.

## Insight API notes

- Phase 12 now exposes:
  - `/api/v1/insights/overview`
  - `/api/v1/insights/expenses`
  - `/api/v1/insights/reflection`
- Each insight card now includes source anchors that point back to the underlying memory or todo records.
- The dashboard homepage consumes `/api/v1/insights/overview`, keeping the card experience aligned with the standalone insight APIs.
- Insight cards are cached per user and time window with a short TTL, and the cache is invalidated when memories or todos change.

## Memory graph notes

- `memory_relations` stores lightweight, explainable edges between memories.
- Relation scoring currently uses shared tags, keywords, topics, entities, extracted facts, category match, and temporal proximity.
- Memory detail pages call `/api/v1/memories/{memory_id}/related` to show related memories.
- `/api/v1/memories/{memory_id}/relations/rebuild` can rebuild one memory's relation edges after parser changes.
- QA traces can show `chunk_v1+relation_expand_v1` and `citation_rerank_v1` when related memories were added and citations were reranked.
- `scripts/backfill_memory_understanding.py` rebuilds existing memory tags, keywords, entities, chunks, facts, and relations after extractor changes.
- `scripts/eval_relation_expansion.py` now separates overall context hit rate from relation-expansion hit rate, and also reports expansion precision and expansion-only noise-free rate.

## Reminder notification notes

- The backend scheduler now persists reminder events and can deliver unsent reminders through PushDeer.
- ServerChan Turbo delivery is available through `SERVERCHAN_SENDKEY`.
- Enterprise WeChat group bot delivery is also available through `WECOM_WEBHOOK_URL`.
- In-app reminders continue to work without external configuration.
- To enable external notifications, set `PUSHDEER_PUSHKEY` in `backend/.env`.
- To enable ServerChan WeChat notifications, set `SERVERCHAN_SENDKEY` and enable the ServerChan channel on the Settings page.
- To enable Enterprise WeChat group notifications, set `WECOM_WEBHOOK_URL` and enable the WeCom channel on the Settings page.
- Delivery is idempotent at the reminder-event level: successfully sent reminders are marked with `sent_at`.
- Users can opt in to PushDeer on the Settings page; new users keep only in-app reminders by default.
- The Settings page can send a one-time test notification for configured external channels.

## Review Queue notes

- Review Queue items are now generated by a shared backend service.
- The scheduler backfills missing review items for active memories.
- Current MVP triggers include low-confidence memory understanding, project relation confirmation, and todo-candidate approval.
- Users can now confirm, ignore, or convert pending review items into TODOs.

## Next recommended implementation steps

1. Add step timing/error instrumentation beyond the current completed-run baseline.
2. Extend query planning beyond context rewriting into explicit sub-question and tool-selection plans.
3. Add refresh-token revocation and device session management for non-demo environments.
