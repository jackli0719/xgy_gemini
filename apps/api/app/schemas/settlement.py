"""结算确认接口的响应 schema。

**响应里没有任何身份字段**：确认人（confirmed_by）由服务端从
token 的 user_id 写入，客户端不能自报「我替谁确认」。

金额只回一个 net_amount（服务商实收）——这是打款依据的那个数。
total_amount / commission_amount 已经写在结算单上，
需要时按结算单 id 去查，不在确认响应里重复一遍。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import SettlementStatus

__all__ = ["ConfirmSettlementResult"]


class ConfirmSettlementResult(BaseModel):
    """确认结算后的结算单状态。"""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="结算单 ID")
    status: SettlementStatus = Field(..., description="结算单状态（确认后为 CONFIRMED）")
    net_amount: Decimal = Field(..., description="服务商实收金额")
    confirmed_at: datetime | None = Field(
        None, description="确认时间（确认后非空）"
    )
