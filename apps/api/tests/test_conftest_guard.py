"""守卫的「全量运行 / 部分运行」判定测试。

这条判定决定了「集成测试数下限」这条守卫在什么时候生效：
判错了就会出现两种误报——

- 全量跑却当成部分跑：测试整体消失了也不报（下限失守）；
- 只跑一个文件却当成全量跑：拿 95 的下限卡 5 个用例，误报失败。

所以判定本身要被测试盯着。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from conftest import _detect_full_run

# apps/api/tests/test_conftest_guard.py -> apps/api
ROOT = Path(__file__).resolve().parents[1]


def _config(
    args: list[str],
    *,
    keyword: str = "",
    markexpr: str = "",
    testpaths: tuple[str, ...] = ("tests",),
) -> SimpleNamespace:
    """造一个只带 _detect_full_run 用得到的那几个属性的假 config。"""

    def getini(name: str):
        if name == "testpaths":
            return list(testpaths)
        raise ValueError(name)

    def getoption(name: str, default=None):
        if name == "keyword":
            return keyword
        if name == "markexpr":
            return markexpr
        return default

    return SimpleNamespace(
        args=list(args),
        rootpath=ROOT,
        getini=getini,
        getoption=getoption,
    )


# ---------------------------------------------------------------------
# 全量运行：命令行没缩小范围
# ---------------------------------------------------------------------


def test_no_arguments_is_full_run() -> None:
    """命令行一个路径都没给 -> 全量。"""
    assert _detect_full_run(_config([])) is True


def test_testpaths_path_is_full_run() -> None:
    """pytest 会把 testpaths 注入 config.args；指向 testpaths 本身仍是全量。"""
    assert _detect_full_run(_config(["tests"])) is True


def test_root_path_is_full_run() -> None:
    """``pytest .`` 覆盖整棵树 -> 全量。"""
    assert _detect_full_run(_config(["."])) is True


# ---------------------------------------------------------------------
# 部分运行：命令行缩小了范围
# ---------------------------------------------------------------------


def test_single_file_is_partial_run() -> None:
    """只跑一个文件 -> 部分运行（下限守卫不生效）。"""
    assert _detect_full_run(_config(["tests/api/test_orders.py"])) is False


def test_subdirectory_is_partial_run() -> None:
    """只跑一个子目录 -> 部分运行。"""
    assert _detect_full_run(_config(["tests/api"])) is False


def test_keyword_filter_is_partial_run() -> None:
    """用了 -k -> 部分运行。"""
    assert _detect_full_run(_config([], keyword="auto_confirm")) is False


def test_marker_filter_is_partial_run() -> None:
    """用了 -m -> 部分运行。"""
    assert _detect_full_run(_config([], markexpr="not integration")) is False


def test_without_testpaths_any_path_is_partial() -> None:
    """没配 testpaths 时，命令行给了路径就算部分运行。"""
    assert _detect_full_run(_config(["whatever"], testpaths=())) is False
    assert _detect_full_run(_config([], testpaths=())) is True
