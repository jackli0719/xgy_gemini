"""平台侧目录管理（品类 / 服务项）的请求与响应 schema。

与用户侧目录查询（app.schemas.catalog）的区别：

- 用户侧只看得见**启用**的品类与服务项；
- 平台侧看**全部**（含已停用），不然没法把停用的东西重新启用。

**身份只从 token 来**：这些接口的请求体里没有 operator 之类字段，
平台侧的身份与归属由服务端从 ``CurrentUser`` 取（R1）。

**改类 / 改服务项带 ``expected_status``**：条件 UPDATE 的谓词是
``WHERE id = ? AND status = 期望旧状态``，客户端把「我以为的旧状态」
一并带上来，服务端据此判断有没有被别人改过（乐观锁）。
不传就用服务端刚读到的旧状态——于是「读之后、写之前被别人改了」
这种情况也会被判成冲突（409）。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import CatalogStatus

__all__ = [
    "CreateCategoryRequest",
    "CreateServiceItemRequest",
    "PlatformCategoryNode",
    "PlatformServiceItem",
    "UpdateCategoryRequest",
    "UpdateServiceItemRequest",
]


class PlatformServiceItem(BaseModel):
    """平台侧看到的一条服务项。"""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="服务项 ID")
    category_id: int = Field(..., description="归属的品类 ID")
    name: str = Field(..., description="服务项名称")
    base_price: Decimal = Field(..., description="基准价")
    duration_min: int = Field(..., description="服务时长（分钟）")
    status: CatalogStatus = Field(..., description="服务项状态")
    created_at: datetime = Field(..., description="建档时间")


class PlatformCategoryNode(BaseModel):
    """品类树上的一个节点（含子树与本品类下的服务项）。

    服务项挂在节点上而不是单独一个接口：后台的品类页要同时看到
    「有哪些品类」和「每个品类下有哪些服务项」，一次请求拿全，
    少一次往返，也不会出现「树加载完了、服务项还在转圈」的中间态。
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="品类 ID")
    name: str = Field(..., description="品类名称")
    parent_id: int | None = Field(..., description="父品类 ID；一级品类为空")
    sort_order: int = Field(..., description="排序值（小的排前面）")
    status: CatalogStatus = Field(..., description="品类状态")
    items: list[PlatformServiceItem] = Field(
        ...,
        description="直接归属本品类的服务项（含已停用）",
    )
    children: list["PlatformCategoryNode"] = Field(..., description="子品类")


class CreateCategoryRequest(BaseModel):
    """新建品类的请求体。

    **状态不在请求体里**：新建一律「启用」（ACTIVE），
    要停用再调改接口（与服务商建档同一思路）。
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=64, description="品类名称")
    parent_id: int | None = Field(
        None,
        gt=0,
        description="父品类 ID；一级品类不传（或传 null）",
    )
    sort_order: int = Field(0, ge=0, le=9999, description="排序值（小的排前面）")


class UpdateCategoryRequest(BaseModel):
    """改品类的请求体。

    至少要改一个字段——三个都不传就是空操作，没有意义（直接 422）。

    ``expected_status`` 是**乐观锁**：带上「我以为的旧状态」，
    服务端发现实际状态已经变了就返回 409（谁先改谁赢，后改的拿到冲突）。
    不传就用服务端刚读到的旧状态。
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=64, description="品类名称")
    sort_order: int | None = Field(None, ge=0, le=9999, description="排序值")
    status: CatalogStatus | None = Field(None, description="品类状态")
    expected_status: CatalogStatus | None = Field(
        None,
        description="调用方以为的旧状态；与服务端读到的不一致时返回 409",
    )

    @model_validator(mode="after")
    def _require_at_least_one_change(self) -> "UpdateCategoryRequest":
        if (
            self.name is None
            and self.sort_order is None
            and self.status is None
        ):
            raise ValueError("至少要改一个字段（name / sort_order / status）")
        return self


class CreateServiceItemRequest(BaseModel):
    """新建服务项的请求体。

    价格是**基准价**：下单时按它算金额（实际金额由服务端算，
    见 app.domain.pricing），所以它属于要留痕的字段（R3）。
    """

    model_config = ConfigDict(extra="forbid")

    category_id: int = Field(..., gt=0, description="归属的品类 ID")
    name: str = Field(..., min_length=1, max_length=64, description="服务项名称")
    base_price: Decimal = Field(..., ge=0, description="基准价")
    duration_min: int = Field(..., gt=0, le=1440, description="服务时长（分钟）")


class UpdateServiceItemRequest(BaseModel):
    """改服务项的请求体。

    至少要改一个字段。``expected_status`` 的语义同
    ``UpdateCategoryRequest.expected_status``。
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=64, description="服务项名称")
    base_price: Decimal | None = Field(None, ge=0, description="基准价")
    duration_min: int | None = Field(None, gt=0, le=1440, description="服务时长（分钟）")
    status: CatalogStatus | None = Field(None, description="服务项状态")
    expected_status: CatalogStatus | None = Field(
        None,
        description="调用方以为的旧状态；与服务端读到的不一致时返回 409",
    )

    @model_validator(mode="after")
    def _require_at_least_one_change(self) -> "UpdateServiceItemRequest":
        if (
            self.name is None
            and self.base_price is None
            and self.duration_min is None
            and self.status is None
        ):
            raise ValueError(
                "至少要改一个字段（name / base_price / duration_min / status）"
            )
        return self
