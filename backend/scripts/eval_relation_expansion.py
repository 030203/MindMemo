from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.evaluation import RetrievalTrace  # noqa: E402
from app.models.memory import MemoryItem  # noqa: E402
from app.models.user import User  # noqa: E402
from app.repos.user_repo import user_repository  # noqa: E402
from app.schemas.memory import MemoryCreateRequest  # noqa: E402
from app.schemas.qa import QARequest  # noqa: E402
from app.services.chunk_service import chunk_service  # noqa: E402
from app.services.fact_extraction_service import fact_extraction_service  # noqa: E402
from app.services.memory_relation_service import memory_relation_service  # noqa: E402
from app.services.memory_service import memory_service  # noqa: E402
from app.services.memory_understanding_service import memory_understanding_service  # noqa: E402
from app.services.qa_service import qa_service  # noqa: E402

EVAL_USER_EMAIL = "eval.phase9@example.com"


def ensure_eval_user(db):
    user = db.execute(select(User).where(User.email == EVAL_USER_EMAIL)).scalar_one_or_none()
    if user is not None:
        if user.deleted_at is not None:
            user.deleted_at = None
            user.status = "active"
            db.commit()
            db.refresh(user)
        return user
    try:
        user = user_repository.create_user(
            db,
            email=EVAL_USER_EMAIL,
            password_hash=hash_password("eval-password-not-for-login"),
            display_name="Phase 9 Eval User",
        )
        user_repository.create_settings(db, user.id)
        db.commit()
        db.refresh(user)
        return user
    except IntegrityError:
        db.rollback()
        return db.execute(select(User).where(User.email == EVAL_USER_EMAIL)).scalar_one()


