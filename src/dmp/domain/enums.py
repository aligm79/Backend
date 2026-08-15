"""Enums, stored in Postgres as strings.

EF Core stored the C# enum *member names* (PascalCase: `SuperAdmin`, `Active`,
`PendingPayment`, `Bachelor`, …) via `.HasConversion<string>()`. To stay byte-for-byte
compatible with the existing database, these enums' `.name` values are written verbatim
to the columns. The JWT/DTO layer lowercases role strings (`super_admin`) separately.
"""

from __future__ import annotations

from enum import StrEnum


class AdminRole(StrEnum):
    SuperAdmin = "SuperAdmin"
    Admin = "Admin"


class UserStatus(StrEnum):
    Active = "Active"
    Suspended = "Suspended"


class OtpPurpose(StrEnum):
    Login = "Login"
    Register = "Register"
    Verify = "Verify"


class SubscriptionStatus(StrEnum):
    PendingPayment = "PendingPayment"
    Active = "Active"
    Expired = "Expired"
    Cancelled = "Cancelled"


class PaymentStatus(StrEnum):
    Pending = "Pending"
    Succeeded = "Succeeded"
    Failed = "Failed"
    Cancelled = "Cancelled"


class ProgramLevel(StrEnum):
    Bachelor = "Bachelor"
    Master = "Master"
    Mba = "Mba"
    Phd = "Phd"


class AdmissionLevel(StrEnum):
    General = "General"
    Bachelor = "Bachelor"
    Master = "Master"
    Mba = "Mba"
    Phd = "Phd"


# ── Application management (new feature) ────────────────────────────────────────


class ApplicationStatus(StrEnum):
    Draft = "Draft"
    Submitted = "Submitted"
    UnderReview = "UnderReview"
    Accepted = "Accepted"
    Rejected = "Rejected"
    Withdrawn = "Withdrawn"


class ApplicationDocumentKind(StrEnum):
    Transcript = "Transcript"
    Passport = "Passport"
    Sop = "Sop"  # statement of purpose
    Lor = "Lor"  # letter of recommendation
    Cv = "Cv"
    Other = "Other"


# ── Role <-> JWT string helpers ─────────────────────────────────────────────────


def admin_role_from_jwt_string(role: str) -> AdminRole:
    """Parse the lowercased JWT role string ('super_admin'/'admin') into the enum."""
    r = (role or "").lower()
    if r in ("super_admin", "superadmin"):
        return AdminRole.SuperAdmin
    return AdminRole.Admin


def admin_role_to_jwt_string(role: AdminRole) -> str:
    return "super_admin" if role == AdminRole.SuperAdmin else "admin"


def otp_purpose_from_string(purpose: str) -> OtpPurpose:
    p = (purpose or "").lower()
    if p == "login":
        return OtpPurpose.Login
    if p == "verify":
        return OtpPurpose.Verify
    return OtpPurpose.Register
