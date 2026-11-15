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

# dev 环境允许使用的占位短信验证码。
#
# 非 dev 环境用它（或者任何空值 / 短码）一律拒绝启动——
# 见 Settings._check_login_sms_code。
DEV_LOGIN_SMS_CODE = "123456"

# 非 dev 环境下验证码的最短长度。
# 8 位是「猜不出来」的最低门槛：再短就基本等于没设。
MIN_LOGIN_SMS_CODE_LENGTH = 8


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

    # 登录验证码。
    #
    # **MVP 占位**：不接短信网关，所有手机号都用这一个固定验证码登录。
    # 接真实短信时把 service 里的比对换成「查短信记录 + 校验有效期 + 一次性作废」，
    # 这个配置项就退休了。
    #
    # 非 dev 环境**必须**换成足够长的随机值：占位值（123456）、空值、
    # 短于 8 位的码都会让应用在启动阶段直接拒绝启动
    # （见下面的 _check_login_sms_code）——
    # 留着占位值就等于任何人都能用 123456 登录生产库。
    login_sms_code: str = DEV_LOGIN_SMS_CODE

    # 超时自动确认：订单停在「待确认」超过这个小时数就由系统自动确认
    # （见 app/services/auto_confirm.py）。0 或负数会让「立刻全部确认」，
    # 配置阶段直接拒绝。
    auto_confirm_threshold_hours: int = 24

    @field_validator("auto_confirm_threshold_hours")
    @classmethod
    def _check_auto_confirm_threshold(cls, value: int) -> int:
        """阈值必须是正整数，否则拒绝启动。"""
        if value <= 0:
            raise ValueError(
                "AUTO_CONFIRM_THRESHOLD_HOURS 必须为正整数，当前 {}。".format(value)
                + "阈值非正会让所有「待确认」订单被立刻自动确认。"
            )
        return value

    @field_validator("login_sms_code")
    @classmethod
    def _check_login_sms_code(cls, value: str, info) -> str:
        """非 dev 环境不许用占位短信验证码。

        跟 jwt_secret 的校验是同一个思路：**配置阶段就拒绝启动**，
        而不是等有人拿 123456 登录了生产库才发现。

        三种情况直接拒绝启动：值为空、值是占位码 123456、长度短于 8 位。

        依赖字段声明顺序：app_env 必须声明在 login_sms_code 之前，
        校验器才拿得到 app_env 的值（info.data 里是「已校验过的字段」）。
        这条依赖由 apps/api/tests/test_config.py 盯着。
        """
        app_env = info.data.get("app_env", "")
        if app_env.strip().lower() == "dev":
            # dev：空值等于「没设」，用占位码顶上；显式设了就用设的
            return value or DEV_LOGIN_SMS_CODE
        if not value:
            raise ValueError(
                "LOGIN_SMS_CODE 在非 dev 环境必须设置（不能为空）。"
                "生成命令：python -c \"import secrets; print(secrets.token_urlsafe(12))\""
            )
        if value == DEV_LOGIN_SMS_CODE:
            raise ValueError(
                "LOGIN_SMS_CODE 在非 dev 环境不能是占位值 {}——"
                "那等于任何人都能用这个码登录。"
                "生成命令：python -c \"import secrets; print(secrets.token_urlsafe(12))\"".format(
                    DEV_LOGIN_SMS_CODE
                )
            )
        if len(value) < MIN_LOGIN_SMS_CODE_LENGTH:
            raise ValueError(
                "LOGIN_SMS_CODE 在非 dev 环境至少要 {} 位，当前 {} 位。"
                "生成命令：python -c \"import secrets; print(secrets.token_urlsafe(12))\"".format(
                    MIN_LOGIN_SMS_CODE_LENGTH, len(value)
                )
            )
        return value

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
