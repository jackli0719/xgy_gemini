#!/usr/bin/env python3
"""压测种子数据。

在**独立压测库** ``oto_perf`` 里种一套压测要用的数据：

- 1 个服务商（ACTIVE）
- 1 个服务商管理员
- 5 个师傅（ACTIVE）
- 1 个品类 + 10 个服务项
- 每个服务项 100 个时段（10 天 x 10 格），每格容量 5
- N 个压测客户（每人 1 个地址），N 默认 600

跑法（在压测栈的 api 容器里）::

    docker compose -f perf/compose.yaml exec api python /app/perf/seed.py

**安全闸**：脚本只允许跑在**库名以 ``_perf`` 结尾**的数据库上。
开发库（oto）、测试库（oto_test）都会让脚本直接退出，
所以「不碰开发库和测试库」这条约束不靠人的自觉，靠代码。

脚本是**幂等**的：每次先 TRUNCATE 再重种，重复跑不会叠加数据。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import time, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

# 容器里 app 包在 /app/apps/api（WORKDIR），但脚本在 /app/perf，
# 所以先把 app 目录塞进 sys.path，再 import app.*
APP_DIR = os.environ.get("OTO_API_DIR", "/app/apps/api")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from sqlalchemy import text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import engine, session_factory  # noqa: E402
from app.core.timezone import today  # noqa: E402
from app.models.address import Address  # noqa: E402
from app.models.catalog import ServiceCategory, ServiceItem  # noqa: E402
from app.models.enums import (  # noqa: E402
    CatalogStatus,
    MasterStatus,
    ProviderStatus,
    UserRole,
    UserStatus,
)
from app.models.provider import Master, ServiceProvider  # noqa: E402
from app.models.schedule_slot import ScheduleSlot  # noqa: E402
from app.models.user import User  # noqa: E402

# ---- 种子规模（可用环境变量覆盖）--------------------------------------
PROVIDER_NAME = os.environ.get("PERF_PROVIDER_NAME", "压测服务商")
PROVIDER_PHONE = os.environ.get("PERF_PROVIDER_PHONE", "13900000000")
CATEGORY_NAME = os.environ.get("PERF_CATEGORY_NAME", "压测品类")

MASTER_COUNT = int(os.environ.get("PERF_MASTERS", "5"))
ITEM_COUNT = int(os.environ.get("PERF_ITEMS", "10"))
SLOTS_PER_ITEM = int(os.environ.get("PERF_SLOTS_PER_ITEM", "100"))
# 每格时段库存：竞态测试要「100 人抢 5 格」，所以默认容量就是 5
SLOT_CAPACITY = int(os.environ.get("PERF_SLOT_CAPACITY", "5"))
CUSTOMER_COUNT = int(os.environ.get("PERF_CUSTOMERS", "600"))

# 一个时段占一小时，从 08:00 排到 17:00（10 格 / 天）
SLOT_HOURS = 10
FIRST_SLOT_HOUR = 8
# 时段铺在今天之后的 10 天上（时段必须在将来才能下单）
SLOT_DAYS = 10

# 要清空的表。顺序无所谓，靠 CASCADE 处理外键；
# RESTART IDENTITY 让自增序列也归零，id 从 1 开始（manifest 里写死 id，k6 直接用）
TRUNCATE_TABLES = (
    '"order"',
    "order_status_log",
    "schedule_slot",
    "address",
    "service_item",
    "service_category",
    "master",
    '"user"',
    "service_provider",
)

MANIFEST_PATH = Path(__file__).resolve().parent / "manifest.json"


def _db_name(url: str) -> str:
    """从 DATABASE_URL 里取库名。"""
    return urlsplit(url).path.lstrip("/").split("?")[0]


def _guard_perf_database(url: str) -> str:
    """库名不是 ``*_perf`` 就拒绝执行。

    这是「不碰开发库和测试库」的最后一道闸：
    脚本被误用在开发栈里时，它会拒绝，而不是把开发数据清掉。
    """
    name = _db_name(url)
    if not name.endswith("_perf"):
        raise SystemExit(
            "拒绝执行：当前 DATABASE_URL 指向的库是 {!r}，不是压测库。"
            "压测种子只允许跑在库名以 _perf 结尾的库上（如 oto_perf）。".format(name)
        )
    return name


async def _truncate(session) -> None:
    await session.execute(
        text("TRUNCATE TABLE {} RESTART IDENTITY CASCADE".format(", ".join(TRUNCATE_TABLES)))
    )
    await session.commit()


async def seed() -> dict:
    """种数据并写 manifest。返回 manifest 内容。"""
    db_name = _guard_perf_database(settings.database_url)

    async with session_factory() as session:
        await _truncate(session)

        # ---- 服务商 + 管理员 -------------------------------------------
        provider = ServiceProvider(
            name=PROVIDER_NAME,
            contact_phone=PROVIDER_PHONE,
            status=ProviderStatus.ACTIVE,
            commission_rate=Decimal("0.1000"),
        )
        session.add(provider)
        await session.flush()

        admin_user = User(
            phone="19990000001",
            nickname="压测管理员",
            status=UserStatus.ACTIVE,
            role=UserRole.PROVIDER_ADMIN,
            provider_id=provider.id,
        )
        session.add(admin_user)

        # ---- 5 个师傅 --------------------------------------------------
        # 师傅的归属权威来源是 master 表；user.provider_id 留空
        # （库里 ck_user_role_provider 约束：只有 PROVIDER_* 角色能带 provider_id）
        masters = []
        for i in range(1, MASTER_COUNT + 1):
            user = User(
                phone="1999000{:04d}".format(i + 1),
                nickname="压测师傅{}".format(i),
                status=UserStatus.ACTIVE,
                role=UserRole.MASTER,
                provider_id=None,
            )
            session.add(user)
            await session.flush()
            master = Master(
                provider_id=provider.id,
                user_id=user.id,
                real_name="压测师傅{}".format(i),
                status=MasterStatus.ACTIVE,
                rating=Decimal("5.0"),
            )
            session.add(master)
            await session.flush()
            masters.append({"master_id": master.id, "user_id": user.id})

        # ---- 品类 + 服务项 ---------------------------------------------
        category = ServiceCategory(
            name=CATEGORY_NAME,
            parent_id=None,
            status=CatalogStatus.ACTIVE,
            sort_order=0,
        )
        session.add(category)
        await session.flush()

        items = []
        for i in range(1, ITEM_COUNT + 1):
            item = ServiceItem(
                category_id=category.id,
                name="压测服务项{}".format(i),
                base_price=Decimal("100.00") + Decimal(i),
                duration_min=60,
                status=CatalogStatus.ACTIVE,
            )
            session.add(item)
            await session.flush()
            items.append(item)

        # ---- 时段：每项 100 格（10 天 x 10 格）--------------------------
        first_day = today() + timedelta(days=1)
        slots = []
        for item in items:
            per_day = max(1, SLOTS_PER_ITEM // SLOT_DAYS)
            for day_offset in range(SLOT_DAYS):
                day = first_day + timedelta(days=day_offset)
                for h in range(per_day):
                    start = time(FIRST_SLOT_HOUR + h, 0)
                    end = time(FIRST_SLOT_HOUR + h + 1, 0)
                    slot = ScheduleSlot(
                        item_id=item.id,
                        date=day,
                        start_time=start,
                        end_time=end,
                        capacity=SLOT_CAPACITY,
                        used=0,
                    )
                    session.add(slot)
                    await session.flush()
                    slots.append(slot)

        # ---- 压测客户 + 地址 --------------------------------------------
        customers = []
        for i in range(1, CUSTOMER_COUNT + 1):
            phone = "199{:08d}".format(i)
            user = User(
                phone=phone,
                nickname="压测客户{}".format(i),
                status=UserStatus.ACTIVE,
                role=UserRole.USER,
                provider_id=None,
            )
            session.add(user)
            await session.flush()
            address = Address(
                user_id=user.id,
                contact="压测客户{}".format(i),
                phone=phone,
                region="上海市浦东新区",
                detail="压测路{}号".format(i),
                is_default=True,
            )
            session.add(address)
            await session.flush()
            customers.append(
                {"index": i - 1, "phone": phone, "address_id": address.id}
            )

        await session.commit()

    # ---- manifest：种子与 k6 之间的契约 --------------------------------
    # 竞态时段取第 1 个服务项的第 1 格；负载池把这一格排除在外，
    # 两组压测互不干扰（否则负载测试会先把库存吃掉，竞态测试就抢不满了）
    race_slot = slots[0]
    load_slots = [
        {"item_id": s.item_id, "slot_id": s.id}
        for s in slots
        if s.id != race_slot.id
    ]

    manifest = {
        "db": db_name,
        "generated_at": today().isoformat(),
        "sms_code": os.environ.get("PERF_SMS_CODE", "123456"),
        "slot_capacity": SLOT_CAPACITY,
        "race": {
            "item_id": race_slot.item_id,
            "slot_id": race_slot.id,
            "capacity": race_slot.capacity,
            "date": race_slot.date.isoformat(),
            "start_time": race_slot.start_time.strftime("%H:%M"),
        },
        "load_slots": load_slots,
        "customers": customers,
        "counts": {
            "providers": 1,
            "admins": 1,
            "masters": MASTER_COUNT,
            "items": ITEM_COUNT,
            "slots_per_item": SLOTS_PER_ITEM,
            "slots_total": len(slots),
            "customers": len(customers),
        },
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


async def main() -> None:
    manifest = await seed()
    counts = manifest["counts"]
    print("[perf-seed] 已写入压测库 {}".format(manifest["db"]))
    print(
        "[perf-seed] 服务商 {} / 管理员 1 / 师傅 {} / 服务项 {} / 时段 {}（每项 {}）/ 客户 {}".format(
            counts["providers"],
            counts["masters"],
            counts["items"],
            counts["slots_total"],
            counts["slots_per_item"],
            counts["customers"],
        )
    )
    print(
        "[perf-seed] 竞态时段 slot_id={}（容量 {}），负载池时段 {} 个".format(
            manifest["race"]["slot_id"],
            manifest["race"]["capacity"],
            len(manifest["load_slots"]),
        )
    )
    print("[perf-seed] manifest: {}".format(MANIFEST_PATH))


if __name__ == "__main__":
    asyncio.run(main())
