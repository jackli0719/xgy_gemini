"""预约时段库存表。

时段是「服务项 + 日期 + 起止时间」维度的一格库存：
- capacity：该时段可容纳的预约总数；
- used：已被占用的数量。

不建 provider_id —— 时段是服务项维度的库存，不是服务商维度；
服务商派单时再按 provider 过滤订单。

超卖由数据库层兜底：`used <= capacity` 的 CHECK 约束保证已用数不超过容量，
并发扣减的原子性由 T-07b-2b 的条件 UPDATE（`WHERE used + count <= capacity`）保证。
"""
import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ScheduleSlot(Base, TimestampMixin):
    """预约时段库存。"""

    __tablename__ = "schedule_slot"
    __table_args__ = (
        # 同一服务项同一日期同一开始时间只有一条时段
        UniqueConstraint(
            "item_id",
            "date",
            "start_time",
            name="uq_schedule_slot_item_date_start",
        ),
        # 查询某服务项某天的可用时段
        Index("ix_schedule_slot_item_date", "item_id", "date"),
        CheckConstraint("capacity > 0", name="ck_schedule_slot_capacity"),
        CheckConstraint("used >= 0", name="ck_schedule_slot_used"),
        CheckConstraint("used <= capacity", name="ck_schedule_slot_used_le_capacity"),
        CheckConstraint("start_time < end_time", name="ck_schedule_slot_time_range"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("service_item.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # 列名 date / start_time / end_time 与 datetime 的类型名同名，
    # 注解一律走 datetime.xxx 显式限定，避免同名遮蔽导致类型解析出错
    date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    start_time: Mapped[datetime.time] = mapped_column(Time, nullable=False)
    end_time: Mapped[datetime.time] = mapped_column(Time, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    used: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
