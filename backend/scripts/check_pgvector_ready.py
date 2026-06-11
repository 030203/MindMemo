from pathlib import Path
import sys

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings
from app.core.db import engine


def main() -> None:
    print(f"database_url={settings.database_url}")
    print(f"dialect={engine.dialect.name}")

    if engine.dialect.name != "postgresql":
        print("status=skip")
        print("reason=Current database is not PostgreSQL, so pgvector SQL readiness cannot be checked here.")
        return

    with engine.connect() as conn:
        extension_row = conn.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        ).fetchone()
        index_rows = conn.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = current_schema() "
                "AND tablename = 'memory_chunks' "
                "AND indexname IN ('idx_memory_chunks_embedding_hnsw', 'idx_memory_chunks_user_created')"
            )
        ).fetchall()

    print(f"vector_extension={'yes' if extension_row else 'no'}")
    print(f"indexes={[row[0] for row in index_rows]}")
    print("status=ok" if extension_row else "status=missing_extension")


if __name__ == "__main__":
    main()
