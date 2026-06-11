# Migrations

This directory is reserved for database migration files.

## Current status

Phase 1 uses:

- SQLAlchemy models
- startup table initialization for local development
- SQLite as the default local database
- PostgreSQL-compatible configuration through `DATABASE_URL`

## Next step

When PostgreSQL becomes the main runtime target, add Alembic here and move schema evolution from `create_all()` to explicit migration files.
