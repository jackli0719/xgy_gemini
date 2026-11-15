"""下单 / 派单 service 的业务异常。

这些异常表达「客户端输入或服务端数据不满足业务前置条件」，
由 API 层统一映射成 4xx。

领域层已有的异常（app.domain.slot_rule 的 SlotError 树）不重复定义，
下单 service 直接复用，避免同一个语义出现两套类型。
"""
from __future__ import annotations

__all__ = [
    "AddressInUseError",
    "AddressNotFoundError",
    "CatalogError",
    "CatalogNotFoundError",
    "DispatchError",
    "DispatchForbiddenError",
    "InvalidOrderStateError",
    "ItemInactiveError",
    "ItemNotFoundError",
    "MasterActionError",
    "MasterActionForbiddenError",
    "MasterActionInvariantError",
    "MasterNotDispatchableError",
    "MasterNotFoundError",
    "MasterOrderStatusNotAllowedError",
    "MasterQueryError",
    "MasterQueryForbiddenError",
    "MasterStatusNotSettableError",
    "OrderNoConflictError",
    "OrderNotFoundError",
    "PlaceOrderError",
    "ServiceFlowError",
    "ServiceFlowForbiddenError",
    "ServiceFlowInvariantError",
    "SettlementError",
    "SettlementForbiddenError",
    "SettlementInvariantError",
    "SettlementNotFoundError",
    "SlotItemMismatchError",
    "SlotNotFoundError",
    "SlotNotInFutureError",
]


class PlaceOrderError(Exception):
    """下单失败的业务异常基类。"""


class AddressNotFoundError(PlaceOrderError):
    """地址不存在，或不属于当前用户。

    「不存在」与「不属于你」共用同一个异常，消息也不含归属信息——
    否则调用方可以用两者的错误差异探测他人资源是否存在（R5 越权）。

    地址管理（增删改查）链路也复用它：那条链路要的正是这个语义。
    """


class AddressInUseError(PlaceOrderError):
    """地址已被订单引用，不能删除。

    order.address_id 上是 RESTRICT 外键：地址一旦被订单引用，
    删掉它订单就指不回地址了（表里没有地址快照列）。
    数据库会挡下这次删除，这里把外键冲突翻译成 409——
    「换个地址 / 先处理订单再来」是可行的应对，500 不是。
    """


class ItemNotFoundError(PlaceOrderError):
    """服务项不存在。"""


class ItemInactiveError(PlaceOrderError):
    """服务项已停用，不能下单。"""


class SlotNotFoundError(PlaceOrderError):
    """预约时段不存在。"""


class SlotItemMismatchError(PlaceOrderError):
    """预约时段不属于所选服务项。"""


class SlotNotInFutureError(PlaceOrderError):
    """预约时段不是未来时间，不能下单。"""


class OrderNoConflictError(PlaceOrderError):
    """订单号连续冲突，重试上限内仍未拿到可用订单号。"""


class OrderNotFoundError(PlaceOrderError):
    """订单不存在。"""


class InvalidOrderStateError(PlaceOrderError):
    """订单当前状态不允许该操作。

    例如订单已经不是「待支付」，却收到支付回调。
    """


class DispatchError(Exception):
    """派单失败的业务异常基类。

    与 ``PlaceOrderError`` 平级而不是它的子类：派单与下单是两条链路，
    共用一个基类会让「下单失败」的兜底文案套到派单错误上。

    这棵树现在也承载**服务商侧师傅管理**（app.services.master_management）
    与**师傅自助接单**（app.services.master_action）两条链路：
    它们判的是同一件事——「这个师傅在不在本商作用域内、他能不能接单」，
    共用同一套异常与文案，免得同一个错误在两个接口里长得不一样。
    """


class MasterNotFoundError(DispatchError):
    """师傅不存在，或不属于当前服务商。

    「不存在」与「属于别的服务商」共用同一个异常、同一句话——
    否则调用方能靠报错差异探测别家师傅是否存在（R1 租户隔离）。
    """


class MasterNotDispatchableError(DispatchError):
    """师傅当前不可接单（停用 / 休假 / 未审核）。

    派单与师傅自助接单共用这一条：服务商把师傅停用之后，
    派单那头派不到他，他自己这头也接不了——同一个错误、同一句话。

    归属校验先于状态校验：别家的师傅永远是 404（不泄露存在性），
    本商但不可接单的师傅才是 409——「换个师傅派」是可行的应对。
    """


class MasterStatusNotSettableError(DispatchError):
    """这个师傅状态不允许被设置。

    服务商只能把师傅置为 ACTIVE / ON_LEAVE / DISABLED；
    PENDING（待审核）是入驻流程的初始状态，服务商改不回去。
    接口层用窄枚举挡过一次（PENDING -> 422），service 这边再挡一次：
    类型提示挡不住运行时传错值。
    """


class DispatchForbiddenError(DispatchError):
    """当前账号没有派单权限。

    典型场景：token 里没有服务商归属（provider_id 为空），
    或者角色不是服务商侧角色。这种情况连订单都查不到就该被挡住。
    """


class MasterActionError(Exception):
    """师傅接单 / 拒单失败的业务异常基类。

    与 ``PlaceOrderError`` / ``DispatchError`` 平级：三条链路各有一棵异常树，
    共用一个基类会让「下单失败」的兜底文案套到派单、接单错误上。
    """


