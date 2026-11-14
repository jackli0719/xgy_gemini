"""应用配置：统一从仓库根目录的 .env 读取。

根目录 .env 由 `cp .env.example .env` 生成，不入库。
"""
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/api/app/core/config.py -> 上溯 4 层到仓库根目录
ROOT_DIR = Path(__file__).resolve().parents[4]

# RFC 7518 §3.2：HS256 的 HMAC 密钥至少 32 字节。低于这个长度，PyJWT 会发
# InsecureKeyLengthWarning——警告没人看，硬编码进仓库的短密钥会被当成"没出事"。
# 所以在配置层直接拒绝启动。
JWT_SECRET_MIN_BYTES = 32


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

    # 应用环境：dev / prod / staging。
    # 决定开发专用接口（如 app/api/v1/pay.py 的 mock 支付回调）是否开放。
    # 默认按生产对待（fail-closed）：没显式配 APP_ENV 时，mock 接口是关的。
    app_env: str = "prod"

    # JWT：鉴权依赖（app.core.auth）用这组配置验签
    jwt_secret: str
    jwt_alg: str = "HS256"
    jwt_access_expire_minutes: int = 120

    @field_validator("jwt_secret")
    @classmethod
    def _check_jwt_secret_length(cls, value: str) -> str:
        """密钥太短 -> 启动失败，不等到运行时才报警。

        校验的是字节长度不是字符数：非 ASCII 字符一个顶多个字节。
        """
        length = len(value.encode("utf-8"))
        if length < JWT_SECRET_MIN_BYTES:
            raise ValueError(
                "JWT_SECRET 至少 32 字节（RFC 7518 HS256），当前 {} 字节。"
                "生成命令：python -c \"import secrets; print(secrets.token_urlsafe(32))\"".format(
                    length
                )
            )
        return value


settings = Settings()
