"""可独立执行的任务脚本（定时任务入口等）。

这些脚本不依赖 FastAPI，用 ``python -m app.scripts.<名字>`` 直接跑，
由 cron / k8s CronJob 之类的调度器拉起。调度方式由部署卡决定，
脚本本身只管「跑一次」。
"""
