"""师傅管理 service 的单元测试（不碰数据库）。

盯的是**接口层挡不住的那一层**：请求体用窄枚举（SettableMasterStatus）
把 PENDING 变成 422，但 service 也会被直接调用（测试、将来的别的入口），
那时类型提示挡不住运行时传错值——``MasterStatus.PENDING`` 照样能传进来。

所以 service 里必须再挡一次：不合法的状态连库都不碰。
"""
from __future__ import annotations

import pytest

from app.core.auth import CurrentUser
from app.models.enums import MasterStatus, SettableMasterStatus, UserRole
from app.services.errors import MasterStatusNotSettableError
from app.services.master_management import update_master_status


class _ExplodingSession:
    """一碰就炸的 session 替身。

    用来证明两件事：

    - 状态不合法时，service **连数据库都没碰**（不该碰）；
    - 状态合法时，service 确实往下走了（守卫没写太紧）。
    """

    def __getattr__(self, name: str):
        raise AssertionError("不该碰数据库，却访问了 session.{}".format(name))


def _current_user() -> CurrentUser:
    return CurrentUser(user_id=1, role=UserRole.PROVIDER_ADMIN, provider_id=1)


async def test_service_rejects_pending_status() -> None:
    """service 直调时传 MasterStatus.PENDING -> 业务异常。

    类型签名声明的是 SettableMasterStatus，但运行时传进来的是
    MasterStatus.PENDING——这正是「类型提示挡不住」的那种情况，
    service 必须自己认出来。
    """
    with pytest.raises(MasterStatusNotSettableError) as excinfo:
        await update_master_status(
            _ExplodingSession(),  # 守卫在碰库之前就抛了，这里不需要真 session
            master_id=1,
            status=MasterStatus.PENDING,
            current_user=_current_user(),
        )
    assert "PENDING" in str(excinfo.value)


async def test_service_rejects_unknown_status_value() -> None:
    """压根不存在的状态值 -> 同样是业务异常（不是 500）。"""
    with pytest.raises(MasterStatusNotSettableError):
        await update_master_status(
            _ExplodingSession(),
            master_id=1,
            status="NOT_A_STATUS",  # type: ignore[arg-type]
            current_user=_current_user(),
        )


async def test_service_accepts_every_settable_status() -> None:
    """可设置的那几个状态一个都不该被误伤（守卫别写太紧）。

    守卫放行之后会走到事务那一步，撞上假 session 的 AssertionError——
    看到它就说明状态没被守卫拦下。
    """
    for status in SettableMasterStatus:
        with pytest.raises(AssertionError, match="session"):
            await update_master_status(
                _ExplodingSession(),
                master_id=1,
                status=status,
                current_user=_current_user(),
            )
