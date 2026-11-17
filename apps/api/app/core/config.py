"""应用配置：统一从仓库根目录的 .env 读取。

根目录 .env 由 `cp .env.example .env` 生成，不入库。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Self
from zoneinfo import ZoneInfo

from pydantic import field_validator, model_validator
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

# 「还没填」的占位标记。
#
# .env.example 里所有待填的位置都写着 REPLACE_WITH_...；照抄成 .env
# 又忘了改，就等于把「待填」的值带上线。CHANGE_ME 是同一类约定，一并拦。
#
# 拦在启动期：应用宁可起不来，也不要带着占位值跑起来——
# 那样出了问题没人知道是配置没填。
PLACEHOLDER_MARKERS = ("REPLACE_WITH", "CHANGE_ME")

# .env.example 里 DATABASE_URL 这类值用的是尖括号写法：
#   postgresql+asyncpg://<user>:<password>@<host>:5432/<db>
# 这类不写 REPLACE_WITH，光靠标记拦不住。
#
# 只认这几个「一看就是占位」的词：真密码里带尖括号（a<b）不是没有可能，
# 但 <user> / <password> 这种不会出现在真实配置里。
PLACEHOLDER_ANGLE_RE = re.compile(
    r"<(?:user|password|passwd|pwd|host|hostname|port|db|database|secret|key|token)>",
    re.IGNORECASE,
)

# 整串就是这些值的，也是占位值（dev 的默认短信码 123456 就是这种）。
#
# 只比「整串相等」，不做子串匹配：JWT 密钥、库密码里偶然出现 123456
# 是正常的随机串的一部分，不该被当成占位值。
PLACEHOLDER_LITERAL_VALUES = (DEV_LOGIN_SMS_CODE,)


def placeholder_reason(value: str) -> str | None:
    """这个配置值是不是占位值？是的话返回一句话理由，不是返回 None。

    给启动期校验和 JWT 长度校验共用一份判定，免得两处口径不一样。
    """
    for marker in PLACEHOLDER_MARKERS:
        if marker in value:
            return "含占位标记 {}".format(marker)
    if PLACEHOLDER_ANGLE_RE.search(value):
        return "含尖括号占位"
    if value in PLACEHOLDER_LITERAL_VALUES:
        return "还是占位值 {}".format(value)
    return None


class Settings(BaseSettings):
    """从环境变量 / 根目录 .env 读取的配置项。"""

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # 报错时不回显输入值。
        #
        # pydantic 默认会把「这次校验拿到的全部输入」拼进错误信息，
        # 这里面的 DATABASE_URL 带库密码、JWT_SECRET 带密钥——
        # 启动失败打一行日志，等于把生产密钥写进日志文件。
        # 隐藏输入值后错误信息只剩我们自己写的那句话（点名是哪个变量坏了）。
        hide_input_in_errors=True,
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

    # 业务时区：所有「业务日期」都按它算——今天是哪天、下单时段是不是还在
    # 将来、超时自动确认的 N 小时从哪一刻起算、T+1 结算的「满一天」。
    #
    # 默认 Asia/Shanghai：面向国内用户。存库时间戳仍是 UTC（timestamptz），
    # 只在「取业务日期」的那一处换算（见 app/core/timezone.py）。
    timezone: str = "Asia/Shanghai"

    @model_validator(mode="after")
    def _check_no_placeholder_values(self) -> Self:
        """生产环境不许带着占位值启动。

        拦的是「.env 没填完就上线」：里面还留着 REPLACE_WITH_...、
        CHANGE_ME_...、<user> 这类尖括号写法，或者短信验证码还是 dev 的 123456。

        为什么用 model_validator(mode="after") 而不是字段校验器：
        - 要拿到**最终值**：环境里没配的字段取的是代码里的默认值
          （例如 LOGIN_SMS_CODE 的默认值 123456），默认值得一并扫。
        - 要**一次列出所有**占位项：字段校验器逐个字段跑，
          第一个不合法就抛，后面的字段根本看不到——
          运维得改一个、重启一次、再改下一个。这里一行日志就能照着改完。

        为什么只在非 dev 环境拦：本地开发就是要能拿占位值跑起来
        （同 _check_login_sms_code 的口径）。
        """
        app_env = self.app_env.strip().lower()
        if app_env == "dev":
            return self

        offenders: list[str] = []
        for name, value in self:
            if not isinstance(value, str) or not value:
                continue
            reason = placeholder_reason(value)
            if reason is not None:
                # 只报**字段名和原因**，不报值本身：值可能是密钥。
                offenders.append("{}（{}）".format(name.upper(), reason))

        if offenders:
            raise ValueError(
                "APP_ENV={} 时以下配置项还是占位值，拒绝启动：{}。"
                "请按 .env.example 逐项替换成真实值"
                "（清单见 docs/PRODUCTION_CHECKLIST.md）。".format(
                    app_env, "；".join(offenders)
                )
            )
        return self

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, value: str) -> str:
        """时区名必须是系统认识的，否则拒绝启动。

        时区名写错（比如 "Asia/ShangHai"）如果放到运行时才发现，
        报出来的是 zoneinfo 的 KeyError，看不出是哪个配置项坏了。
        所以在配置阶段就拒。
        """
        name = (value or "").strip()
        if not name:
            raise ValueError("TIMEZONE 不能为空。")
        try:
            ZoneInfo(name)
        except Exception as exc:  # noqa: BLE001 - 任何解析失败都是「不是合法时区名」
            raise ValueError(
                "TIMEZONE={} 不是合法的时区名：{}".format(name, exc)
            )
        return name

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

        dev 也一样卡：占位密钥（.env.example 那串）本来就够长，
        短的是「自己配小了」，那在任何环境都不该放行。
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
