"""配置层的启动期校验（app/core/config.py）。

重点盯两条：

1. **非 dev 环境不许用占位短信验证码**；
2. **非 dev 环境不许带着占位值启动**（REPLACE_WITH / CHANGE_ME /
   尖括号写法 / 默认的 123456）——.env 照抄 .env.example 又忘了改，
   就属于这种。

和 JWT_SECRET 的校验是同一个思路：配置阶段就拒绝启动，
而不是等有人拿 123456 登录了生产库才发现。

这里也是 ``login_sms_code`` 校验器依赖的那条字段声明顺序
（app_env 必须声明在 login_sms_code 之前，校验器才拿得到 app_env）
的守卫：顺序一旦被改坏，本文件的用例会先红。
"""
from __future__ import annotations

import pytest

from app.core.config import (
    DEV_LOGIN_SMS_CODE,
    MIN_LOGIN_SMS_CODE_LENGTH,
    Settings,
)

# 一条「能过长度校验但明显是占位」的密钥：
# 够长（>=32 字节），所以拦它的只能是占位值这条守卫，不是长度那条。
LONG_PLACEHOLDER_SECRET = "REPLACE_WITH_RANDOM_SECRET_AT_LEAST_32_BYTES_LONG"

# 一条明显是占位、但长度不够 32 字节的密钥（.env.example 抄错版本会这样）。
SHORT_PLACEHOLDER_SECRET = "REPLACE_WITH_xxx"

# 够长的真实密钥：非 dev 环境的「正常配置」基准值。
REAL_SECRET = "k3Qm8Zt0vXb7NwErYuIoPaSdFgHjKlZxCvBnM"


# =====================================================================
# 非 dev 环境：占位值 / 空值 / 短码一律拒绝启动
# =====================================================================


def test_non_dev_rejects_placeholder_code() -> None:
    """生产环境用 123456 -> 拒绝启动。"""
    with pytest.raises(ValueError):
        Settings(app_env="prod", login_sms_code=DEV_LOGIN_SMS_CODE)


def test_non_dev_rejects_empty_code() -> None:
    """生产环境没配验证码 -> 拒绝启动。"""
    with pytest.raises(ValueError):
        Settings(app_env="prod", login_sms_code="")


def test_non_dev_rejects_short_code() -> None:
    """生产环境配了但短于下限 -> 拒绝启动。"""
    with pytest.raises(ValueError):
        Settings(app_env="prod", login_sms_code="1" * (MIN_LOGIN_SMS_CODE_LENGTH - 1))


def test_non_dev_accepts_long_enough_code() -> None:
    """生产环境配了足够长的随机值 -> 放行。"""
    code = "aB3xY9zQ7mK2"
    settings = Settings(app_env="prod", login_sms_code=code)
    assert settings.login_sms_code == code


# =====================================================================
# dev 环境：占位值随便用
# =====================================================================


def test_dev_accepts_placeholder_code() -> None:
    """dev 用占位码 -> 放行（本地开发能跑起来）。"""
    settings = Settings(app_env="dev", login_sms_code=DEV_LOGIN_SMS_CODE)
    assert settings.login_sms_code == DEV_LOGIN_SMS_CODE


def test_dev_empty_code_falls_back_to_placeholder() -> None:
    """dev 里配了空值 -> 当成「没设」，用占位码顶上（.env.example 就是空占位）。"""
    settings = Settings(app_env="dev", login_sms_code="")
    assert settings.login_sms_code == DEV_LOGIN_SMS_CODE


def test_dev_accepts_custom_code() -> None:
    """dev 里显式配了别的码就用它。"""
    settings = Settings(app_env="dev", login_sms_code="654321")
    assert settings.login_sms_code == "654321"


# =====================================================================
# 非 dev 环境：占位值一律拒绝启动
#
# 拦的是「.env 照抄 .env.example 忘了改就上线」。
# 报错消息必须点名具体变量名——运维照着改，不用一行行猜。
# =====================================================================


def test_prod_rejects_placeholder_jwt_secret() -> None:
    """生产环境用占位 JWT_SECRET -> 拒绝启动，消息点名 JWT_SECRET。

    用**够长**的那串占位密钥：长度规则先过，占位规则才轮得到它——
    短占位密钥被长度规则拦下（见 test_short_placeholder_secret_error_has_no_value_echo）。
    """
    with pytest.raises(ValueError) as exc:
        Settings(
            app_env="prod",
            database_url="postgresql+asyncpg://u:p@localhost:5432/oto",
            jwt_secret=LONG_PLACEHOLDER_SECRET,
            login_sms_code="aB3xY9zQ7mK2",
        )
    message = str(exc.value)
    assert "JWT_SECRET" in message
    assert "REPLACE_WITH" in message


def test_prod_rejects_placeholder_sms_code() -> None:
    """生产环境用占位短信验证码 -> 拒绝启动，消息点名 LOGIN_SMS_CODE。"""
    with pytest.raises(ValueError) as exc:
        Settings(
            app_env="prod",
            database_url="postgresql+asyncpg://u:p@localhost:5432/oto",
            jwt_secret=REAL_SECRET,
            login_sms_code=DEV_LOGIN_SMS_CODE,
        )
    assert "LOGIN_SMS_CODE" in str(exc.value)


def test_prod_rejects_default_placeholder_code() -> None:
    """生产环境没配短信验证码 -> 取到的是代码里的默认占位码 123456，也得拒。

    拦的是「压根没写」这一种——不是值写错，是根本没写，
    取默认值就等于用了 123456。
    """
    with pytest.raises(ValueError) as exc:
        Settings(
            app_env="prod",
            database_url="postgresql+asyncpg://u:p@localhost:5432/oto",
            jwt_secret=REAL_SECRET,
        )
    assert "LOGIN_SMS_CODE" in str(exc.value)


