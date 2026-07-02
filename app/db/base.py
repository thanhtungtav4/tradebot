"""Declarative base + shared column helpers."""

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utc_now_column(*, onupdate: bool = False) -> Mapped[datetime]:
    """TIMESTAMPTZ NOT NULL DEFAULT NOW(), optionally bumped on update."""
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now() if onupdate else None,
    )
