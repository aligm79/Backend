"""SQLAlchemy ORM models for all 13 existing tables + the 2 new application tables.

Column names, types, nullability and constraints mirror the committed EF Core
`initial.sql` exactly (snake_case via explicit `__tablename__`/`__table__.c`), so the
FastAPI app can run against the existing database with no schema drift.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ..db import utcnow
from .enums import (
    AdminRole,
    AdmissionLevel,
    ApplicationDocumentKind,
    ApplicationStatus,
    OtpPurpose,
    PaymentStatus,
    ProgramLevel,
    SubscriptionStatus,
    UserStatus,
)


class Base(DeclarativeBase):
    pass


# ── Auth ────────────────────────────────────────────────────────────────────────


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    username: Mapped[str] = mapped_column(String(150), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    last_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    role: Mapped[AdminRole] = mapped_column(String(32), nullable=False, default=AdminRole.Admin)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    username: Mapped[str | None] = mapped_column(String(150), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(256), unique=True, index=True)
    phone_number: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(512))
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    phone_number_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[UserStatus] = mapped_column(String(32), nullable=False, default=UserStatus.Active)
    preferred_language: Mapped[str] = mapped_column(String(8), nullable=False, default="fa")
    # ── Extended profile (AbroadPath) ──────────────────────────────────────────
    bio: Mapped[str | None] = mapped_column(Text)
    gpa: Mapped[str | None] = mapped_column(String(16))  # string to support varied scales
    education: Mapped[dict | None] = mapped_column(JSONB)  # [{institution, degree, field, startYear, endYear, gpa}]
    test_scores: Mapped[dict | None] = mapped_column(JSONB)  # {ielts, toefl, gre, ...}
    research_interests: Mapped[dict | None] = mapped_column(JSONB)  # ["machine learning", ...]
    preferred_countries: Mapped[dict | None] = mapped_column(JSONB)  # ["US", "DE", ...]
    avatar_url: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    settings: Mapped[UserSettings | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class UserSettings(Base):
    """One-to-one user settings row (notifications, AI prefs, theme, integrations)."""

    __tablename__ = "user_settings"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    notification_email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notification_push_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notification_deadline_reminders: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notification_email_tracker: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ai_model: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    ai_temperature: Mapped[float] = mapped_column(Numeric, nullable=False, default=0.7)
    theme: Mapped[str] = mapped_column(String(16), nullable=False, default="dark")  # light/dark/system
    integrations: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    user: Mapped[User | None] = relationship(back_populates="settings")


class Otp(Base):
    __tablename__ = "otps"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    identifier: Mapped[str] = mapped_column(String(256), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    purpose: Mapped[OtpPurpose] = mapped_column(String(32), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


# ── Billing ─────────────────────────────────────────────────────────────────────


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    name_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    description_key: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    price_toman: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    features: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    subscriptions: Mapped[list[Subscription]] = relationship(back_populates="plan")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    plan_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("subscription_plans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[SubscriptionStatus] = mapped_column(
        String(32), nullable=False, default=SubscriptionStatus.PendingPayment, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    user: Mapped[User | None] = relationship()
    plan: Mapped[SubscriptionPlan | None] = relationship(back_populates="subscriptions")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    subscription_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("subscriptions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    plan_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("subscription_plans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount_toman: Mapped[int] = mapped_column(BigInteger, nullable=False)
    authority: Mapped[str | None] = mapped_column(String(64), index=True)
    ref_id: Mapped[str | None] = mapped_column(String(64))
    card_pan: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[PaymentStatus] = mapped_column(String(32), nullable=False, default=PaymentStatus.Pending)
    gateway: Mapped[str] = mapped_column(String(32), nullable=False, default="zarinpal")
    description: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    user: Mapped[User | None] = relationship()
    subscription: Mapped[Subscription | None] = relationship()
    plan: Mapped[SubscriptionPlan | None] = relationship()


# ── Catalog ─────────────────────────────────────────────────────────────────────


class CatalogItemType(Base):
    __tablename__ = "catalog_item_types"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class Country(Base):
    __tablename__ = "countries"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    code: Mapped[str] = mapped_column(String(2), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    flag_emoji: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class UniversityData(Base):
    """Raw landing table for restored university dumps (pg_dump of university_data).

    The source of truth for imports: each row is one university variant scraped
    from a ranking source, with the full semi-structured payload in `json_content`.
    Kept separate from the canonical `universities` table so future dump schema
    changes never break the app — only the mapper needs updating.
    """

    __tablename__ = "university_data"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    university_name: Mapped[str | None] = mapped_column(Text)
    guid: Mapped[str | None] = mapped_column(Text)
    json_content: Mapped[dict | None] = mapped_column(JSONB)
    inserted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class University(Base):
    __tablename__ = "universities"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    catalog_item_type_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("catalog_item_types.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    slug: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    logo_url: Mapped[str | None] = mapped_column(String(1024))
    cover_image_url: Mapped[str | None] = mapped_column(String(1024))
    qs_world_rank: Mapped[str | None] = mapped_column(String(32))
    about: Mapped[str] = mapped_column(Text, nullable=False, default="")
    international_students_pct: Mapped[str | None] = mapped_column(String(32))
    facilities: Mapped[str | None] = mapped_column(Text)
    costs_of_living: Mapped[dict | None] = mapped_column(JSONB)
    tuition_fees: Mapped[dict | None] = mapped_column(JSONB)
    scholarships: Mapped[str | None] = mapped_column(Text)
    career_services: Mapped[str | None] = mapped_column(Text)
    campus_location: Mapped[str | None] = mapped_column(String(256))
    country_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("countries.id", ondelete="SET NULL"), index=True
    )
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    catalog_item_type: Mapped[CatalogItemType | None] = relationship()
    country: Mapped[Country | None] = relationship()
    programs: Mapped[list[UniversityProgram]] = relationship(
        back_populates="university", cascade="all, delete-orphan"
    )
    admissions: Mapped[list[UniversityAdmission]] = relationship(
        back_populates="university", cascade="all, delete-orphan"
    )
    student_staff: Mapped[UniversityStudentStaff | None] = relationship(
        back_populates="university", cascade="all, delete-orphan", uselist=False
    )
    ranking: Mapped[UniversityRanking | None] = relationship(
        back_populates="university", cascade="all, delete-orphan", uselist=False
    )
    translations: Mapped[list[UniversityTranslation]] = relationship(
        back_populates="university", cascade="all, delete-orphan"
    )
    applications: Mapped[list[Application]] = relationship(back_populates="university")


class UniversityProgram(Base):
    __tablename__ = "university_programs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    university_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("universities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    level: Mapped[ProgramLevel] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    university: Mapped[University | None] = relationship(back_populates="programs")


class UniversityAdmission(Base):
    __tablename__ = "university_admissions"
    __table_args__ = (UniqueConstraint("university_id", "level", name="ix_university_admissions_university_id_level"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    university_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("universities.id", ondelete="CASCADE"), nullable=False
    )
    level: Mapped[AdmissionLevel] = mapped_column(String(16), nullable=False)
    toefl: Mapped[str | None] = mapped_column(String(32))
    ielts: Mapped[str | None] = mapped_column(String(32))
    cambridge_cae: Mapped[str | None] = mapped_column(String(32))
    pte: Mapped[str | None] = mapped_column(String(32))
    ib: Mapped[str | None] = mapped_column(String(32))
    sat: Mapped[str | None] = mapped_column(String(32))
    gre: Mapped[str | None] = mapped_column(String(32))
    gmat: Mapped[str | None] = mapped_column(String(32))
    gpa: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    university: Mapped[University | None] = relationship(back_populates="admissions")


class UniversityStudentStaff(Base):
    __tablename__ = "university_student_staff"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    university_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("universities.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    total_students: Mapped[dict | None] = mapped_column(JSONB)
    international_students: Mapped[dict | None] = mapped_column(JSONB)
    total_faculty: Mapped[dict | None] = mapped_column(JSONB)
    student_life: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    university: Mapped[University | None] = relationship(back_populates="student_staff")


class UniversityRanking(Base):
    __tablename__ = "university_rankings"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    university_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("universities.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    qs_world: Mapped[str | None] = mapped_column(String(32))
    qs_subject: Mapped[str | None] = mapped_column(String(32))
    qs_sustainability: Mapped[str | None] = mapped_column(String(32))
    europe_rank: Mapped[str | None] = mapped_column(String(32))
    criteria: Mapped[dict | None] = mapped_column(JSONB)
    yearly_data: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    university: Mapped[University | None] = relationship(back_populates="ranking")


class UniversityTranslation(Base):
    __tablename__ = "university_translations"
    __table_args__ = (
        UniqueConstraint(
            "university_id", "language", "field", name="ix_university_translations_university_id_language_field"
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    university_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("universities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="fa")
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    university: Mapped[University | None] = relationship(back_populates="translations")


# ── Applications (new feature) ──────────────────────────────────────────────────


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    university_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("universities.id", ondelete="SET NULL"), index=True
    )
    program_level: Mapped[ProgramLevel | None] = mapped_column(String(16))
    status: Mapped[ApplicationStatus] = mapped_column(
        String(32), nullable=False, default=ApplicationStatus.Draft, index=True
    )
    preferred_intake: Mapped[str | None] = mapped_column(String(32))  # e.g. "2026 Fall"
    notes: Mapped[str | None] = mapped_column(Text)
    admin_notes: Mapped[str | None] = mapped_column(Text)  # private reviewer notes
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    user: Mapped[User | None] = relationship()
    university: Mapped[University | None] = relationship(back_populates="applications")
    documents: Mapped[list[ApplicationDocument]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )


class ApplicationDocument(Base):
    __tablename__ = "application_documents"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    application_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[ApplicationDocumentKind] = mapped_column(String(32), nullable=False, default=ApplicationDocumentKind.Other)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    mime: Mapped[str] = mapped_column(String(128), nullable=False, default="application/octet-stream")
    size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    application: Mapped[Application | None] = relationship(back_populates="documents")