def test_prod_rejects_change_me_marker() -> None:
    """CHANGE_ME 和 REPLACE_WITH 是同一类占位标记，一样拦。"""
    with pytest.raises(ValueError) as exc:
        Settings(
            app_env="prod",
            database_url="postgresql+asyncpg://CHANGE_ME@localhost:5432/oto",
            jwt_secret=REAL_SECRET,
            login_sms_code="aB3xY9zQ7mK2",
        )
    assert "DATABASE_URL" in str(exc.value)


def test_prod_rejects_angle_bracket_placeholder() -> None:
    """尖括号写法（.env.example 里的 <user> / <password>）也是占位值。"""
    with pytest.raises(ValueError) as exc:
        Settings(
            app_env="prod",
            database_url="postgresql+asyncpg://<user>:<password>@localhost:5432/oto",
            jwt_secret=REAL_SECRET,
            login_sms_code="aB3xY9zQ7mK2",
        )
    assert "DATABASE_URL" in str(exc.value)


def test_prod_lists_all_offenders_at_once() -> None:
    """多个占位项要一次全列出来。

    逐个报错的话，运维得改一个重启一次再来——白费一轮时间。
    """
    with pytest.raises(ValueError) as exc:
        Settings(
            app_env="prod",
            database_url="postgresql+asyncpg://<user>:<password>@localhost:5432/oto",
            jwt_secret=LONG_PLACEHOLDER_SECRET,
            login_sms_code="aB3xY9zQ7mK2",
        )
    message = str(exc.value)
    assert "JWT_SECRET" in message
    assert "DATABASE_URL" in message


def test_prod_error_message_does_not_leak_secret() -> None:
    """报错消息里不能出现密钥原文。

    pydantic 默认会把「这次校验拿到的全部输入」拼进错误信息，
    启动失败打一行日志 = 把生产密钥写进日志文件。
    """
    with pytest.raises(ValueError) as exc:
        Settings(
            app_env="prod",
            database_url="postgresql+asyncpg://u:p@localhost:5432/oto",
            jwt_secret="REPLACE_WITH_SUPERSECRET_VALUE",
            login_sms_code="aB3xY9zQ7mK2",
        )
    assert "SUPERSECRET" not in str(exc.value)


def test_prod_accepts_real_config() -> None:
    """都填成真实值 -> 放行。"""
    settings = Settings(
        app_env="prod",
        database_url="postgresql+asyncpg://u:p@localhost:5432/oto",
        jwt_secret=REAL_SECRET,
        login_sms_code="aB3xY9zQ7mK2",
    )
    assert settings.jwt_secret == REAL_SECRET


# =====================================================================
# dev 环境：占位值随便用（本地开发要能拿占位值跑起来）
# =====================================================================


def test_dev_accepts_placeholder_values() -> None:
    """dev 用占位值 -> 放行。

    占位密钥用的是 .env.example 里那串（够长，长度规则照样过）；
    短的占位串在 dev 也过不了长度规则——那条规则不在本卡的放宽范围内。
    """
    settings = Settings(
        app_env="dev",
        database_url="postgresql+asyncpg://u:p@localhost:5432/oto",
        jwt_secret=LONG_PLACEHOLDER_SECRET,
        login_sms_code=DEV_LOGIN_SMS_CODE,
    )
    assert settings.jwt_secret == LONG_PLACEHOLDER_SECRET
    assert settings.login_sms_code == DEV_LOGIN_SMS_CODE


def test_dev_still_rejects_short_real_secret() -> None:
    """dev 也拦「自己配了但太短」的真密钥——放行的是占位值，不是所有短串。"""
    with pytest.raises(ValueError):
        Settings(
            app_env="dev",
            database_url="postgresql+asyncpg://u:p@localhost:5432/oto",
            jwt_secret="too-short",
            login_sms_code=DEV_LOGIN_SMS_CODE,
        )


# =====================================================================
# 报错形态：ValidationError 是 ValueError 的子类
#
# 校验失败时 pydantic 抛的是 ValidationError。它继承自 ValueError，
# 所以「用 except ValueError 接住启动失败」这段代码是成立的。
# =====================================================================


def test_validation_error_is_value_error_subclass() -> None:
    """ValidationError 继承 ValueError —— 调用方按 ValueError 接就够。"""
    from pydantic import ValidationError

    assert issubclass(ValidationError, ValueError)
    with pytest.raises(ValueError) as exc:
        Settings(
            app_env="prod",
            database_url="postgresql+asyncpg://u:p@localhost:5432/oto",
            jwt_secret=LONG_PLACEHOLDER_SECRET,
            login_sms_code="aB3xY9zQ7mK2",
        )
    assert isinstance(exc.value, ValidationError)


def test_short_placeholder_secret_error_has_no_value_echo() -> None:
    """短的占位密钥：报错里也不该出现密钥原文。

    hide_input_in_errors 打开后，pydantic 不再把输入值拼进错误消息——
    否则启动失败那一行日志就是一行明文密钥。
    """
    with pytest.raises(ValueError) as exc:
        Settings(
            app_env="prod",
            database_url="postgresql+asyncpg://u:p@localhost:5432/oto",
            jwt_secret=SHORT_PLACEHOLDER_SECRET,
            login_sms_code="aB3xY9zQ7mK2",
        )
    message = str(exc.value)
    assert "REPLACE_WITH_xxx" not in message
    assert "JWT_SECRET" in message
