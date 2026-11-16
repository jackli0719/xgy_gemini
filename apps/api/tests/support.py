"""跨测试文件复用的测试助手。

两样东西：

1. ``business_today()``：业务时区的「今天」——测试里统一用它，
   不用 ``date.today()``（那是跑测试的机器的本地时区，CI 与本地会差一天）；
2. 并发测试的会合点助手（Rendezvous 等）。

**会合点（rendezvous）必须落在「实现第一次碰到该表的位置」**，
不能落在某个固定语句上：

- 读-改-写的实现里，第一句碰到 order 表的是 SELECT；
- 条件 UPDATE 的实现里，第一句碰到 order 表的是 UPDATE。

落在固定语句上，只会强制其中一种实现交错——另一种实现会被放过，
变异测试就会假绿（T-09b 踩过这个坑：把条件 UPDATE 改回读-改-写后，
并发用例居然全绿）。

所以这里判定「碰到 order 表」时，SELECT 与 UPDATE 都要认。
"""
from __future__ import annotations

import asyncio
from datetime import date

from sqlalchemy import Select, Update

from app.models.order import Order

__all__ = [
    "Rendezvous",
    "RendezvousSession",
    "business_today",
    "is_order_update",
    "touches_order",
]


def business_today() -> date:
    """业务时区（``settings.timezone``，默认 Asia/Shanghai）的今天。

    测试里**不要**用 ``date.today()``：那是**跑测试的机器**的本地时区，
    CI 上是 UTC、本地是 Asia/Shanghai，两边会差一天——「明天」的时段
    在 UTC 的 CI 上会变成「今天」，「过去的时段」也会跟着漂，
    用例就会随机红。业务日期只有一个口径，就跟后端对齐。
    """
    from app.core.timezone import today

    return today()


class Rendezvous:
    """一次性的会合点：两个协程都到了才一起放行。

    只等一个协程时最多等 10 秒就放行——测试宁可失败也不能挂死。
    """

    def __init__(self, parties: int = 2) -> None:
        self._parties = parties
        self._arrived = 0
        self._released = asyncio.Event()

    async def wait(self) -> None:
        self._arrived += 1
        if self._arrived >= self._parties:
            self._released.set()
        try:
            await asyncio.wait_for(self._released.wait(), timeout=10)
        except asyncio.TimeoutError:
            pass


def touches_order(statement) -> bool:
    """判断这条语句是不是作用在 order 表上（SELECT 或 UPDATE）。

    SELECT 按 ORM 实体判断，不能按语句文本里有没有 "order"：
    order 表有个 master_id 列，按文本判断会把查 master 也算进来。
    UPDATE 没有 column_descriptions，改看它作用的表。
    """
    if isinstance(statement, Select):
        try:
            return statement.column_descriptions[0].get("entity") is Order
        except Exception:  # noqa: BLE001 - 认不出来就当不是
            return False
    table = getattr(statement, "table", None)
    return table is not None and getattr(table, "name", None) == "order"


def is_order_update(statement) -> bool:
    """判断这条语句是不是「对 order 表的 UPDATE」。"""
    if not isinstance(statement, Update):
        return False
    table = getattr(statement, "table", None)
    return table is not None and getattr(table, "name", None) == "order"


class RendezvousSession:
    """在「第一次碰到 order 表」处会合的会话包装。

    作用是把两个并发的写操作强制排在同一个时间窗里，好让竞态出现：

    - 读-改-写的实现下，两个协程都会先读到「还等着我操作」，
      然后各自改一遍 -> 丢更新，两边都成功、写出两条日志；
    - 条件 UPDATE 的实现下，两个协程同时改，由数据库的行锁裁决，
      只有一方能改成功。

    **会合点的位置分两种**，都是为了让竞态稳定复现（而不是看运气）：

    - SELECT：会合在**执行之后**——保证两边的读都发生在任何写之前，
      两边都读到旧值；
    - UPDATE：会合在**发出之前**——两个 UPDATE 同时在飞，
      由行锁裁决谁赢。

    注意 UPDATE 不能改成「执行之后会合」：后一个 UPDATE 会等前一个的行锁，
    前一个又卡在会合点等后一个 -> 死锁。
    """

    def __init__(self, session, rendezvous: Rendezvous) -> None:
        self._session = session
        self._rendezvous = rendezvous
        self._armed = True

    async def execute(self, statement, *args, **kwargs):
        if self._armed and touches_order(statement):
            # 每个会话只拦一次：拦第二次会把自己也卡住
            self._armed = False
            if is_order_update(statement):
                await self._rendezvous.wait()
                return await self._session.execute(statement, *args, **kwargs)
            result = await self._session.execute(statement, *args, **kwargs)
            await self._rendezvous.wait()
            return result
        return await self._session.execute(statement, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._session, name)
