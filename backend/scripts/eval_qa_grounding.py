from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
os.chdir(ROOT)
for path in [ROOT, SCRIPT_DIR]:
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.memory import MemoryItem  # noqa: E402
from app.models.user import User  # noqa: E402
from app.repos.user_repo import user_repository  # noqa: E402
from app.schemas.memory import MemoryCreateRequest  # noqa: E402
from app.schemas.qa import QARequest  # noqa: E402
from app.services.chunk_service import chunk_service  # noqa: E402
from app.services.memory_service import memory_service  # noqa: E402
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
        user = db.execute(select(User).where(User.email == EVAL_USER_EMAIL)).scalar_one()
        return user


def load_dataset(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_seed_memories(db, user_id, seed_memories: list[dict[str, str]]) -> None:
    for item in seed_memories:
        stmt = select(MemoryItem).where(
            MemoryItem.user_id == user_id,
            MemoryItem.title == item["title"],
            MemoryItem.deleted_at.is_(None),
        )
        exists = db.execute(stmt).scalars().first()
        if exists is not None:
            chunk_service.ensure_chunks_for_memory(db, exists)
            continue

        memory_service.create_memory(
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


def evaluate_case(db, user_id, case: dict[str, Any]) -> dict[str, Any]:
    response = qa_service.answer_question(
        db,
        user_id,
        QARequest(
            question=case["question"],
            mode=case.get("mode", "memory_only"),
            conversation_context=case.get("conversation_context", []),
        ),
    )
    citation_titles = [citation.title for citation in response.citations]
    expected_titles = case.get("expected_titles", [])
    expected_set = set(expected_titles)
    citation_hits = [title for title in citation_titles if title in expected_set]
    answer = response.answer.strip()
    answer_for_matching = answer.lower()
    must_include = [str(item) for item in case.get("must_include", [])]
    must_not_include = [str(item) for item in case.get("must_not_include", [])]
    included_terms = [term for term in must_include if term.lower() in answer_for_matching]
    forbidden_terms = [term for term in must_not_include if term.lower() in answer_for_matching]
    trace_metadata = response.trace.metadata if response.trace is not None else {}

    return {
        "id": case["id"],
        "question": case["question"],
        "expected_titles": expected_titles,
        "answer": answer,
        "answer_nonempty": bool(answer),
        "citation_titles": citation_titles,
        "citation_hit": bool(citation_hits),
        "citation_hits": citation_hits,
        "must_include": must_include,
        "included_terms": included_terms,
        "must_include_hit": len(included_terms) == len(must_include),
        "must_not_include": must_not_include,
        "forbidden_terms": forbidden_terms,
        "must_not_include_hit": not forbidden_terms,
        "conversation_context_used": bool(trace_metadata.get("conversation_context_used")),
        "effective_question": trace_metadata.get("effective_question"),
        "expected_context_used": bool(case.get("expect_conversation_context_used", False)),
        "suggested_followup_count": len(response.suggested_followups),
    }


def build_report(dataset: dict[str, Any], case_results: list[dict[str, Any]]) -> dict[str, Any]:
    answer_nonempty_rate = sum(1 for item in case_results if item["answer_nonempty"]) / max(len(case_results), 1)
    citation_hit_rate = sum(1 for item in case_results if item["citation_hit"]) / max(len(case_results), 1)
    quality_cases = [
        item
        for item in case_results
        if item["must_include"] or item["must_not_include"] or item["expected_context_used"]
    ]
    quality_case_count = max(len(quality_cases), 1)
    must_include_hit_rate = sum(1 for item in quality_cases if item["must_include_hit"]) / quality_case_count
    must_not_include_hit_rate = sum(1 for item in quality_cases if item["must_not_include_hit"]) / quality_case_count
    context_hit_rate = sum(
        1
        for item in quality_cases
        if not item["expected_context_used"] or item["conversation_context_used"]
    ) / quality_case_count
    min_citation_hit_rate = float(dataset.get("thresholds", {}).get("min_citation_hit_rate", 0.7))
    min_answer_quality_hit_rate = float(dataset.get("thresholds", {}).get("min_answer_quality_hit_rate", 0.8))
    passed = (
        answer_nonempty_rate >= 1.0
        and citation_hit_rate >= min_citation_hit_rate
        and must_include_hit_rate >= min_answer_quality_hit_rate
        and must_not_include_hit_rate >= min_answer_quality_hit_rate
        and context_hit_rate >= min_answer_quality_hit_rate
    )

    return {
        "dataset_version": dataset.get("version"),
        "summary": {
            "case_count": len(case_results),
            "quality_case_count": len(quality_cases),
            "answer_nonempty_rate": round(answer_nonempty_rate, 4),
            "citation_hit_rate": round(citation_hit_rate, 4),
            "must_include_hit_rate": round(must_include_hit_rate, 4),
            "must_not_include_hit_rate": round(must_not_include_hit_rate, 4),
            "conversation_context_hit_rate": round(context_hit_rate, 4),
            "min_citation_hit_rate": min_citation_hit_rate,
            "min_answer_quality_hit_rate": min_answer_quality_hit_rate,
            "passed": passed,
        },
        "cases": case_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MySecondBrain grounded QA regression eval.")
    parser.add_argument("--dataset", default=str(ROOT / "evals" / "golden_memory_dataset.json"))
    parser.add_argument("--report", default=str(ROOT / "eval_reports" / "qa_grounding_eval_latest.json"))
    args = parser.parse_args()

    dataset = load_dataset(Path(args.dataset))
    with SessionLocal() as db:
        user = ensure_eval_user(db)
        ensure_seed_memories(db, user.id, dataset["seed_memories"])
        db.commit()
        qa_cases = [*dataset["retrieval_cases"], *dataset.get("qa_quality_cases", [])]
        results = [evaluate_case(db, user.id, case) for case in qa_cases]

    report = build_report(dataset, results)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = report["summary"]
    print(f"dataset={report['dataset_version']}")
    print(f"cases={summary['case_count']}")
    print(f"quality_cases={summary['quality_case_count']}")
    print(f"answer_nonempty_rate={summary['answer_nonempty_rate']}")
    print(f"citation_hit_rate={summary['citation_hit_rate']}")
    print(f"must_include_hit_rate={summary['must_include_hit_rate']}")
    print(f"must_not_include_hit_rate={summary['must_not_include_hit_rate']}")
    print(f"conversation_context_hit_rate={summary['conversation_context_hit_rate']}")
    print(f"report={report_path}")
    if not summary["passed"]:
        raise SystemExit("qa_grounding_eval=failed")
    print("qa_grounding_eval=passed")


if __name__ == "__main__":
    main()
