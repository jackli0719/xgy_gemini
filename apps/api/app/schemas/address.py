"""地址接口的请求 / 响应 schema。

三条边界：

- **请求体里没有 user_id**：地址归属由服务端按 token 里的 user_id 写死（R1）。
  客户端声明归属等于把隔离交给客户端。
- **``extra="forbid"``**：多带一个字段（比如 user_id）直接 422，
  而不是被静默忽略——静默忽略会让人以为字段生效了，实际却是另一套行为。
- **响应里不回 user_id**：地址列表按当前用户过滤，回不回归属信息都一样，
  不回就少一个可被用来对照的字段。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AddressCreateRequest",
    "AddressResponse",
    "AddressUpdateRequest",
]


class AddressResponse(BaseModel):
    """一条收货地址。"""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="地址 ID")
    contact: str = Field(..., description="联系人")
    phone: str = Field(..., description="联系电话")
    region: str = Field(..., description="省市区")
    detail: str = Field(..., description="详细地址")


class AddressCreateRequest(BaseModel):
    """新建地址的请求体。

    字段集合就是「联系人 / 电话 / 地区 / 详细地址」四个，多一个少一个都算破坏契约。
    """

    model_config = ConfigDict(extra="forbid")

    contact: str = Field(..., min_length=1, max_length=64, description="联系人")
    phone: str = Field(..., min_length=1, max_length=32, description="联系电话")
    region: str = Field(..., min_length=1, max_length=255, description="省市区")
    detail: str = Field(..., min_length=1, max_length=512, description="详细地址")


class AddressUpdateRequest(AddressCreateRequest):
    """修改地址的请求体。

    PUT 是**整体替换**：四个字段都要给全，不用给就说明客户端以为它是增量更新，
    那就该用 PATCH。与新建同构，所以直接继承新建的字段定义。
    """
