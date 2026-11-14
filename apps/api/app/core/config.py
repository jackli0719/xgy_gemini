"""应用配置：统一从仓库根目录的 .env 读取。

根目录 .env 由 `cp .env.example .env` 生成，不入库。
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/api/app/core/config.py -> 上溯 4 层到仓库根目录
ROOT_DIR = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    """从环境变量 / 根目录 .env 读取的配置项。"""

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    db_echo: bool = False
    db_pool_size: int = 10


settings = Settings()
