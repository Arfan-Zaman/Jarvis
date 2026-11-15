"""Shared errors, time helpers and input validators."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

VERIFICATION_STATUSES = ("unverified", "user_provided", "verified", "disputed")


class JarvisError(Exception):
    """Base class for all expected JARVIS errors."""


class ValidationError(JarvisError):
    """Input was rejected."""


class NotFoundError(JarvisError):
    """A requested record does not exist."""


class PermissionDenied(JarvisError):
    """The safety layer refused an action."""


def utcnow(offset_minutes: float = 0) -> str:
    """Current UTC time as a sortable ISO-8601 string."""
    moment = datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)
    return moment.isoformat(timespec="milliseconds")


def text(field: str, *, required: bool = False, max_len: int = 20000):
    """Validator factory for text fields."""

    def validate(value):
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise ValidationError(f"{field} must be text")
        value = value.strip()
        if required and not value:
            raise ValidationError(f"{field} is required")
        if len(value) > max_len:
            raise ValidationError(f"{field} is too long (max {max_len} characters)")
        return value

    return validate


def choice(field: str, choices: tuple[str, ...]):
    """Validator factory for enumerated fields."""

    def validate(value):
        if value not in choices:
            raise ValidationError(f"{field} must be one of: {', '.join(choices)}")
        return value

    return validate


def confidence(value):
    """A confidence score between 0 (no confidence) and 1 (certain)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError("confidence must be a number between 0 and 1")
    if not 0 <= value <= 1:
        raise ValidationError("confidence must be between 0 and 1")
    return float(value)


def optional_id(field: str):
    """Validator factory for optional references to another record."""

    def validate(value):
        if value is None or value == "":
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValidationError(f"{field} must be a record id or empty")
        return value

    return validate


def optional_timestamp(field: str):
    """Validator factory for optional ISO-8601 dates or datetimes."""

    def validate(value):
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ValidationError(f"{field} must be an ISO date")
        try:
            datetime.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValidationError(f"{field} must be an ISO date (YYYY-MM-DD)") from exc
        return value.strip()

    return validate
