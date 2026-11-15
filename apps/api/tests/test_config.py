"""配置层的启动期校验（app/core/config.py）。

重点盯一条：**非 dev 环境不许用占位短信验证码**。

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
