"""0008 迁移（operator_type 补 PLATFORM_OPS）的测试。

要盯住三件事：

1. **AUTOCOMMIT 路径**：``ALTER TYPE ADD VALUE`` 必须跑在
   ``autocommit_block()`` 里。在普通事务里跑，类型锁会一直持到事务提交
   （整条迁移链跑完），期间 ``audit_log`` / ``order_status_log``
   这两张用着该类型的表写入被阻塞。
2. **幂等**：枚举取值加上去就删不掉，downgrade 只能空转，于是
   「downgrade 到 0007 再 upgrade 回 head」一定会重复加同一个值——
   语句必须带 ``IF NOT EXISTS``，否则这条路径直接炸。
3. **两条建库路径一致**：``create_all`` 建的测试库（模型侧取值）与
   ``alembic`` 建的库（0001 + 0006 + 0008）必须**取值集合相同**。

集成测试在**临时库**上跑真实的 alembic 命令（子进程），跑完就删库，
不碰测试库、更不碰开发库。
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.models.enums import OperatorType

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# apps/api —— alembic.ini 与 alembic/ 都在这儿
ALEMBIC_DIR = Path(__file__).resolve().parents[2]

# 0008 的文件名（脚本路径由 alembic 自己解析，这里只用来做源文本断言）
MIGRATION_FILE = ALEMBIC_DIR / "alembic" / "versions" / "0008_operator_type_ops.py"


# =====================================================================
# 单元测试：迁移脚本的结构
# =====================================================================


def _upgrade_node() -> ast.FunctionDef:
    """取迁移脚本里 upgrade 函数的语法树节点。"""
    tree = ast.parse(MIGRATION_FILE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
            return node
    raise AssertionError("迁移脚本里没有 upgrade 函数")


def _calls_autocommit_block(node: ast.AST) -> bool:
    """这个表达式里是不是调用了 autocommit_block()。

    用语法树而不是文本匹配：迁移的 docstring 里也写着 autocommit_block()，
    文本匹配会拿注释当代码，把「代码里其实没包 autocommit」这种坏改动放过。
    """
    return any(
        isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr == "autocommit_block"
        for child in ast.walk(node)
    )


def _sql_statements(node: ast.AST) -> list[str]:
    """这个函数里执行的所有 SQL 字面量。"""
    return [
        arg.value
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "execute"
        for arg in call.args
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
    ]


def test_alter_type_runs_in_autocommit_block() -> None:
    """ALTER TYPE 必须在 autocommit_block() 里执行。

    这是本次迁移的核心：类型锁只持瞬时，而不是持到整条迁移链提交。
    """
    upgrade = _upgrade_node()

    autocommit_blocks = [
        node
        for node in ast.walk(upgrade)
        if isinstance(node, ast.With)
        and any(_calls_autocommit_block(item.context_expr) for item in node.items)
    ]
    assert autocommit_blocks, "upgrade 里没有 autocommit_block()"

    alter_statements = [s for s in _sql_statements(upgrade) if "ALTER TYPE" in s]
    assert alter_statements, "upgrade 里没有执行 ALTER TYPE 的语句"

    alter_calls = [
        node
        for node in ast.walk(upgrade)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
        and any(
            isinstance(arg, ast.Constant) and "ALTER TYPE" in arg.value
            for arg in node.args
        )
    ]
    # ALTER TYPE 必须落在某个 autocommit 块**里面**
    for call in alter_calls:
        inside = any(
            any(inner is call for inner in ast.walk(block))
            for block in autocommit_blocks
        )
        assert inside, "ALTER TYPE 必须在 autocommit_block() 里执行"


def test_add_value_is_idempotent() -> None:
    """ADD VALUE 必须带 IF NOT EXISTS。

    枚举取值删不掉，downgrade 是空操作，所以「downgrade 再 upgrade」
    这条路径一定会重复加同一个值。
    """
    upgrade = _upgrade_node()
    alter_statements = [s for s in _sql_statements(upgrade) if "ALTER TYPE" in s]
    assert alter_statements, "upgrade 里没有 ALTER TYPE 语句"
    for statement in alter_statements:
        assert "IF NOT EXISTS" in statement


def test_adds_platform_ops_value() -> None:
    """加的正是 PLATFORM_OPS 这一个取值（不多不少）。"""
    upgrade = _upgrade_node()
    alter_statements = [s for s in _sql_statements(upgrade) if "ALTER TYPE" in s]
    assert len(alter_statements) == 1
    assert "PLATFORM_OPS" in alter_statements[0]


def test_migration_docments_deploy_order() -> None:
    """迁移注释里写明「应用代码写 PLATFORM_OPS 之前必须先跑 0008」。"""
    source = MIGRATION_FILE.read_text(encoding="utf-8")
    assert "0008 必须已经执行" in source


def test_downgrade_is_a_noop() -> None:
    """downgrade 是空操作：PG 不支持删除枚举取值。

    别把它改成「重建类型」——那要动 audit_log / order_status_log 两张表的列。
    """
    tree = ast.parse(MIGRATION_FILE.read_text(encoding="utf-8"))
    downgrade = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "downgrade":
            downgrade = node
    assert downgrade is not None, "迁移脚本里没有 downgrade 函数"

    # downgrade 里不许有 op.execute / op.drop_* 之类的实际操作
    for node in ast.walk(downgrade):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert not node.func.attr.startswith(
                ("execute", "drop_", "create_", "alter_")
            ), "downgrade 必须是空操作"


# =====================================================================
# 集成测试：在临时库上跑真实的 alembic 命令
# =====================================================================


def _replace_db(url: str, dbname: str) -> str:
    """把连接串里的库名换掉，其余部分（用户 / 密码 / 主机 / 端口）不动。"""
    parts = urlsplit(url)
    return urlunsplit(
        (parts.scheme, parts.netloc, "/" + dbname, parts.query, parts.fragment)
    )


async def _create_db(admin_url: str, dbname: str) -> None:
    """建临时库。

    CREATE DATABASE 不能在事务里跑，所以连接用 AUTOCOMMIT 隔离级别。
    """
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text('CREATE DATABASE "{}"'.format(dbname)))
    finally:
        await engine.dispose()


async def _drop_db(admin_url: str, dbname: str) -> None:
    """删临时库。FORCE 用来踢掉残留的连接。"""
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text('DROP DATABASE IF EXISTS "{}" WITH (FORCE)'.format(dbname))
            )
    finally:
        await engine.dispose()


async def _operator_type_values(db_url: str) -> list[str]:
    """读出 operator_type 枚举的全部取值。"""
    engine = create_async_engine(db_url)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT unnest(enum_range(NULL::operator_type))")
            )
            return [row[0] for row in rows]
    finally:
        await engine.dispose()


def _alembic(db_url: str, *args: str) -> subprocess.CompletedProcess:
    """跑一条 alembic 命令，返回结果。

    用子进程而不是同进程调用 alembic API：alembic 的 env.py 会在导入时
    读一次配置（数据库地址来自环境变量），子进程才能干净地指向临时库。
    """
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
        cwd=str(ALEMBIC_DIR),
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.mark.integration
async def test_migration_roundtrip_is_idempotent() -> None:
    """upgrade -> downgrade -> upgrade 往返跑得通，重复加值不报错。"""
    if not TEST_DATABASE_URL:
        pytest.skip("需要真实 PostgreSQL：请设置 TEST_DATABASE_URL")

    dbname = "oto_mig_test_{}".format(uuid.uuid4().hex[:8])
    db_url = _replace_db(TEST_DATABASE_URL, dbname)
    admin_url = _replace_db(TEST_DATABASE_URL, "postgres")

    await _create_db(admin_url, dbname)
    try:
        # 1. 全新库 upgrade head
        result = _alembic(db_url, "upgrade", "head")
        assert result.returncode == 0, result.stdout + result.stderr

        values = await _operator_type_values(db_url)
        assert "PLATFORM_OPS" in values
        # 取值没有重复
        assert len(values) == len(set(values))

        # 2. downgrade 回 0007（枚举取值还在，downgrade 是空操作）
        result = _alembic(db_url, "downgrade", "0007_provider_status")
        assert result.returncode == 0, result.stdout + result.stderr

        # 3. 再 upgrade 回 head：同一个值被加第二次
        #    语句带 IF NOT EXISTS，所以这里必须是成功的
        result = _alembic(db_url, "upgrade", "head")
        assert result.returncode == 0, result.stdout + result.stderr

        values = await _operator_type_values(db_url)
        assert values.count("PLATFORM_OPS") == 1

        # 4. 一路退到底也不报错
        result = _alembic(db_url, "downgrade", "base")
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        await _drop_db(admin_url, dbname)


@pytest.mark.integration
async def test_alembic_enum_values_match_the_model() -> None:
    """两条建库路径的 operator_type 取值集合必须一致。

    - ``create_all`` 建的测试库：取值来自 ``app.models.enums.OperatorType``；
    - ``alembic`` 建的库：0001 建的那几个 + 0006 的 PLATFORM_FINANCE
      + 0008 的 PLATFORM_OPS。

    集合不一样就意味着同一份代码在两套库里能写的操作方不一样——
    比如模型能写 PLATFORM_OPS 而开发库的枚举里没有，插库时直接报错。
    """
    if not TEST_DATABASE_URL:
        pytest.skip("需要真实 PostgreSQL：请设置 TEST_DATABASE_URL")

    dbname = "oto_mig_test_{}".format(uuid.uuid4().hex[:8])
    db_url = _replace_db(TEST_DATABASE_URL, dbname)
    admin_url = _replace_db(TEST_DATABASE_URL, "postgres")

    await _create_db(admin_url, dbname)
    try:
        result = _alembic(db_url, "upgrade", "head")
        assert result.returncode == 0, result.stdout + result.stderr

        db_values = set(await _operator_type_values(db_url))
        model_values = {member.value for member in OperatorType}

        assert db_values == model_values, (
            "两条建库路径的 operator_type 取值不一致：\n"
            "  alembic 建的库：{}\n"
            "  模型侧：{}\n"
            "  差集：{}".format(
                sorted(db_values),
                sorted(model_values),
                sorted(db_values ^ model_values),
            )
        )
    finally:
        await _drop_db(admin_url, dbname)
