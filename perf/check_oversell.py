#!/usr/bin/env python3
"""超卖检查：查库比对 ``used`` / ``capacity`` / 该时段上的订单数。

压测跑完必须用它收口——k6 只能看见「谁抢到了」（201 / 409），
看不见库存计数有没有被写坏。判定口径三条：

1. ``used > capacity`` —— 直接超卖（库里还有 CHECK 约束兜底，
   但压测库也该确认约束确实在）；
2. ``used != 该时段订单数`` —— 库存计数与实际订单对不上
   （少记 = 后续还能超卖，多记 = 白占库存）；
3. 竞态时段上 ``订单数 != capacity`` —— 抢到最后必须正好占满。

跑法（在压测栈的 api 容器里）::

    docker compose -f perf/compose.yaml exec api python /app/perf/check_oversell.py

有超卖时退出码为 1（Makefile 会因此失败）。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

APP_DIR = os.environ.get("OTO_API_DIR", "/app/apps/api")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from sqlalchemy import text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import engine  # noqa: E402

MANIFEST_PATH = Path(__file__).resolve().parent / "manifest.json"


def _db_name(url: str) -> str:
    return urlsplit(url).path.lstrip("/").split("?")[0]


def _guard_perf_database(url: str) -> str:
    name = _db_name(url)
    if not name.endswith("_perf"):
        raise SystemExit(
            "拒绝执行：当前库是 {!r}，不是压测库（必须以 _perf 结尾）。".format(name)
        )
    return name


async def main() -> int:
    db_name = _guard_perf_database(settings.database_url)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    race_slot_id = manifest["race"]["slot_id"]

    oversold = False
    async with engine.connect() as conn:
        # ---- 竞态时段明细 ------------------------------------------------
        row = (
            await conn.execute(
                text(
                    """
                    SELECT s.id, s.capacity, s.used,
                           (SELECT count(*) FROM "order" o WHERE o.slot_id = s.id)
                               AS order_count
                    FROM schedule_slot s
                    WHERE s.id = :slot_id
                    """
                ),
                {"slot_id": race_slot_id},
            )
        ).one_or_none()

        if row is None:
            print("[perf-check] 竞态时段 slot_id={} 不存在！".format(race_slot_id))
            return 1

        slot_id, capacity, used, order_count = row
        print(
            "[perf-check] 竞态时段 slot_id={}: capacity={} used={} 该时段订单数={}".format(
                slot_id, capacity, used, order_count
            )
        )

        if used > capacity:
            print("[perf-check]   -> 超卖：used({}) > capacity({})".format(used, capacity))
            oversold = True
        if used != order_count:
            print(
                "[perf-check]   -> 库存与订单对不上：used({}) != 订单数({})".format(
                    used, order_count
                )
            )
            oversold = True
        if order_count != capacity:
            print(
                "[perf-check]   -> 竞态时段没抢满：订单数({}) != capacity({})".format(
                    order_count, capacity
                )
            )
            oversold = True

        # ---- 全库扫一遍 --------------------------------------------------
        anomalies = (
            await conn.execute(
                text(
                    """
                    SELECT s.id, s.capacity, s.used, count(o.id) AS order_count
                    FROM schedule_slot s
                    LEFT JOIN "order" o ON o.slot_id = s.id
                    GROUP BY s.id, s.capacity, s.used
                    HAVING s.used > s.capacity
                        OR count(o.id) > s.capacity
                        OR s.used <> count(o.id)
                    ORDER BY s.id
                    """
                )
            )
        ).all()

        if anomalies:
            oversold = True
            print("[perf-check] 全库异常时段 {} 个：".format(len(anomalies)))
            for anomaly in anomalies:
                print(
                    "[perf-check]   slot_id={} capacity={} used={} 订单数={}".format(
                        *anomaly
                    )
                )
        else:
            print("[perf-check] 全库扫描：没有 used > capacity / 库存与订单对不上的时段")

        total_slots = (
            await conn.execute(
                text("SELECT count(*), sum(capacity), sum(used) FROM schedule_slot")
            )
        ).one()
        total_orders = (
            await conn.execute(text('SELECT count(*) FROM "order"'))
        ).scalar_one()

    print(
        "[perf-check] 压测库 {}：时段 {} 格，总容量 {}，已用 {}，订单总数 {}".format(
            db_name, total_slots[0], total_slots[1], total_slots[2], total_orders
        )
    )
    print("[perf-check] 超卖：{}".format("是（有异常）" if oversold else "否"))
    return 1 if oversold else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
