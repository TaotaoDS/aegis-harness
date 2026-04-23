"""Database package — async SQLAlchemy + PostgreSQL/pgvector.

Graceful degradation: when DATABASE_URL is not set (e.g. in test
environments) all DB operations become no-ops and the system falls back
to the file-only mode that was used in v0.9.0 and earlier.
"""
