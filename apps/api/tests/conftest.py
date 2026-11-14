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

**全量运行 vs 部分运行**：``EXPECTED_INTEGRATION_TESTS`` 这条「数量下限」
只在**全量运行**时生效。只跑一个文件（``pytest tests/xxx.py``）或用了
``-k`` / ``-m`` 过滤时，跑到的用例本来就比全量少，拿全量的下限去卡它
是误报——这条守卫的本意是发现「测试整体消失」，不是发现「这次跑少了」。
部分运行时仍然守的是「不许静默 skip」：收集到的集成测试必须真的执行。
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

INTEGRATION_MARKER = "integration"

# 集成测试的四个计数
_collected: set[str] = set()  # 选中且会跑的
_deselected: set[str] = set()  # 被 -m "not integration" 过滤掉的
_skipped: set[str] = set()  # 选中但被 skip 的
_executed: set[str] = set()  # 真正跑了的（通过或失败）

# 这次是不是全量运行（决定「集成测试数下限」这条守卫是否生效）
_is_full_run = True

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
        # 「一个都没收集到」只在全量运行时是问题：
        # 部分运行本来就没打算收集全部
        if _is_full_run and total == 0:
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
        # 「数量下限」同样只在全量运行时生效：
        # 只跑一部分时用例数本来就比下限少，拿下限卡它是误报
        if _is_full_run and expected is not None and total < expected:
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
    if not _is_full_run:
        # 部分运行：说清楚哪条守卫没生效，别让人以为下限也查过了
        terminalreporter.write_line(
            "本次是部分运行（指定了路径或用了 -k / -m 过滤）："
            "「集成测试数下限」守卫未生效；"
            "「集成测试不许静默 skip」守卫仍然生效"
        )
    expected = _env_int("EXPECTED_INTEGRATION_TESTS")
    if _is_full_run and expected is not None and total > expected:
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
    global _is_full_run
    _is_full_run = _detect_full_run(config)
    _ensure_test_database()
    _warn_same_database()


def _detect_full_run(config) -> bool:
    """判断这次是不是全量运行。

    全量 = 命令行没缩小范围：没指定别的路径（跑的就是 pytest.ini 里的
    ``testpaths`` 整棵测试树），也没用 ``-k`` / ``-m`` 过滤。

    只指定了文件、或用了过滤表达式时，用例数本来就比全量少，
    「集成测试数下限」那条守卫不适用（见文件头说明）。

    注意 pytest 会把 ``testpaths`` 注入 ``config.args``，所以
    「命令行没给路径」和「config.args 里是 tests」要分开看：
    判据是「命令行给的路径有没有把 testpaths 整棵树盖住」。
    """
    positional = list(getattr(config, "args", None) or [])

    keyword = config.getoption("keyword", default="") or ""
    markexpr = config.getoption("markexpr", default="") or ""
    if keyword or markexpr:
        # 用了过滤表达式：跑到的用例是挑出来的
        return False

    if not positional:
        # 命令行一个路径都没给：跑的就是全部
        return True

    try:
        testpaths = [str(p) for p in (config.getini("testpaths") or [])]
    except ValueError:
        testpaths = []
    if not testpaths:
        # 没配 testpaths 时没法比对：命令行给了路径就是部分运行
        return False

    root = Path(str(config.rootpath)).resolve()
    covered = [(root / p).resolve() for p in testpaths]
    targets = []
    for arg in positional:
        try:
            targets.append((root / arg).resolve())
        except OSError:  # pragma: no cover - 路径解析不了就当部分运行
            return False
    # 命令行给的路径必须把每一棵 testpaths 都盖住，才算全量
    # （target 盖住 testpath：两者相同，或 testpath 在 target 底下）
    for testpath in covered:
        if not any(
            testpath == target or target in testpath.parents for target in targets
        ):
            return False
    return True


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
