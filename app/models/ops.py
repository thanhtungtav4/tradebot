"""Component health cache + admin audit log (06 §5.13-5.14)."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utc_now_column
from app.models.enums import COMPONENT_STATUS, in_check


class ComponentHealth(Base):
    __tablename__ = "component_health"

    component_code: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="UNKNOWN")
    summary: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    checked_at: Mapped[datetime] = utc_now_column()
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = utc_now_column(onupdate=True)

    __table_args__ = (
        CheckConstraint(in_check("status", COMPONENT_STATUS), name="ck_health_status"),
    )


class AdminActivityLog(Base):
    __tablename__ = "admin_activity_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="ADMIN")
    actor_id: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[str | None] = mapped_column(Text)
    before_state: Mapped[dict | None] = mapped_column(JSONB)
    after_state: Mapped[dict | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = utc_now_column()
