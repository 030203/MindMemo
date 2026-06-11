# MySecondBrain Project Work Guide

## Purpose

This file is the top-level operating guide for the project.
Use it as the first entry point before continuing implementation work.

## Primary project goals

1. Build the MVP in small, stable, verifiable steps.
2. Keep product requirements, architecture, and execution rules synchronized.
3. Avoid large unchecked changes that increase regression risk.
4. Maintain a daily development record with completed work and next actions.

## Must-read files

| Path | Purpose |
|---|---|
| `docs/MySecondBrain_需求分析_V1.1.md` | Full product requirements, architecture, workflow, database, API, and roadmap baseline |
| `docs/standards/00_文档导航.md` | Documentation index and reading order |
| `docs/standards/10_分阶段开发路线图.md` | Safe phased implementation roadmap |
| `docs/standards/11_AI_Agent长期演进路线图.md` | Post-MVP AI Agent, RAG, long-term memory, and workflow roadmap |
| `docs/standards/20_开发需求基线.md` | MVP scope baseline and feature boundaries |
| `docs/standards/30_技术实现规范.md` | Backend/frontend architecture and coding rules |
| `docs/standards/40_UI与交互设计规范.md` | UI, layout, interaction, and page consistency rules |
| `docs/standards/50_执行步骤与交付流程.md` | Daily execution workflow and Definition of Done |
| `docs/standards/60_测试与验收规范.md` | Verification checklist and acceptance rules |
| `docs/standards/70_开发日志规范.md` | Daily logging structure and update rules |
| `dev_logs/README.md` | Log directory usage and automation notes |
| `dev_logs/_daily_template.md` | Standard daily log template |

## Current implementation order

MVP Phase 0-6 is now in a usable and verifiable state. Future work should follow:

1. `docs/standards/11_AI_Agent长期演进路线图.md`
2. Phase 7：Memory Intelligence Layer
3. Phase 8：Structured Facts & Temporal Index
4. Phase 9：Retrieval Evaluation Harness
5. Phase 10: Memory Relation v1 and Hybrid Retrieval improvements
6. Continue phase-by-phase; do not jump to multi-agent orchestration before retrieval quality and observability are measurable.

## Working rules

1. Only take one bounded slice at a time.
2. Every slice must end with a verification action.
3. Do not mix infrastructure refactors with user-facing feature work in the same small step unless required.
4. Keep API contracts stable before expanding UI complexity.
5. Update the daily log whenever a meaningful development step completes.

## Daily logging rules

1. Store logs in `dev_logs/`.
2. Use one file per day: `YYYY-MM-DD.md`.
3. Record:
   - completed work
   - verification performed
   - blockers or risks
   - next todos
4. Keep entries factual and tied to actual repo changes.
5. Daily automation: `MySecondBrain Daily Dev Log` runs at `21:30` local time to maintain the log baseline.

## Stop conditions before moving to the next step

Do not continue to the next implementation slice until the current slice has:

1. a clear scope boundary
2. matching documentation if contracts changed
3. a successful build or runtime verification
4. a daily log update

## Current status

The project already has:

1. the main requirements and design document
2. a FastAPI skeleton
3. a React/Vite skeleton
4. a SQLAlchemy-backed persistent data layer using local SQLite by default
5. real backend auth endpoints and token-based user isolation
6. chunk persistence and first-pass chunk-based QA retrieval
7. PostgreSQL-ready configuration through `DATABASE_URL`
8. a development standards and logging framework
9. a Phase 7-16 AI Agent long-term roadmap
10. a Phase 9 retrieval and grounded-QA evaluation harness baseline
11. a Phase 10 Memory Relation v1 surface with persisted related-memory edges
12. a Phase 11 Agentic RAG trace baseline with persisted Agent runs and workflow steps
