"""超时自动确认任务（独立可执行入口）。

用法::

    cd apps/api && python -m app.scripts.auto_confirm_job

**不加 APScheduler / Celery**：调度方式留给部署卡决定（cron、k8s CronJob
或其他都行）。本脚本只负责「跑一轮」，跑完就退出——被调度器反复拉起即可，
幂等由 service 保证（已确认的订单不会被再次确认）。

退出码：0 = 正常跑完；非 0 = 脚本本身出了问题（比如数据库连不上），
调度器据此告警。单个订单确认失败不算脚本失败——那属于业务数据问题，
service 会记日志后继续。
"""
from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.core.database import session_factory
from app.services.auto_confirm import auto_confirm_expired

__all__ = ["main", "run_once"]

logger = logging.getLogger(__name__)


async def run_once(threshold_hours: int | None = None) -> int:
    """跑一轮自动确认，返回本次确认的笔数。

    ``threshold_hours`` 为 None 时取配置项 ``auto_confirm_threshold_hours``
    （默认 24 小时）——阈值不硬编码在代码里。
    """
    hours = (
        threshold_hours
        if threshold_hours is not None
        else settings.auto_confirm_threshold_hours
    )
    async with session_factory() as session:
        return await auto_confirm_expired(session, threshold_hours=hours)


def main() -> int:
    """脚本入口。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    threshold = settings.auto_confirm_threshold_hours
    count = asyncio.run(run_once(threshold_hours=threshold))
    logger.info(
        "超时自动确认任务结束：确认 %d 笔（阈值 %d 小时）", count, threshold
    )
    # 往 stdout 也打一行：cron 的输出会进邮件/日志，留个抓手
    print("超时自动确认：确认 {} 笔（阈值 {} 小时）".format(count, threshold))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
