from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Text, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base, timestamp_now

DATE_TIME_SETTINGS_ID = "global"
DEFAULT_OPERATOR_TIMEZONE = "Asia/Tehran"


class DateTimeSettings(Base):
    __tablename__ = "date_time_settings"

    id: Mapped[str] = mapped_column(
        Text,
        primary_key=True,
        default=DATE_TIME_SETTINGS_ID,
        server_default=text("'global'"),
    )
    timezone: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=DEFAULT_OPERATOR_TIMEZONE,
        server_default=text("'Asia/Tehran'"),
    )
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint("id = 'global'", name="ck_date_time_settings_singleton"),
        CheckConstraint(
            "char_length(timezone) BETWEEN 1 AND 255 AND timezone = btrim(timezone)",
            name="ck_date_time_settings_timezone_shape",
        ),
    )
