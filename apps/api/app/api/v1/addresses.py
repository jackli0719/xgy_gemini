"""收货地址的增删改查路由。

接口层只做三件事：鉴权、收参数、把 service 的结果翻译成响应模型。

**身份只从 token 来**（R1 / R5）：

- 请求体里没有 user_id（schema 直接 422 掉）；
- 列表按 token 的 user_id 过滤；
- 改 / 删按 (address_id, token 里的 user_id) 查，查不到就是 404——
  「地址不存在」与「地址不属于你」共用同一句话，调用方没法靠错误差异
  探测别人的地址存不存在。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, get_current_user
from app.core.database import get_session
from app.schemas.address import (
    AddressCreateRequest,
    AddressResponse,
    AddressUpdateRequest,
)
from app.services import addresses as address_service

__all__ = ["router"]

router = APIRouter(prefix="/api/v1", tags=["addresses"])


def _to_address(row: address_service.AddressRow) -> AddressResponse:
    """service 的地址行 -> 响应模型。"""
    return AddressResponse(
        id=row.id,
        contact=row.contact,
        phone=row.phone,
        region=row.region,
        detail=row.detail,
    )


@router.get(
    "/addresses",
    response_model=list[AddressResponse],
    summary="我的地址列表",
)
async def list_addresses(
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[AddressResponse]:
    """返回当前用户的全部地址（按创建顺序）。"""
    rows = await address_service.list_addresses(
        session, user_id=current_user.user_id
    )
    return [_to_address(row) for row in rows]


@router.post(
    "/addresses",
    response_model=AddressResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新建地址",
)
async def create_address(
    payload: AddressCreateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> AddressResponse:
    """新建一条属于当前用户的地址。"""
    row = await address_service.create_address(
        session,
        user_id=current_user.user_id,
        contact=payload.contact,
        phone=payload.phone,
        region=payload.region,
        detail=payload.detail,
    )
    return _to_address(row)


@router.put(
    "/addresses/{address_id}",
    response_model=AddressResponse,
    summary="修改地址",
)
async def update_address(
    payload: AddressUpdateRequest,
    address_id: int = Path(..., gt=0, description="地址 ID"),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> AddressResponse:
    """修改当前用户的某条地址（整体替换四个字段）。

    地址不存在或不属于当前用户 -> 404（两种情况同构）。
    """
    row = await address_service.update_address(
        session,
        user_id=current_user.user_id,
        address_id=address_id,
        contact=payload.contact,
        phone=payload.phone,
        region=payload.region,
        detail=payload.detail,
    )
    return _to_address(row)


@router.delete(
    "/addresses/{address_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除地址",
)
async def delete_address(
    address_id: int = Path(..., gt=0, description="地址 ID"),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> Response:
    """删除当前用户的某条地址。

    地址不存在或不属于当前用户 -> 404（两种情况同构）。
    """
    await address_service.delete_address(
        session, user_id=current_user.user_id, address_id=address_id
    )
    # 204 没有响应体：直接返回 Response，绕开 JSON 序列化
    return Response(status_code=status.HTTP_204_NO_CONTENT)
