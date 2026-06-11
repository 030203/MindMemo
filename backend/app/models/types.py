from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

from app.core.config import settings
from pgvector.sqlalchemy import Vector

JSON_VARIANT = JSON().with_variant(JSONB, "postgresql")
EMBEDDING_VARIANT = JSON().with_variant(Vector(settings.embedding_dimension), "postgresql")
