"""Initial schema (existing marketplace tables + new application tables).

Revision ID: 0001
Revises:
Create Date: 2026-08-09

The marketplace DDL mirrors the EF Core `initial.sql` byte-for-byte (snake_case, uuid
PKs, jsonb columns, all indexes/FKs). The two `applications`/`application_documents`
tables are new (study-abroad application feature). On a database already provisioned by
the .NET backend, this migration is a no-op for the existing tables (IF NOT EXISTS) and
adds only the new tables.
"""

from __future__ import annotations

import re

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _split_sql(text: str) -> list[str]:
    """Split a SQL script into individual statements.

    Splits on `;` at the end of a line, but keeps `DO $$ … $$` blocks intact
    (the only multi-statement construct we use). DO blocks end with `END $$;`.
    """
    statements: list[str] = []
    buf: list[str] = []
    in_dollar = False
    for line in text.splitlines():
        stripped = line.strip()
        # Track $$ ... $$ DO blocks (single-line toggles aren't an issue; ours span lines).
        if "$$" in stripped:
            # Toggle on each occurrence count parity on the line.
            in_dollar = (stripped.count("$$") % 2 == 1) ^ in_dollar
        buf.append(line)
        if stripped.endswith(";") and not in_dollar:
            stmt = "\n".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
    tail = "\n".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


# The full marketplace schema (admins … payments + countries), verbatim from the EF
# Core initial.sql. Wrapped in CREATE TABLE IF NOT EXISTS so it's safe on an existing DB.
EXISTING_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS "__EFMigrationsHistory" (
    migration_id character varying(150) NOT NULL,
    product_version character varying(32) NOT NULL,
    CONSTRAINT pk___ef_migrations_history PRIMARY KEY (migration_id)
);

