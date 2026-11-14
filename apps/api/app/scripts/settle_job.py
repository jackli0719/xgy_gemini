"""T+1 待结算生成任务（独立可执行入口）。

用法::

    cd apps/api && python -m app.scripts.settle_job

**不加 APScheduler / Celery**：调度方式留给部署卡决定（cron、k8s CronJob
或其他都行）。本脚本只负责「跑一轮」，跑完就退出——被调度器反复拉起即可，
幂等由 service 保证（已转成「待结算」的订单不会被再次结算）。

退出码：0 = 正常跑完；非 0 = 脚本本身出了问题（比如数据库连不上），
调度器据此告警。单个服务商结算失败不算脚本失败——那属于业务数据问题，
service 会记日志后继续。
"""
from __future__ import annotations

import asyncio
import logging

from app.core.database import session_factory
from app.services.settle import generate_pending_settlements

__all__ = ["main", "run_once"]

logger = logging.getLogger(__name__)


async def run_once() -> int:
    """跑一轮待结算生成，返回本次转成「待结算」的订单笔数。"""
    async with session_factory() as session:
        return await generate_pending_settlements(session)


def main() -> int:
    """脚本入口。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    count = asyncio.run(run_once())
    logger.info("待结算生成任务结束：转 %d 笔订单为待结算", count)
    # 往 stdout 也打一行：cron 的输出会进邮件/日志，留个抓手
    print("待结算生成：转 {} 笔订单为待结算".format(count))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
