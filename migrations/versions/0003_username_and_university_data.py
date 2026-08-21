"""users.username + university_data landing table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-22

- `users.username` (nullable, unique) — register/login by username.
- `university_data` — raw landing table for restored university dumps; the
  canonical `universities` rows are derived from it via the import mapper.

Non-breaking: both additions are additive.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

UPGRADE_SQL = """
ALTER TABLE users ADD COLUMN IF NOT EXISTS username character varying(150);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username);
CREATE TABLE IF NOT EXISTS university_data (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    university_name text,
    guid text,
    json_content jsonb,
    inserted_at timestamp with time zone,
    CONSTRAINT pk_university_data PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_university_data_guid ON university_data (guid);
-- campus_location (varchar 64 in the original schema) is too short for dump data.
ALTER TABLE universities ALTER COLUMN campus_location TYPE varchar(256);
"""

DOWNGRADE_SQL = """
DROP TABLE IF EXISTS university_data;
DROP INDEX IF EXISTS ix_users_username;
ALTER TABLE users DROP COLUMN IF EXISTS username;
"""


def _split_sql(text_: str) -> list[str]:
    statements: list[str] = []
    buf: list[str] = []
    for line in text_.splitlines():
        buf.append(line)
        if line.strip().endswith(";"):
            stmt = "\n".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
    tail = "\n".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def upgrade() -> None:
    bind = op.get_bind()
    for stmt in _split_sql(UPGRADE_SQL):
        bind.execute(sa.text(stmt))


def downgrade() -> None:
    bind = op.get_bind()
    for stmt in _split_sql(DOWNGRADE_SQL):
        bind.execute(sa.text(stmt))