CREATE TABLE IF NOT EXISTS admins (
    id uuid NOT NULL,
    username character varying(150) NOT NULL,
    password_hash character varying(512) NOT NULL,
    first_name character varying(100) NOT NULL,
    last_name character varying(100) NOT NULL,
    role character varying(32) NOT NULL,
    is_active boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT pk_admins PRIMARY KEY (id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_admins_username ON admins (username);

CREATE TABLE IF NOT EXISTS catalog_item_types (
    id uuid NOT NULL,
    code character varying(64) NOT NULL,
    name_key character varying(128) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT pk_catalog_item_types PRIMARY KEY (id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_catalog_item_types_code ON catalog_item_types (code);

CREATE TABLE IF NOT EXISTS otps (
    id uuid NOT NULL,
    identifier character varying(256) NOT NULL,
    code_hash character varying(256) NOT NULL,
    purpose character varying(32) NOT NULL,
    attempts integer NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT pk_otps PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_otps_identifier_expires_at ON otps (identifier, expires_at);

CREATE TABLE IF NOT EXISTS subscription_plans (
    id uuid NOT NULL,
    name_key character varying(128) NOT NULL,
    description_key character varying(128) NOT NULL,
    price_toman bigint NOT NULL,
    duration_days integer NOT NULL,
    is_active boolean NOT NULL,
    sort_order integer NOT NULL,
    features jsonb,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT pk_subscription_plans PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_subscription_plans_name_key ON subscription_plans (name_key);

CREATE TABLE IF NOT EXISTS users (
    id uuid NOT NULL,
    email character varying(256),
    phone_number character varying(32),
    password_hash character varying(512),
    email_verified boolean NOT NULL,
    phone_number_verified boolean NOT NULL,
    first_name character varying(100),
    last_name character varying(100),
    status character varying(32) NOT NULL,
    preferred_language character varying(8) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT pk_users PRIMARY KEY (id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_phone_number ON users (phone_number);

CREATE TABLE IF NOT EXISTS countries (
    id uuid NOT NULL,
    code character varying(2) NOT NULL,
    name character varying(100) NOT NULL,
    flag_emoji character varying(8) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT pk_countries PRIMARY KEY (id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_countries_code ON countries (code);

CREATE TABLE IF NOT EXISTS universities (
    id uuid NOT NULL,
    catalog_item_type_id uuid NOT NULL,
    slug character varying(200) NOT NULL,
    name character varying(256) NOT NULL,
    logo_url character varying(1024),
    cover_image_url character varying(1024),
    qs_world_rank character varying(32),
    about text NOT NULL,
    international_students_pct character varying(32),
    facilities text,
    costs_of_living jsonb,
    tuition_fees jsonb,
    scholarships text,
    career_services text,
    campus_location character varying(64),
    country_id uuid,
    is_published boolean NOT NULL,
    sort_order integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT pk_universities PRIMARY KEY (id),
    CONSTRAINT fk_universities_catalog_item_types_catalog_item_type_id
        FOREIGN KEY (catalog_item_type_id) REFERENCES catalog_item_types (id) ON DELETE RESTRICT
);
DO $$ BEGIN
    ALTER TABLE universities ADD CONSTRAINT fk_universities_countries_country_id
        FOREIGN KEY (country_id) REFERENCES countries (id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
CREATE INDEX IF NOT EXISTS ix_universities_catalog_item_type_id ON universities (catalog_item_type_id);
CREATE INDEX IF NOT EXISTS ix_universities_is_published ON universities (is_published);
CREATE UNIQUE INDEX IF NOT EXISTS ix_universities_slug ON universities (slug);
CREATE INDEX IF NOT EXISTS ix_universities_country_id ON universities (country_id);

CREATE TABLE IF NOT EXISTS subscriptions (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    plan_id uuid NOT NULL,
    start_at timestamp with time zone NOT NULL,
    end_at timestamp with time zone NOT NULL,
    status character varying(32) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT pk_subscriptions PRIMARY KEY (id),
    CONSTRAINT fk_subscriptions_subscription_plans_plan_id
        FOREIGN KEY (plan_id) REFERENCES subscription_plans (id) ON DELETE RESTRICT,
    CONSTRAINT fk_subscriptions_users_user_id
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS ix_subscriptions_plan_id ON subscriptions (plan_id);
CREATE INDEX IF NOT EXISTS ix_subscriptions_status ON subscriptions (status);
CREATE INDEX IF NOT EXISTS ix_subscriptions_user_id ON subscriptions (user_id);

CREATE TABLE IF NOT EXISTS university_admissions (
    id uuid NOT NULL,
    university_id uuid NOT NULL,
    level character varying(16) NOT NULL,
    toefl character varying(32),
    ielts character varying(32),
    cambridge_cae character varying(32),
    pte character varying(32),
    ib character varying(32),
    sat character varying(32),
    gre character varying(32),
    gmat character varying(32),
    gpa character varying(32),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT pk_university_admissions PRIMARY KEY (id),
    CONSTRAINT fk_university_admissions_universities_university_id
        FOREIGN KEY (university_id) REFERENCES universities (id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_university_admissions_university_id_level
    ON university_admissions (university_id, level);

CREATE TABLE IF NOT EXISTS university_programs (
    id uuid NOT NULL,
    university_id uuid NOT NULL,
    level character varying(16) NOT NULL,
    name character varying(256) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT pk_university_programs PRIMARY KEY (id),
    CONSTRAINT fk_university_programs_universities_university_id
        FOREIGN KEY (university_id) REFERENCES universities (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_university_programs_university_id ON university_programs (university_id);

CREATE TABLE IF NOT EXISTS university_rankings (
    id uuid NOT NULL,
    university_id uuid NOT NULL,
    qs_world character varying(32),
    qs_subject character varying(32),
    qs_sustainability character varying(32),
    europe_rank character varying(32),
    criteria jsonb,
    yearly_data jsonb,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT pk_university_rankings PRIMARY KEY (id),
    CONSTRAINT fk_university_rankings_universities_university_id
        FOREIGN KEY (university_id) REFERENCES universities (id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_university_rankings_university_id ON university_rankings (university_id);

CREATE TABLE IF NOT EXISTS university_student_staff (
    id uuid NOT NULL,
    university_id uuid NOT NULL,
    total_students jsonb,
    international_students jsonb,
    total_faculty jsonb,
    student_life text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT pk_university_student_staff PRIMARY KEY (id),
    CONSTRAINT fk_university_student_staff_universities_university_id
        FOREIGN KEY (university_id) REFERENCES universities (id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_university_student_staff_university_id ON university_student_staff (university_id);

CREATE TABLE IF NOT EXISTS university_translations (
    id uuid NOT NULL,
    university_id uuid NOT NULL,
    language character varying(8) NOT NULL,
    field character varying(64) NOT NULL,
    value text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT pk_university_translations PRIMARY KEY (id),
    CONSTRAINT fk_university_translations_universities_university_id
        FOREIGN KEY (university_id) REFERENCES universities (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_university_translations_university_id ON university_translations (university_id);
CREATE UNIQUE INDEX IF NOT EXISTS ix_university_translations_university_id_language_field
    ON university_translations (university_id, language, field);

CREATE TABLE IF NOT EXISTS payments (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    subscription_id uuid NOT NULL,
    plan_id uuid NOT NULL,
    amount_toman bigint NOT NULL,
    authority character varying(64),
    ref_id character varying(64),
    card_pan character varying(32),
    status character varying(32) NOT NULL,
    gateway character varying(32) NOT NULL,
    description character varying(256) NOT NULL,
    paid_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT pk_payments PRIMARY KEY (id),
    CONSTRAINT fk_payments_subscription_plans_plan_id
        FOREIGN KEY (plan_id) REFERENCES subscription_plans (id) ON DELETE RESTRICT,
    CONSTRAINT fk_payments_subscriptions_subscription_id
        FOREIGN KEY (subscription_id) REFERENCES subscriptions (id) ON DELETE RESTRICT,
    CONSTRAINT fk_payments_users_user_id
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS ix_payments_authority ON payments (authority);
CREATE INDEX IF NOT EXISTS ix_payments_plan_id ON payments (plan_id);
CREATE INDEX IF NOT EXISTS ix_payments_subscription_id ON payments (subscription_id);
CREATE INDEX IF NOT EXISTS ix_payments_user_id ON payments (user_id);
"""

APPLICATIONS_SQL = """
CREATE TABLE IF NOT EXISTS applications (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    university_id uuid,
    program_level character varying(16),
    status character varying(32) NOT NULL,
    preferred_intake character varying(32),
    notes text,
    admin_notes text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT pk_applications PRIMARY KEY (id),
    CONSTRAINT fk_applications_users_user_id
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_applications_universities_university_id
        FOREIGN KEY (university_id) REFERENCES universities (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_applications_user_id ON applications (user_id);
CREATE INDEX IF NOT EXISTS ix_applications_status ON applications (status);

CREATE TABLE IF NOT EXISTS application_documents (
    id uuid NOT NULL,
    application_id uuid NOT NULL,
    kind character varying(32) NOT NULL,
    filename character varying(255) NOT NULL,
    storage_path text NOT NULL,
    mime character varying(128) NOT NULL,
    size bigint NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT pk_application_documents PRIMARY KEY (id),
    CONSTRAINT fk_application_documents_applications_application_id
        FOREIGN KEY (application_id) REFERENCES applications (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_application_documents_application_id ON application_documents (application_id);
"""


def upgrade() -> None:
    bind = op.get_bind()
    for stmt in _split_sql(EXISTING_SCHEMA_SQL) + _split_sql(APPLICATIONS_SQL):
        bind.execute(sa.text(stmt))


def downgrade() -> None:
    bind = op.get_bind()
    for stmt in _split_sql("DROP TABLE IF EXISTS application_documents; DROP TABLE IF EXISTS applications;"):
        bind.execute(sa.text(stmt))
    # Intentionally do not drop the marketplace tables on downgrade.
