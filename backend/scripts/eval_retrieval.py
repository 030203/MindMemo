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
from app.models.memory import MemoryItem  # noqa: E402
from app.models.user import User  # noqa: E402
from app.schemas.memory import MemoryCreateRequest  # noqa: E402
from app.repos.user_repo import user_repository  # noqa: E402
from app.services.chunk_service import chunk_service  # noqa: E402
from app.services.fact_insight_service import fact_insight_service  # noqa: E402
from app.services.memory_service import memory_service  # noqa: E402

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


def reciprocal_rank(candidates: list[str], expected_titles: list[str]) -> float:
    expected = set(expected_titles)
    for index, title in enumerate(candidates, start=1):
        if title in expected:
            return 1 / index
    return 0.0


def evaluate_case(db, user_id, case: dict[str, Any], *, k: int, seed_titles: set[str]) -> dict[str, Any]:
    memories = list(
        db.execute(
            select(MemoryItem)
            .where(MemoryItem.user_id == user_id, MemoryItem.deleted_at.is_(None))
            .where(MemoryItem.title.in_(seed_titles))
            .order_by(MemoryItem.created_at.desc())
        )
        .scalars()
        .all()
    )
    hits = chunk_service.retrieve_relevant_chunks(db, user_id, memories, case["question"], limit=k)
    candidate_titles = [hit.memory.title or "Untitled Memory" for hit in hits]
    expected_titles = case.get("expected_titles", [])
    expected_set = set(expected_titles)
    hit_titles = [title for title in candidate_titles if title in expected_set]
    recall_at_k = len(set(hit_titles)) / len(expected_set) if expected_set else 1.0
    mrr = reciprocal_rank(candidate_titles, expected_titles)

    fact_insight = fact_insight_service.answer_question(db, user_id, case["question"])
    expected_fact_types = set(case.get("expected_fact_types") or [])
    fact_type_hit = True
    if expected_fact_types:
        fact_type_hit = fact_insight is not None and any(
            expected_title in {citation.title for citation in fact_insight.citations}
            for expected_title in expected_titles
        )

    return {
        "id": case["id"],
        "question": case["question"],
        "expected_titles": expected_titles,
        "candidate_titles": candidate_titles,
        "hit_titles": hit_titles,
        "recall_at_k": round(recall_at_k, 4),
        "reciprocal_rank": round(mrr, 4),
        "fact_type_hit": fact_type_hit,
        "top_scores": [
            {
                "title": hit.memory.title,
                "score": round(float(hit.score), 4),
                "snippet": hit.chunk.chunk_summary or hit.chunk.chunk_text[:96],
            }
            for hit in hits[:k]
        ],
    }


def build_report(dataset: dict[str, Any], case_results: list[dict[str, Any]], *, k: int) -> dict[str, Any]:
    average_recall = sum(item["recall_at_k"] for item in case_results) / max(len(case_results), 1)
    mean_reciprocal_rank = sum(item["reciprocal_rank"] for item in case_results) / max(len(case_results), 1)
    fact_cases = [item for item in case_results if item.get("fact_type_hit") is not None]
    fact_hit_rate = sum(1 for item in fact_cases if item["fact_type_hit"]) / max(len(fact_cases), 1)
    thresholds = dataset.get("thresholds", {})

    passed = (
        average_recall >= float(thresholds.get("min_average_recall_at_k", 0))
        and mean_reciprocal_rank >= float(thresholds.get("min_mean_reciprocal_rank", 0))
        and fact_hit_rate >= float(thresholds.get("min_citation_hit_rate", 0))
    )

    return {
        "dataset_version": dataset.get("version"),
        "k": k,
        "summary": {
            "case_count": len(case_results),
            "average_recall_at_k": round(average_recall, 4),
            "mean_reciprocal_rank": round(mean_reciprocal_rank, 4),
            "fact_citation_hit_rate": round(fact_hit_rate, 4),
            "passed": passed,
            "thresholds": thresholds,
        },
        "cases": case_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MySecondBrain retrieval regression eval.")
    parser.add_argument("--dataset", default=str(ROOT / "evals" / "golden_memory_dataset.json"))
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--report", default=str(ROOT / "eval_reports" / "retrieval_eval_latest.json"))
    args = parser.parse_args()

    dataset = load_dataset(Path(args.dataset))
    with SessionLocal() as db:
        user = ensure_eval_user(db)
        ensure_seed_memories(db, user.id, dataset["seed_memories"])
        db.commit()
        seed_titles = {item["title"] for item in dataset["seed_memories"]}
        results = [evaluate_case(db, user.id, case, k=args.k, seed_titles=seed_titles) for case in dataset["retrieval_cases"]]

    report = build_report(dataset, results, k=args.k)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = report["summary"]
    print(f"dataset={report['dataset_version']}")
    print(f"cases={summary['case_count']}")
    print(f"average_recall_at_{args.k}={summary['average_recall_at_k']}")
    print(f"mean_reciprocal_rank={summary['mean_reciprocal_rank']}")
    print(f"fact_citation_hit_rate={summary['fact_citation_hit_rate']}")
    print(f"report={report_path}")
    if not summary["passed"]:
        raise SystemExit("retrieval_eval=failed")
    print("retrieval_eval=passed")


if __name__ == "__main__":
    main()
