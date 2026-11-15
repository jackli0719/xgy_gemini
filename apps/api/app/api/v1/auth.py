"""登录路由。

这是**唯一不需要 token 的业务接口**（注册与登录本身就是拿到 token 的入口）。
其余接口一律要求 ``Authorization: Bearer``（见 app.core.auth）。

**MVP 占位**：短信验证码写死（``settings.login_sms_code``，默认 123456），
不接短信网关。接口的形状按真实短信登录设计，接网关时只换 service 里的比对点。

失败语义：

- 验证码不对 -> 401（文案「验证码错误或已过期」，不区分写错 / 过期）；
- 账号被禁用 -> 403。

service 的异常在接口层翻译成 HTTPException：这个接口只有两个失败分支，
不值得为它单开一棵异常树（异常树是给「异常种类多」的链路用的）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.schemas.auth import LoginRequest, LoginResponse, LoginUser
from app.services import login as login_service

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# 验证码不对的文案。不区分「写错」和「过期」：客户端的应对是一样的（重发一条）。
LOGIN_CODE_INVALID_DETAIL = "验证码错误或已过期"

# 账号被禁用的文案
LOGIN_USER_DISABLED_DETAIL = "账号已被禁用"


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="手机号 + 验证码登录",
)
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_session),
) -> LoginResponse:
    """用手机号和验证码登录，返回访问令牌。

    手机号没注册过会自动建号（C 端「登录即注册」）。
    """
    try:
        result = await login_service.login(
            session, phone=payload.phone, code=payload.code
        )
    except login_service.InvalidLoginCodeError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=LOGIN_CODE_INVALID_DETAIL,
        ) from None
    except login_service.LoginUserDisabledError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=LOGIN_USER_DISABLED_DETAIL,
        ) from None

    return LoginResponse(
        access_token=result.token,
        token_type="bearer",
        user=LoginUser(
            id=result.user.id,
            nickname=result.user.nickname,
            phone=result.user.phone,
        ),
    )
