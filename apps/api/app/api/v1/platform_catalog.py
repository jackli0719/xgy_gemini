"""平台侧目录管理路由（PLAT-02）：品类树 + 服务项。

五个接口：

- ``GET /api/v1/platform/categories``：品类树（含子品类与服务项）
- ``POST /api/v1/platform/categories``：新建品类
- ``PATCH /api/v1/platform/categories/{category_id}``：改品类
- ``POST /api/v1/platform/items``：新建服务项
- ``PATCH /api/v1/platform/items/{item_id}``：改服务项（含改价）

接口层只做三件事：校验入参、鉴权、把 service 的结果翻译成 HTTP。
业务判断全在 service 里（见 app.services.platform_catalog）。

**身份只从 token 来**（R1）：``require_platform_staff`` 判角色，
审计日志里的操作人由 service 从 ``CurrentUser`` 填。
请求体里出现 operator 之类字段会被 schema 直接 422。

**改的时候带 expected_status / expected_updated_at**：条件 UPDATE 的谓词是
``WHERE id = ? AND status = 期望旧状态 AND 版本号 = 期望版本号``，
别人先改了就返回 409（见 app.services.platform_catalog.update_category）。
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path
# 这里的 status 是 HTTP 状态码；下面几个查询/请求参数也叫 status（接口约定），
# 所以 HTTP 状态码这一套换个名字导入，免得同名遮蔽。
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, require_platform_staff
from app.core.database import get_session
from app.schemas.platform_catalog import (
    CreateCategoryRequest,
    CreateServiceItemRequest,
    PlatformCategoryNode,
    PlatformServiceItem,
    UpdateCategoryRequest,
    UpdateServiceItemRequest,
)
from app.services import platform_catalog

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/platform", tags=["platform-catalog"])


def _to_category_node(category: platform_catalog.PlatformCategory) -> PlatformCategoryNode:
    """service 的品类节点 -> 响应模型（子树递归转换）。"""
    return PlatformCategoryNode(
        id=category.id,
        name=category.name,
        parent_id=category.parent_id,
        sort_order=category.sort_order,
        status=category.status,
        updated_at=category.updated_at,
        items=[_to_service_item(item) for item in category.items],
        children=[_to_category_node(child) for child in category.children],
    )


def _to_service_item(item: platform_catalog.PlatformServiceItem) -> PlatformServiceItem:
    """service 的服务项 -> 响应模型。"""
    return PlatformServiceItem(
        id=item.id,
        category_id=item.category_id,
        name=item.name,
        base_price=item.base_price,
        duration_min=item.duration_min,
        status=item.status,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get(
    "/categories",
    response_model=list[PlatformCategoryNode],
    summary="品类树（含子品类与各品类下的服务项）",
)
async def list_platform_categories(
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(require_platform_staff),
) -> list[PlatformCategoryNode]:
    """返回品类树。

    **含已停用的品类与服务项**：平台侧要能看见停用的东西，
    否则没法把它们重新启用。
    """
    categories = await platform_catalog.list_catalog(session)
    return [_to_category_node(category) for category in categories]


@router.post(
    "/categories",
    response_model=PlatformCategoryNode,
    status_code=http_status.HTTP_201_CREATED,
    summary="新建品类（初始状态：启用）",
)
async def create_platform_category(
    payload: CreateCategoryRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(require_platform_staff),
) -> PlatformCategoryNode:
    """新建一个品类。

    状态**不由请求体决定**：新建一律启用，要停用再调改接口。
    """
    category = await platform_catalog.create_category(
        session,
        name=payload.name,
        parent_id=payload.parent_id,
        sort_order=payload.sort_order,
        current_user=current_user,
    )
    return _to_category_node(category)


@router.patch(
    "/categories/{category_id}",
    response_model=PlatformCategoryNode,
    summary="改品类（名称 / 排序 / 状态）",
)
async def update_platform_category(
    category_id: Annotated[int, Path(ge=1, description="品类 ID")],
    payload: UpdateCategoryRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(require_platform_staff),
) -> PlatformCategoryNode:
    """把品类改成指定的样子。

    这一行被别人改过（expected_status / expected_updated_at 对不上）-> 409。
    品类不存在 -> 404。
    """
    category = await platform_catalog.update_category(
        session,
        category_id=category_id,
        name=payload.name,
        sort_order=payload.sort_order,
        status=payload.status,
        expected_status=payload.expected_status,
        expected_updated_at=payload.expected_updated_at,
        current_user=current_user,
    )
    return _to_category_node(category)


@router.post(
    "/items",
    response_model=PlatformServiceItem,
    status_code=http_status.HTTP_201_CREATED,
    summary="新建服务项",
)
async def create_platform_item(
    payload: CreateServiceItemRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(require_platform_staff),
) -> PlatformServiceItem:
    """在某个品类下新建一个服务项。

    品类不存在 -> 404。
    """
    item = await platform_catalog.create_service_item(
        session,
        category_id=payload.category_id,
        name=payload.name,
        base_price=payload.base_price,
        duration_min=payload.duration_min,
        current_user=current_user,
    )
    return _to_service_item(item)


@router.patch(
    "/items/{item_id}",
    response_model=PlatformServiceItem,
    summary="改服务项（名称 / 基准价 / 时长 / 状态）",
)
async def update_platform_item(
    item_id: Annotated[int, Path(ge=1, description="服务项 ID")],
    payload: UpdateServiceItemRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(require_platform_staff),
) -> PlatformServiceItem:
    """把服务项改成指定的样子。

    **改价会留痕**：base_price 的 old / new 值都写进 audit_log（R3），
    new 值取自库里落下的值（``UPDATE ... RETURNING``）。
    这一行被别人改过（expected_status / expected_updated_at 对不上）-> 409。
    服务项不存在 -> 404。
    """
    item = await platform_catalog.update_service_item(
        session,
        item_id=item_id,
        name=payload.name,
        base_price=payload.base_price,
        duration_min=payload.duration_min,
        status=payload.status,
        expected_status=payload.expected_status,
        expected_updated_at=payload.expected_updated_at,
        current_user=current_user,
    )
    return _to_service_item(item)