class MasterActionForbiddenError(MasterActionError):
    """当前账号不能做接单 / 拒单这件事。

    典型场景：这个登录账号在 master 表里没有师傅身份；
    或者它同时是服务商账号，但 token 里的服务商归属与师傅归属不一致。
    这种账号连订单都查不到就该被挡住。
    """


class MasterActionInvariantError(MasterActionError):
    """内部一致性被打破（服务端 bug，不是客户端的问题）。

    唯一的触发场景：「本事务内本会话改过该行，回读出来仍不是我们写的样子」。

    注意它**不是**「条件 UPDATE 没命中」的原因：
    条件 UPDATE 没命中有四种可能（不存在 / 不是派给我的 / 状态不对 /
    等待行锁期间被改走又改回），对调用方一律是 404。
    其中「改走又改回」（ABA）在回查里与「谓词写错」长得一样，
    分不出来也不该分——它就是一次普通的状态变化，客户端重试即可。
    """


class MasterQueryError(Exception):
    """师傅端查询（我的订单列表 / 订单详情 / 我的资料）失败的业务异常基类。

    与前六棵异常树（PlaceOrderError / DispatchError / MasterActionError /
    ServiceFlowError / SettlementError / CatalogError）平级：
    师傅端查询是独立的一条链路，共用一个基类会让别的链路的兜底文案
    套到它头上。
    """


class MasterOrderStatusNotAllowedError(MasterQueryError):
    """师傅端只支持三种订单状态。

    业务规则：师傅的工作队列只有三组——待接单（PENDING_ACCEPT）、
    已接单待开工（ACCEPTED）、服务中（IN_SERVICE）
    （见 ``app.models.enums.MasterOrderStatus``）。

    接口层用窄枚举挡过一次（别的状态 -> 422），service 这边再挡一次：
    类型提示挡不住运行时传错值——有人绕过接口层直接调 service 时，
    ``OrderStatus.COMPLETED`` 照样能传进来，而它**不该**是一次合法查询
    （否则师傅会拿到一批比「工作队列」宽得多的单）。

    与 ``MasterStatusNotSettableError`` 同一类错误：客户端改了请求内容
    才可能解决 -> 400，不是 404、也不是 500。
    """


class MasterQueryForbiddenError(MasterQueryError):
    """当前账号不能查师傅端数据。

    典型场景：角色不对（拿普通用户 / 服务商账号来查师傅端数据）；
    或者账号在 master 表里没有师傅身份；
    或者它同时是服务商账号，但 token 里的服务商归属与师傅归属不一致。
    这种账号连订单都查不到就该被挡住。
    """


class ServiceFlowError(Exception):
    """服务流转（开工 / 完工 / 确认完成）失败的业务异常基类。

    与前三棵异常树（PlaceOrderError / DispatchError / MasterActionError）平级：
    四条链路各有一棵树，共用一个基类会让「下单失败」的兜底文案
    套到派单、接单、服务流转的错误上。
    """


class ServiceFlowForbiddenError(ServiceFlowError):
    """当前账号不能做这件事。

    典型场景：角色不对（用普通用户账号去开工）；
    或者账号在 master 表里没有师傅身份；
    或者它同时是服务商账号，但 token 里的服务商归属与师傅归属不一致。
    这种账号连订单都碰不到就该被挡住。
    """


class ServiceFlowInvariantError(ServiceFlowError):
    """内部一致性被打破（服务端 bug，不是客户端的问题）。

    唯一的触发场景：「本事务内本会话改过该行，回读出来仍不是我们写的样子」。

    注意它**不是**「条件 UPDATE 没命中」的原因：
    条件 UPDATE 没命中有四种可能（不存在 / 不是我的 / 状态不对 /
    等待行锁期间被改走又改回），对调用方一律是 404。
    """


class SettlementError(Exception):
    """结算确认失败的业务异常基类。

    与前四棵异常树（PlaceOrderError / DispatchError / MasterActionError /
    ServiceFlowError）平级：结算确认是独立的一条链路，
    共用一个基类会让「下单失败」的兜底文案套到结算确认的错误上。
    """


class SettlementForbiddenError(SettlementError):
    """当前账号不能确认结算单。

    典型场景：角色不是 PLATFORM_FINANCE（比如拿服务商账号来确认结算）。
    这种账号连结算单都查不到就该被挡住。
    """


class SettlementNotFoundError(SettlementError):
    """结算单不存在，或已经不是「待结算」。

    「不存在」与「已被确认」共用同一个异常、同一句话——
    否则调用方能靠报错差异探测某张结算单存不存在、是什么状态。
    """


class SettlementInvariantError(SettlementError):
    """内部一致性被打破（服务端 bug，不是客户端的问题）。

    唯一的触发场景：结算单被确认了，但关联订单没能全部从「待结算」
    流转到「已结算」——明细里的订单不在「待结算」状态，或明细跟订单对不上。
    这是数据坏了，必须暴露成 500，不能伪装成「结算单不存在」。
    """


class CatalogError(Exception):
    """目录查询（品类 / 服务项 / 时段）失败的业务异常基类。

    与前五棵异常树（PlaceOrderError / DispatchError / MasterActionError /
    ServiceFlowError / SettlementError）平级：目录查询是独立的一条链路，
    共用一个基类会让「下单失败」的兜底文案套到目录错误上。
    """


class CatalogNotFoundError(CatalogError):
    """品类不存在，或已停用。

    「不存在」与「已停用」共用同一个异常、同一句话——
    否则调用方能靠报错差异探测某个品类存不存在、是不是下架了。
    """
