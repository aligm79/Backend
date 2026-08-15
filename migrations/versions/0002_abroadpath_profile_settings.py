"""AbroadPath: extended user profile + user_settings.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-09

Adds the extended-profile JSONB columns to `users` and a one-to-one
`user_settings` table (notifications, AI prefs, theme, integrations) for the
AbroadPath dashboard. Non-breaking: all new columns are nullable/defaulted.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

PROFILE_COLUMNS_SQL = """
ALTER TABLE users ADD COLUMN IF NOT EXISTS bio text;
ALTER TABLE users ADD COLUMN IF NOT EXISTS gpa character varying(16);
ALTER TABLE users ADD COLUMN IF NOT EXISTS education jsonb;
ALTER TABLE users ADD COLUMN IF NOT EXISTS test_scores jsonb;
ALTER TABLE users ADD COLUMN IF NOT EXISTS research_interests jsonb;
ALTER TABLE users ADD COLUMN IF NOT EXISTS preferred_countries jsonb;
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url character varying(1024);
"""

SETTINGS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS user_settings (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    notification_email_enabled boolean NOT NULL DEFAULT true,
    notification_push_enabled boolean NOT NULL DEFAULT true,
    notification_deadline_reminders boolean NOT NULL DEFAULT true,
    notification_email_tracker boolean NOT NULL DEFAULT true,
    ai_enabled boolean NOT NULL DEFAULT true,
    ai_model character varying(64) NOT NULL DEFAULT 'default',
    ai_temperature numeric NOT NULL DEFAULT 0.7,
    theme character varying(16) NOT NULL DEFAULT 'dark',
    integrations jsonb,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT pk_user_settings PRIMARY KEY (id),
    CONSTRAINT fk_user_settings_users_user_id
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_user_settings_user_id ON user_settings (user_id);
"""


def _split_sql(text: str) -> list[str]:
    statements: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
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
    for stmt in _split_sql(PROFILE_COLUMNS_SQL) + _split_sql(SETTINGS_TABLE_SQL):
        bind.execute(sa.text(stmt))


def downgrade() -> None:
    bind = op.get_bind()
    for stmt in _split_sql(
        "DROP TABLE IF EXISTS user_settings;\n"
        "ALTER TABLE users DROP COLUMN IF EXISTS bio;\n"
        "ALTER TABLE users DROP COLUMN IF EXISTS gpa;\n"
        "ALTER TABLE users DROP COLUMN IF EXISTS education;\n"
        "ALTER TABLE users DROP COLUMN IF EXISTS test_scores;\n"
        "ALTER TABLE users DROP COLUMN IF EXISTS research_interests;\n"
        "ALTER TABLE users DROP COLUMN IF EXISTS preferred_countries;\n"
        "ALTER TABLE users DROP COLUMN IF EXISTS avatar_url;\n"
    ):
        bind.execute(sa.text(stmt))
