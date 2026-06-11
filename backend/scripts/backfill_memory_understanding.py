from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.db import SessionLocal
from app.repos.memory_repo import memory_repository
from app.services.chunk_service import chunk_service
from app.services.fact_extraction_service import fact_extraction_service
from app.services.memory_relation_service import memory_relation_service
from app.services.memory_understanding_service import memory_understanding_service


def main() -> None:
    updated = 0
    with SessionLocal() as db:
        memories = memory_repository.list_all_active(db)
        for memory in memories:
            understanding = memory_understanding_service.understand(
                memory.content_clean or memory.content_raw or "",
                memory.category,
            )
            memory.tags = understanding.tags
            memory.keywords = understanding.keywords
            memory.entities = understanding.entities
            chunk_service.rebuild_chunks_for_memory(db, memory)
            fact_extraction_service.rebuild_facts_for_memory(db, memory)
            memory_relation_service.rebuild_for_memory(db, memory.user_id, memory)
            updated += 1
        db.commit()
    print(f"updated_memories={updated}")
    print("status=ok")


if __name__ == "__main__":
    main()