def load_dataset(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _title_set(values: list[str] | None) -> set[str]:
    return {str(value).strip() for value in (values or []) if str(value).strip()}


def _precision_score(observed: set[str], acceptable: set[str], expected: set[str]) -> float:
    if observed:
        return len(observed & acceptable) / len(observed)
    return 0.0 if expected else 1.0


def ensure_seed_memories(db, user_id, seed_memories: list[dict[str, str]]) -> list[MemoryItem]:
    memories: list[MemoryItem] = []
    for item in seed_memories:
        stmt = select(MemoryItem).where(
            MemoryItem.user_id == user_id,
            MemoryItem.title == item["title"],
            MemoryItem.deleted_at.is_(None),
        )
        memory = db.execute(stmt).scalars().first()
        if memory is None:
            created = memory_service.create_memory(
                db,
                user_id,
                MemoryCreateRequest(
                    title=item["title"],
                    content=item["content"],
                    category=item.get("category", "memo"),
                    source_type="memo",
                    run_ai_parse=True,
                ),
            )
            memory = db.execute(select(MemoryItem).where(MemoryItem.id == created.id)).scalar_one()
        else:
            understanding = memory_understanding_service.understand(
                memory.content_clean or memory.content_raw or "",
                memory.category,
            )
            memory.tags = understanding.tags
            memory.keywords = understanding.keywords
            memory.entities = understanding.entities
            chunk_service.rebuild_chunks_for_memory(db, memory)
            fact_extraction_service.rebuild_facts_for_memory(db, memory)
        memories.append(memory)

    db.flush()
    for memory in memories:
        memory_relation_service.rebuild_for_memory(db, user_id, memory)
    db.commit()
    return memories


def latest_trace_for_question(db, user_id, question: str) -> RetrievalTrace | None:
    return (
        db.execute(
            select(RetrievalTrace)
            .where(RetrievalTrace.user_id == user_id, RetrievalTrace.question == question)
            .order_by(RetrievalTrace.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


def evaluate_case(db, user_id, case: dict[str, Any]) -> dict[str, Any]:
    response = qa_service.answer_question(
        db,
        user_id,
        QARequest(question=case["question"], mode="memory_only"),
    )
    citation_titles = [citation.title for citation in response.citations]
    trace_response = response.trace
    trace = None if trace_response is not None else latest_trace_for_question(db, user_id, case["question"])
    metadata = (
        dict(trace_response.metadata or {})
        if trace_response is not None
        else dict(trace.meta_payload or {}) if trace is not None else {}
    )
    expansions = metadata.get("related_memory_expansions", [])
    expanded_titles = [item.get("title") for item in expansions]
    retrieval_strategy = trace_response.retrieval_strategy if trace_response is not None else trace.retrieval_strategy if trace is not None else None

    anchor_set = _title_set(case.get("anchor_titles", []))
    expected_related = case.get("expected_related_titles", [])
    allowed_related = case.get("allowed_related_titles", [])
    expected_set = _title_set(expected_related)
    allowed_set = _title_set(allowed_related)
    acceptable_set = expected_set | allowed_set
    forbidden_set = _title_set(case.get("forbidden_titles", []))

    citation_related_titles = _title_set(citation_titles) - anchor_set
    expanded_related_titles = _title_set(expanded_titles) - anchor_set
    observed_related_titles = citation_related_titles | expanded_related_titles

    related_hits = sorted(expected_set & observed_related_titles)
    expansion_hits = sorted(expected_set & expanded_related_titles)
    allowed_hits = sorted(allowed_set & observed_related_titles)
    anchor_hits = sorted(anchor_set & _title_set(citation_titles))
    relation_trace_hit = bool(expansions) and retrieval_strategy == "chunk_v1+relation_expand_v1"

    noise_hits = sorted(forbidden_set & observed_related_titles)
    citation_noise_hits = sorted(forbidden_set & citation_related_titles)
    expansion_noise_hits = sorted(forbidden_set & expanded_related_titles)
    relation_precision = _precision_score(observed_related_titles, acceptable_set, expected_set)
    expansion_precision = _precision_score(expanded_related_titles, acceptable_set, expected_set)

    return {
        "id": case["id"],
        "question": case["question"],
        "anchor_titles": case.get("anchor_titles", []),
        "expected_related_titles": expected_related,
        "allowed_related_titles": allowed_related,
        "forbidden_titles": case.get("forbidden_titles", []),
        "citation_titles": citation_titles,
        "expanded_titles": expanded_titles,
        "citation_related_titles": sorted(citation_related_titles),
        "expanded_related_titles": sorted(expanded_related_titles),
        "observed_related_titles": sorted(observed_related_titles),
        "anchor_hit": bool(anchor_hits),
        "related_hit": bool(related_hits),
        "related_hits": related_hits,
        "expansion_hit": bool(expansion_hits),
        "expansion_hits": expansion_hits,
        "allowed_hits": allowed_hits,
        "noise_hit": bool(noise_hits),
        "noise_hits": noise_hits,
        "citation_noise_hit": bool(citation_noise_hits),
        "citation_noise_hits": citation_noise_hits,
        "expansion_noise_hit": bool(expansion_noise_hits),
        "expansion_noise_hits": expansion_noise_hits,
        "relation_precision": round(relation_precision, 4),
        "expansion_precision": round(expansion_precision, 4),
        "relation_trace_hit": relation_trace_hit,
        "retrieval_strategy": retrieval_strategy,
        "related_memory_count": metadata.get("related_memory_count", 0),
    }


def build_report(dataset: dict[str, Any], case_results: list[dict[str, Any]]) -> dict[str, Any]:
    thresholds = dataset.get("thresholds", {})
    case_count = max(len(case_results), 1)
    positive_cases = [item for item in case_results if item["expected_related_titles"]]
    positive_case_count = max(len(positive_cases), 1)
    anchor_hit_rate = sum(1 for item in case_results if item["anchor_hit"]) / case_count
    related_hit_rate = sum(1 for item in positive_cases if item["related_hit"]) / positive_case_count
    expansion_hit_rate = sum(1 for item in positive_cases if item["expansion_hit"]) / positive_case_count
    trace_rate = sum(1 for item in positive_cases if item["relation_trace_hit"]) / positive_case_count
    noise_free_rate = sum(1 for item in case_results if not item["noise_hit"]) / case_count
    expansion_noise_free_rate = sum(1 for item in case_results if not item["expansion_noise_hit"]) / case_count
    average_precision = sum(float(item["relation_precision"]) for item in case_results) / case_count
    average_expansion_precision = sum(float(item["expansion_precision"]) for item in case_results) / case_count
    min_context_hit_rate = float(thresholds.get("min_relation_context_hit_rate", thresholds.get("min_relation_expansion_hit_rate", 0.5)))
    min_expansion_hit_rate = float(thresholds.get("min_relation_expansion_hit_rate", 0.5))
    min_trace_rate = float(thresholds.get("min_relation_trace_rate", 1.0))
    min_precision = float(thresholds.get("min_relation_precision", 0.7))
    min_expansion_precision = float(thresholds.get("min_relation_expansion_precision", min_precision))
    min_noise_free_rate = float(thresholds.get("min_relation_noise_free_rate", 1.0))
    min_expansion_noise_free_rate = float(thresholds.get("min_relation_expansion_noise_free_rate", min_noise_free_rate))
    passed = (
        anchor_hit_rate >= 1.0
        and related_hit_rate >= min_context_hit_rate
        and expansion_hit_rate >= min_expansion_hit_rate
        and trace_rate >= min_trace_rate
        and average_precision >= min_precision
        and average_expansion_precision >= min_expansion_precision
        and noise_free_rate >= min_noise_free_rate
        and expansion_noise_free_rate >= min_expansion_noise_free_rate
    )
    return {
        "dataset_version": dataset.get("version"),
        "summary": {
            "case_count": len(case_results),
            "positive_case_count": len(positive_cases),
            "anchor_hit_rate": round(anchor_hit_rate, 4),
            "relation_context_hit_rate": round(related_hit_rate, 4),
            "relation_expansion_hit_rate": round(expansion_hit_rate, 4),
            "relation_trace_rate": round(trace_rate, 4),
            "relation_precision": round(average_precision, 4),
            "relation_expansion_precision": round(average_expansion_precision, 4),
            "relation_noise_free_rate": round(noise_free_rate, 4),
            "relation_expansion_noise_free_rate": round(expansion_noise_free_rate, 4),
            "passed": passed,
            "thresholds": thresholds,
        },
        "cases": case_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MySecondBrain relation-expanded QA eval.")
    parser.add_argument("--dataset", default=str(ROOT / "evals" / "golden_memory_dataset.json"))
    parser.add_argument("--report", default=str(ROOT / "eval_reports" / "relation_expansion_eval_latest.json"))
    args = parser.parse_args()

    dataset = load_dataset(Path(args.dataset))
    with SessionLocal() as db:
        user = ensure_eval_user(db)
        ensure_seed_memories(db, user.id, dataset["seed_memories"])
        results = [evaluate_case(db, user.id, case) for case in dataset.get("relation_cases", [])]

    report = build_report(dataset, results)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = report["summary"]
    print(f"dataset={report['dataset_version']}")
    print(f"cases={summary['case_count']}")
    print(f"positive_cases={summary['positive_case_count']}")
    print(f"anchor_hit_rate={summary['anchor_hit_rate']}")
    print(f"relation_context_hit_rate={summary['relation_context_hit_rate']}")
    print(f"relation_expansion_hit_rate={summary['relation_expansion_hit_rate']}")
    print(f"relation_trace_rate={summary['relation_trace_rate']}")
    print(f"relation_precision={summary['relation_precision']}")
    print(f"relation_expansion_precision={summary['relation_expansion_precision']}")
    print(f"relation_noise_free_rate={summary['relation_noise_free_rate']}")
    print(f"relation_expansion_noise_free_rate={summary['relation_expansion_noise_free_rate']}")
    print(f"report={report_path}")
    if not summary["passed"]:
        raise SystemExit("relation_expansion_eval=failed")
    print("relation_expansion_eval=passed")


if __name__ == "__main__":
    main()
