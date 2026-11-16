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
    "MasterOnboardingConflictError",
    "MasterOnboardingError",
    "MasterOnboardingForbiddenError",
    "MasterOnboardingInvariantError",
    "MasterOnboardingNotFoundError",
    "MasterOrderStatusNotAllowedError",
    "MasterPendingNotSettableError",
    "MasterQueryError",
    "MasterQueryForbiddenError",
    "MasterStatusNotSettableError",
    "OrderNoConflictError",
    "OrderNotFoundError",
    "PlaceOrderError",
    "PlatformCatalogConflictError",
    "PlatformCatalogError",
    "PlatformCatalogForbiddenError",
    "PlatformCatalogNotFoundError",
    "PlatformProviderConflictError",
    "PlatformProviderError",
    "PlatformProviderForbiddenError",
    "PlatformProviderNotFoundError",
    "PlatformProviderStatusNotSettableError",
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


class MasterPendingNotSettableError(DispatchError):
    """待审核（PENDING）的师傅，服务商侧不能改他的状态。

    PENDING 是入驻流程的初始状态，只能由**平台审核**流转
    （见 app.services.master_onboarding.review_onboarding）。
    服务商提前把他置成 ACTIVE，等于绕过平台审核那道闸门；
    置成 DISABLED / ON_LEAVE 也不对——这位师傅还没入职，
    服务商根本不该动他的入职状态。

    -> 409：等服务商 / 平台把状态改掉再来（或换个人操作），
    不是 404（这个师傅确实存在且在本商作用域内）。
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


class PlatformProviderError(Exception):
    """平台侧服务商管理失败的业务异常基类。

    与前面六棵异常树平级：平台侧管服务商（入驻 / 冻结 / 建管理员账号）
    是一条独立链路，共用一个基类会让别的链路的兜底文案套到它头上。
    """


class PlatformProviderNotFoundError(PlatformProviderError):
    """服务商不存在。

    平台侧是「管理所有服务商」，不存在与「不属于我」不是一回事：
    平台管理员能看全部服务商，所以这里只有「真的不存在」这一种。
    """


class PlatformProviderConflictError(PlatformProviderError):
    """服务商状态冲突，或手机号已被占用。

    两种情况都是 409：「换个状态再来」或「换个手机号」是可行的应对：

    - 状态冲突：条件 UPDATE 没命中（当前状态不允许这次流转，
      或者等锁期间状态被别人改了）；
    - 手机号已占用：这个手机号已经有账号了。
    """


class PlatformProviderForbiddenError(PlatformProviderError):
    """当前账号不能管理服务商。

    典型场景：角色不是 PLATFORM_ADMIN。正常情况下依赖层
    （``require_platform_admin``）已经挡住了，这里是 service 层的兜底。
    """


class PlatformProviderStatusNotSettableError(PlatformProviderError):
    """这个状态不允许被设置。

    PENDING（待审核）是建档时的初始状态，平台不能把服务商改回待审核；
    两个废弃取值同理。客户端改请求内容才可能解决 -> 400，不是 409。
    """


class PlatformCatalogError(Exception):
    """平台侧品类 / 服务项管理失败的业务异常基类。

    与前七棵异常树平级：平台侧管目录（品类树 + 服务项 + 价格）
    是一条独立链路，共用一个基类会让别的链路的兜底文案套到它头上。
    """


class PlatformCatalogNotFoundError(PlatformCatalogError):
    """品类 / 服务项不存在。

    平台侧管的是**全平台**的目录，不存在与「不属于我」不是一回事：
    平台运营能看全部目录，所以这里只有「真的不存在」这一种。
    """


class PlatformCatalogConflictError(PlatformCatalogError):
    """条件 UPDATE 没命中（并发冲突）。

    改品类 / 服务项走的是「条件 UPDATE」：``WHERE id = ? AND status = 期望旧状态``。
    没命中说明这一行的状态已经被别人改过了（乐观锁冲突），
    客户端刷新后重试就行 -> 409。
    """


class PlatformCatalogForbiddenError(PlatformCatalogError):
    """当前账号不能管理目录。

    典型场景：角色不是 PLATFORM_ADMIN / PLATFORM_OPS。正常情况下依赖层
    （``require_platform_staff``）已经挡住了，这里是 service 层的兜底。
    """


class MasterOnboardingError(Exception):
    """师傅入驻失败的业务异常基类。

    与前面九棵异常树平级：入驻是独立的一条链路（师傅登记 + 平台审核），
    共用一个基类会让别的链路的兜底文案套到入驻错误上。
    """


class MasterOnboardingForbiddenError(MasterOnboardingError):
    """当前账号不能做这件事。

    典型场景：角色不是普通用户（服务商账号、平台账号都不该来申请入驻）；
    或者这个账号已经在师傅体系里了（角色已是 MASTER）。

    失败发生在**碰库之前**：角色不对的账号连「能不能申请」都问不到。
    """


class MasterOnboardingNotFoundError(MasterOnboardingError):
    """入驻申请不存在，或目标服务商不存在 / 不可加入。

    这两类都用同一个异常、同一句话，**不区分失败原因**：
    入驻申请是**按 user_id 查自己**的（不存在就是不存在），
    服务商那一侧则要同时挡住「不存在」与「不是 ACTIVE（已冻结 / 待审核）」
    两种情况——调用方不该靠报错差异去枚举哪些服务商存在、哪些被冻结。
    """


class MasterOnboardingConflictError(MasterOnboardingError):
    """状态冲突：不能重复申请，或审核条件已变。

    - 已经有入驻申请（审核中 / 已入职 / 在服务商处被停用）；
    - 条件 UPDATE 没命中（并发：另一个请求先一步提交了申请，
      或者两个平台管理员同时审了同一份申请）。

    都是「换个时候再来 / 刷新后重试」能解决的 -> 409。
    """


class MasterOnboardingInvariantError(MasterOnboardingError):
    """内部一致性被打破（服务端 bug，不是客户端的问题）。

    唯一的触发场景：「本事务内本会话改过这一行，回读出来仍不是我们写的样子」，
    或者「库里出现了 master 表与 user 表对不上的数据」
    （师傅身份与登录账号必须一一对应，且师傅的归属只由 master 表说了算）。

    这类错误必须暴露成 500：它意味着服务端数据坏了，
    伪装成「没申请过」只会让调用方一直重试。
    """

