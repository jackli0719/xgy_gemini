"""pytest 全局配置：集成测试的统计、测试库准备、以及「不许静默 skip」守卫。

三件事：

1. 统计集成测试（marker=integration）的收集 / 执行 / skip / 被过滤数量；
2. TEST_DATABASE_URL 指向的库不存在时自动创建——
   集成 fixture 每次会 drop_all + create_all，所以这个库必须是独立测试库；
3. 守卫：集成测试不许静默 skip。
   判据是「收集到多少 / 真正执行了多少」这类真实数字，
   而不是写死的预期数量（预期数量只当下限用，用来发现测试整体消失）。

环境变量开关：

- ``REQUIRE_INTEGRATION=1``：强制集成测试必须全部真跑（make test 用）。
  有集成测试被 skip、或一个都没收集到，直接判整场失败。
- ``EXPECTED_INTEGRATION_TESTS=N``：集成测试数量下限。
- ``TEST_DATABASE_URL``：集成测试用的库地址。
"""
from __future__ import annotations

import asyncio
import os
from urllib.parse import unquote, urlsplit

import pytest

INTEGRATION_MARKER = "integration"

# 集成测试的四个计数
_collected: set[str] = set()  # 选中且会跑的
_deselected: set[str] = set()  # 被 -m "not integration" 过滤掉的
_skipped: set[str] = set()  # 选中但被 skip 的
_executed: set[str] = set()  # 真正跑了的（通过或失败）

# 守卫判定出的问题，留到终端摘要里打印
_problems: list[str] = []


# =====================================================================
# 集成测试计数
# =====================================================================
@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(items) -> None:
    """统计「会跑的」集成测试。

    trylast：等 pytest 的 mark 插件先做完 -m 过滤，统计到的才是真正会跑的。
    """
    _collected.update(
        item.nodeid for item in items if item.get_closest_marker(INTEGRATION_MARKER)
    )


def pytest_deselected(items) -> None:
    """记录被 -m 过滤掉的集成测试（make test-unit 会走这里）。"""
    _deselected.update(
        item.nodeid for item in items if item.get_closest_marker(INTEGRATION_MARKER)
    )


def pytest_runtest_logreport(report) -> None:
    """区分「跑过了」和「被 skip 了」。

    只看 setup / call 两个阶段：teardown 阶段的报告对被 skip 的用例也是
    passed，把它算进去会把「跳过」误记成「跑过」。
    """
    nodeid = report.nodeid
    if nodeid not in _collected or report.when == "teardown":
        return
    if report.skipped:
        _skipped.add(nodeid)
    elif report.when == "call":
        _executed.add(nodeid)


# =====================================================================
# 守卫
# =====================================================================
def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw.isdigit() else None


def _guard_problems() -> list[str]:
    """返回守卫发现的问题；空列表表示一切正常。"""
    problems: list[str] = []
    total = len(_collected) + len(_deselected)
    expected = _env_int("EXPECTED_INTEGRATION_TESTS")

    if _env_flag("REQUIRE_INTEGRATION"):
        if total == 0:
            problems.append(
                "一个集成测试都没收集到（marker={} 的用例数为 0）".format(
                    INTEGRATION_MARKER
                )
            )
        if _skipped:
            problems.append(
                "{} 个集成测试被 skip 了：{}".format(
                    len(_skipped), ", ".join(sorted(_skipped))
                )
            )
        if expected is not None and total < expected:
            problems.append(
                "集成测试数 {} 少于预期下限 {}".format(total, expected)
            )
    elif (
        os.environ.get("TEST_DATABASE_URL")
        and _collected
        and not _executed
    ):
        # 没开强制模式，但配了库地址却一个都没真跑 —— 同样是静默 skip
        problems.append(
            "设置了 TEST_DATABASE_URL，但 {} 个集成测试一个都没真正执行".format(
                len(_collected)
            )
        )
    return problems


def pytest_sessionfinish(session, exitstatus) -> None:
    """守卫不通过时把整场判失败。"""
    problems = _guard_problems()
    if problems:
        _problems.extend(problems)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    """打印集成测试统计；跳过数量必须显式写出来，不能静默。"""
    total = len(_collected) + len(_deselected)
    if total:
        terminalreporter.write_line(
            "integration tests: 选中 {} / 已执行 {} / skip {} / 被 -m 过滤 {}".format(
                len(_collected), len(_executed), len(_skipped), len(_deselected)
            )
        )
    if _deselected:
        terminalreporter.write_line(
            "skipped {} integration tests (被 -m 'not integration' 过滤)".format(
                len(_deselected)
            )
        )
    expected = _env_int("EXPECTED_INTEGRATION_TESTS")
    if expected is not None and total > expected:
        terminalreporter.write_line(
            "提示：集成测试数 {} 已超过 EXPECTED_INTEGRATION_TESTS={}，"
            "新增集成测试后请同步更新该值".format(total, expected)
        )
    if _problems:
        terminalreporter.write_line("")
        terminalreporter.write_line("集成测试守卫失败：", red=True)
        for problem in _problems:
            terminalreporter.write_line("  - " + problem, red=True)


# =====================================================================
# 测试库准备
# =====================================================================
def pytest_configure(config) -> None:
    """跑测试之前把测试库准备好，避免「库不存在 → 集成测试全 skip」。"""
    _ensure_test_database()
    _warn_same_database()


def _ensure_test_database() -> None:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        return
    try:
        asyncio.run(_create_database_if_missing(url))
    except Exception as exc:  # 连不上 / 没建库权限都不该让整场测试崩在配置阶段
        print("[conftest] 提示：未能确认测试库是否存在：{}".format(exc))


async def _create_database_if_missing(url: str) -> None:
    import asyncpg

    parts = urlsplit(url)
    dbname = unquote(parts.path.lstrip("/"))
    if not dbname:
        return
    connection = await asyncpg.connect(
        host=parts.hostname or "localhost",
        port=parts.port or 5432,
        user=unquote(parts.username or ""),
        password=unquote(parts.password or ""),
        # 连到维护库再建目标库
        database="postgres",
    )
    try:
        exists = await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", dbname
        )
        if not exists:
            await connection.execute(
                'CREATE DATABASE "{}"'.format(dbname.replace('"', '""'))
            )
            print("[conftest] 已创建测试库 {}".format(dbname))
    finally:
        await connection.close()


def _warn_same_database() -> None:
    """集成库和开发库指向同一个库时要提醒：集成 fixture 会 drop_all。"""
    test_url = os.environ.get("TEST_DATABASE_URL")
    dev_url = os.environ.get("DATABASE_URL")
    if not test_url or not dev_url:
        return
    test_db = urlsplit(test_url).path.lstrip("/")
    dev_db = urlsplit(dev_url).path.lstrip("/")
    if test_db and test_db == dev_db:
        print(
            "[conftest] 警告：TEST_DATABASE_URL 与 DATABASE_URL 指向同一个库 {}，"
            "集成 fixture 会 drop_all + create_all，开发数据会被清空！".format(test_db)
        )
