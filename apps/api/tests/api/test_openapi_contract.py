"""OpenAPI 契约的检查。

前端的类型是照着 ``apps/api/openapi.json`` 生成的（``npm run generate:api``），
所以这个文件必须**跟后端实际路由一致**。两条防线：

1. **路径集合一致**：导出的路径 == FastAPI 实际挂的公开路由。
   后端加了接口忘了重新导出，前端就会照着旧契约写代码——
   这条测试会先红，逼着人重新导出。
2. **敏感字段不许出现在请求体里**：金额、身份归属这类字段必须由服务端决定，
   客户端不能声明（也不需要声明）。请求体里出现它们，说明契约被改坏了。

另外还盯一条：``/docs`` 与 ``/openapi.json`` 是文档页，不是业务接口，
不该出现在契约里（前端会照着契约生成这两个接口的调用）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute

from app.main import app

# apps/api/tests/api/test_openapi_contract.py -> 上溯 2 层到 apps/api
API_DIR = Path(__file__).resolve().parents[2]
OPENAPI_PATH = API_DIR / "openapi.json"

# 契约里绝对不许出现的请求体字段。
# 金额类：必须由服务端按服务项基准价算出来，客户端声明了就会被伪造。
# 身份类：身份只从 token 来（R1），请求体里带 user_id / provider_id 等于把隔离交给客户端。
FORBIDDEN_BODY_FIELDS = frozenset(
    {
        "amount",
        "price",
        "unit_price",
        "total_amount",
        "commission_amount",
        "net_amount",
        "user_id",
        "provider_id",
        "password",
        "token",
        "secret",
    }
)

# 下单请求体应当**恰好**是这三个字段（不多不少）。
PLACE_ORDER_FIELDS = {"item_id", "slot_id", "address_id"}


@pytest.fixture(scope="module")
def contract() -> dict[str, Any]:
    """读仓库里那份已提交的契约。"""
    assert OPENAPI_PATH.exists(), (
        "找不到 {}：先跑 `make openapi` 导出契约".format(OPENAPI_PATH)
    )
    return json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))


def _collect_route_paths(routes: Any, prefix: str = "", parent_in_schema: bool = True) -> dict[str, bool]:
    """递归收集路由表里的路径 -> 是否进 schema。

    **为什么要递归**：这版 FastAPI 的 ``include_router`` 不再把子路由摊平进
    ``app.routes``，而是塞一个 ``_IncludedRouter`` 包装对象（真正的路由在
    ``original_router.routes`` 里，额外前缀在 ``include_context.prefix``）。
    只看 ``app.routes`` 一层会一个业务路由都收不到。

    用的是 FastAPI 的内部字段名。升级 FastAPI 时这条测试要是红了，
    说明内部结构变了——照着新的结构改这里，别把断言放宽成「不比了」。
    """
    result: dict[str, bool] = {}
    for route in routes:
        if isinstance(route, APIRoute):
            result[prefix + route.path] = (
                parent_in_schema and getattr(route, "include_in_schema", True)
            )
            continue
        original_router = getattr(route, "original_router", None)
        if original_router is None:
            continue
        context = getattr(route, "include_context", None)
        sub_prefix = getattr(context, "prefix", "") or ""
        sub_in_schema = parent_in_schema and getattr(context, "include_in_schema", True)
        result.update(
            _collect_route_paths(original_router.routes, prefix + sub_prefix, sub_in_schema)
        )
    return result


def _app_route_paths() -> set[str]:
    """应用实际挂载的公开路由路径集合。"""
    collected = _collect_route_paths(app.routes)
    assert collected, (
        "一个路由都没收集到：FastAPI 的路由表结构可能变了，"
        "请检查 _collect_route_paths"
    )
    return {path for path, in_schema in collected.items() if in_schema}


def _resolve(schema: dict[str, Any], components: dict[str, Any]) -> dict[str, Any]:
    """把 ``{"$ref": "#/components/schemas/X"}`` 解析成真正的 schema。"""
    ref = schema.get("$ref")
    if not ref:
        return schema
    name = ref.rsplit("/", 1)[-1]
    resolved = components.get("schemas", {}).get(name)
    assert resolved is not None, "契约里引用了不存在的 schema：{}".format(ref)
    return resolved


def _request_body_schemas(contract: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """所有带 JSON 请求体的接口 -> (说明, schema)。"""
    components = contract.get("components", {})
    result: list[tuple[str, dict[str, Any]]] = []
    for path, item in contract.get("paths", {}).items():
        for method, operation in item.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            body = operation.get("requestBody")
            if not body:
                continue
            content = body.get("content", {})
            json_body = content.get("application/json")
            if not json_body:
                continue
            result.append(
                (
                    "{} {}".format(method.upper(), path),
                    _resolve(json_body.get("schema", {}), components),
                )
            )
    return result


# =====================================================================
# 路径集合一致
# =====================================================================


def test_contract_paths_match_app_routes(contract: dict[str, Any]) -> None:
    """契约里的路径集合 == 应用实际路由集合。"""
    contract_paths = set(contract.get("paths", {}))
    app_paths = _app_route_paths()

    missing = app_paths - contract_paths
    assert not missing, (
        "这些路由在契约里没有：{}。\n"
        "重新导出：make openapi（然后把 apps/api/openapi.json 一起提交）".format(
            sorted(missing)
        )
    )

    extra = contract_paths - app_paths
    assert not extra, (
        "契约里有多余的路径：{}。\n"
        "这些接口已经不存在了，重新导出：make openapi".format(sorted(extra))
    )


def test_contract_excludes_docs_routes(contract: dict[str, Any]) -> None:
    """``/docs`` 与 ``/openapi.json`` 是文档页，不是业务接口，不进契约。"""
    contract_paths = set(contract.get("paths", {}))
    assert "/docs" not in contract_paths
    assert "/openapi.json" not in contract_paths


def test_contract_is_up_to_date(contract: dict[str, Any]) -> None:
    """提交的契约跟当前代码生成的契约一致（路径 + schema）。

    比路径集合更严：响应模型改了、字段加了，契约也必须跟着更新。
    """
    fresh = app.openapi()

    assert contract.get("paths") == fresh.get("paths"), (
        "契约里的 paths 跟当前代码不一致。重新导出：make openapi"
    )
    assert contract.get("components") == fresh.get("components"), (
        "契约里的 components（请求 / 响应模型）跟当前代码不一致。重新导出：make openapi"
    )


# =====================================================================
# 敏感字段
# =====================================================================


def test_place_order_request_has_no_amount(contract: dict[str, Any]) -> None:
    """下单请求体恰好是 item_id / slot_id / address_id，没有金额。"""
    schemas = contract.get("components", {}).get("schemas", {})
    assert "PlaceOrderRequest" in schemas, "契约里没有 PlaceOrderRequest"

    properties = schemas["PlaceOrderRequest"].get("properties", {})
    assert set(properties) == PLACE_ORDER_FIELDS, (
        "PlaceOrderRequest 的字段集合变了：{}（应当恰好是 {}）".format(
            sorted(properties), sorted(PLACE_ORDER_FIELDS)
        )
    )
    assert "amount" not in properties, "下单请求体不许出现 amount：金额由服务端算"
    assert "user_id" not in properties, "下单请求体不许出现 user_id：身份只从 token 来"


def test_no_request_body_contains_sensitive_fields(contract: dict[str, Any]) -> None:
    """所有接口的请求体里都不许出现金额 / 身份归属这类字段。"""
    offenders: list[str] = []
    for label, schema in _request_body_schemas(contract):
        properties = schema.get("properties", {})
        for field in FORBIDDEN_BODY_FIELDS:
            if field in properties:
                offenders.append("{} -> {}".format(label, field))

    assert not offenders, "请求体里出现了不该出现的字段：{}".format(offenders)
