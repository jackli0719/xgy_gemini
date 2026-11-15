"""登录接口的请求 / 响应 schema。

**MVP 占位**：短信验证码不接网关，固定值由服务端配置（``settings.login_sms_code``，
默认 123456）。请求体里的 ``code`` 只是把它原样传上去比对，
所以这里只校验「非空、长度合理」，**不校验格式**——
格式不对的验证码也是「验证码错误」（401），不是 422。
把「格式不对」和「验证码不对」分成两种响应，等于多给了一个不用猜的分支。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["LoginRequest", "LoginResponse", "LoginUser"]


class LoginRequest(BaseModel):
    """手机号 + 验证码登录。"""

    model_config = ConfigDict(extra="forbid")

    phone: str = Field(
        ...,
        min_length=6,
        max_length=32,
        pattern=r"^[0-9]{6,20}$",
        description="手机号（纯数字）",
    )
    code: str = Field(
        ...,
        min_length=1,
        max_length=32,
        description="短信验证码（MVP 写死，见 settings.login_sms_code）",
    )


class LoginUser(BaseModel):
    """登录用户的基本信息（不含任何归属信息）。"""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="用户 ID")
    nickname: str = Field(..., description="昵称")
    phone: str = Field(..., description="手机号")


class LoginResponse(BaseModel):
    """登录成功：给 token 和用户信息。"""

    model_config = ConfigDict(extra="forbid")

    access_token: str = Field(..., description="访问令牌（HS256 JWT）")
    token_type: str = Field(default="bearer", description="令牌类型")
    user: LoginUser = Field(..., description="当前用户")
