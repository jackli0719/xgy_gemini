"""导出 OpenAPI 契约（openapi.json）。

用法::

    cd apps/api && python -m app.scripts.export_openapi
    # 或者走容器（推荐，跟测试同一个环境）：
    #   make openapi

产出：apps/api/openapi.json

**为什么要有这个文件**：后端接口是前端唯一的契约来源。前端照着这份 JSON
生成类型，如果后端加了接口而忘了重新导出，前端就会照着旧的契约写代码，
问题要等到联调甚至上线才暴露出来。所以 openapi.json 进版本库，
并且有一条测试盯着它跟实际路由是否一致（见 tests/api/test_openapi_contract.py）。

**只导公开路由**：FastAPI 的 ``app.openapi()`` 只收 ``include_in_schema=True``
的路由，``/docs`` 与 ``/openapi.json`` 本身是文档页，不在契约里。

**不依赖数据库**：只读路由表，不建连接、不查库。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.main import app

__all__ = ["OPENAPI_PATH", "export_openapi", "main"]

# apps/api/app/scripts/export_openapi.py -> 上溯 2 层到 apps/api
API_DIR = Path(__file__).resolve().parents[2]
OPENAPI_PATH = API_DIR / "openapi.json"


def export_openapi() -> dict[str, Any]:
    """返回应用的 OpenAPI 契约（纯内存，不落盘）。"""
    return app.openapi()


def main() -> int:
    """把契约写到 apps/api/openapi.json。"""
    schema = export_openapi()
    OPENAPI_PATH.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    paths = schema.get("paths", {})
    print(
        "OpenAPI 契约已导出：{}（{} 条路径 / {} 个 schema）".format(
            OPENAPI_PATH,
            len(paths),
            len(schema.get("components", {}).get("schemas", {})),
        )
    )
    for path in sorted(paths):
        methods = ",".join(sorted(m.upper() for m in paths[path]))
        print("  {:<10} {}".format(methods, path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
