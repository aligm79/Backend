"""Plans: direct display fields (name/description) + currency (Rials).

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-22

Prices are integers in the plan's currency — Rials (IRR) for now. The display
name/description avoid the i18n-key indirection for admin-created plans.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

UPGRADE_SQL = """
ALTER TABLE subscription_plans ADD COLUMN IF NOT EXISTS name character varying(128) NOT NULL DEFAULT '';
ALTER TABLE subscription_plans ADD COLUMN IF NOT EXISTS description text NOT NULL DEFAULT '';
ALTER TABLE subscription_plans ADD COLUMN IF NOT EXISTS currency character varying(8) NOT NULL DEFAULT 'IRR';
"""

DOWNGRADE_SQL = """
ALTER TABLE subscription_plans DROP COLUMN IF EXISTS currency;
ALTER TABLE subscription_plans DROP COLUMN IF EXISTS description;
ALTER TABLE subscription_plans DROP COLUMN IF EXISTS name;
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
