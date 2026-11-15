"""师傅端查询 service 的单元测试（不碰数据库）。

盯的是**接口层挡不住的那一层**：查询参数用窄枚举（MasterOrderStatus）
把别的状态变成 422，但 service 也会被直接调用（测试、将来的别的入口），
那时类型提示挡不住运行时传错值——``OrderStatus.COMPLETED`` 照样能传进来。

所以 service 里必须再挡一次：不合法的状态连库都不碰。

（与 app.services.master_management 的 _SETTABLE_STATUS_VALUES 同一套写法。）
"""
from __future__ import annotations

import pytest

from app.models.enums import MasterOrderStatus, OrderStatus
from app.services.errors import MasterOrderStatusNotAllowedError
from app.services.master_queries import list_master_orders


class _ExplodingSession:
    """一碰就炸的 session 替身。

    用来证明两件事：

    - 状态不合法时，service **连数据库都没碰**（不该碰）；
    - 状态合法时，service 确实往下走了（守卫没写太紧）。
    """

    def __getattr__(self, name: str):
        raise AssertionError("不该碰数据库，却访问了 session.{}".format(name))


async def test_service_rejects_status_outside_the_three() -> None:
    """service 直调时传 OrderStatus.COMPLETED -> 业务异常。

    类型签名声明的是 MasterOrderStatus，但运行时传进来的是
    OrderStatus.COMPLETED——这正是「类型提示挡不住」的那种情况，
    service 必须自己认出来。

    不挡的后果不是报错，而是**更宽的查询**：师傅会拿到一批
    「已完成」的单，而师傅端的工作队列只有三组。
    """
    with pytest.raises(MasterOrderStatusNotAllowedError) as excinfo:
        await list_master_orders(
            _ExplodingSession(),  # 守卫在碰库之前就抛了，这里不需要真 session
            master_id=1,
            status=OrderStatus.COMPLETED,
        )
    assert "COMPLETED" in str(excinfo.value)


async def test_service_rejects_unknown_status_value() -> None:
    """压根不存在的状态值 -> 同样是业务异常（不是 500 的 AttributeError）。"""
    with pytest.raises(MasterOrderStatusNotAllowedError):
        await list_master_orders(
            _ExplodingSession(),
            master_id=1,
            status="NOT_A_STATUS",  # type: ignore[arg-type]
        )


async def test_service_accepts_every_allowed_status() -> None:
    """可查的那三个状态一个都不该被误伤（守卫别写太紧）。

    守卫放行之后会走到查库那一步，撞上假 session 的 AssertionError——
    看到它就说明状态没被守卫拦下。
    """
    for status in MasterOrderStatus:
        with pytest.raises(AssertionError, match="session"):
            await list_master_orders(
                _ExplodingSession(),
                master_id=1,
                status=status,
            )


async def test_service_accepts_raw_string_of_allowed_status() -> None:
    """合法状态的裸字符串也放行（守卫认的是取值，不是类型）。"""
    with pytest.raises(AssertionError, match="session"):
        await list_master_orders(
            _ExplodingSession(),
            master_id=1,
            status="PENDING_ACCEPT",
        )
