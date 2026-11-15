"""受控枚举取值。

全部使用 PostgreSQL 原生枚举类型，取值集合由数据库强制约束。
新增取值需 `ALTER TYPE ... ADD VALUE`，不能靠应用层塞值。
"""
from enum import Enum

from sqlalchemy.dialects import postgresql


class UserStatus(str, Enum):
    """用户状态。"""

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    BANNED = "BANNED"


class UserRole(str, Enum):
    """用户角色。

    角色与「是否归属某个服务商」强绑定：只有 PROVIDER_ADMIN / PROVIDER_STAFF
    带 provider_id，其余角色必须没有（数据库 CHECK 约束 ck_user_role_provider 强制）。

    注意 MASTER（师傅）：师傅的归属权威来源是 master 表，不是 user.provider_id。
    一个师傅可能同时是某个服务商的管理员，但「这个用户对应哪个师傅身份」
    只能查 master 表——user.provider_id 记的是**登录账号**的服务商归属，
    与师傅身份是两回事。技术债：两者没有在模型层做一致性校验。
    """

    USER = "USER"
    MASTER = "MASTER"
    PROVIDER_ADMIN = "PROVIDER_ADMIN"
    PROVIDER_STAFF = "PROVIDER_STAFF"
    PLATFORM_ADMIN = "PLATFORM_ADMIN"
    PLATFORM_OPS = "PLATFORM_OPS"
    PLATFORM_FINANCE = "PLATFORM_FINANCE"
    PLATFORM_CS = "PLATFORM_CS"


class ProviderStatus(str, Enum):
    """服务商状态。

    - ``PENDING``：待审核。平台侧刚建出来的初始状态，审核通过后转 ACTIVE；
    - ``ACTIVE``：正常营业；
    - ``FROZEN``：被平台冻结（不能接新单，但已有订单还要继续处理）。

    ``SUSPENDED`` / ``CLOSED`` 是早期设计的停用 / 关停取值，**现在已废弃**：
    全仓库没有任何代码写这两个值。但 PostgreSQL 的枚举取值删不掉
    （见迁移 0007），所以它们仍然留在类型里——留着是为了让
    「create_all 建的测试库」与「alembic 建的开发库」枚举取值集合一致。

    **取值顺序与迁移建出来的库不一样**：迁移 0001 建的是
    (ACTIVE, SUSPENDED, CLOSED)，0007 追加的是 (PENDING, FROZEN)，
    而这里是按业务含义排的。PostgreSQL 的枚举排序按「取值在类型里的
    先后」，所以**不要按 status 排序**（列表接口按 id 排，见
    app.services.platform_provider.list_providers）。
    """

    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class SettableProviderStatus(str, Enum):
    """平台侧可以把服务商置成的状态。

    比 ``ProviderStatus`` 少了 ``PENDING``：PENDING 是建号时的初始状态，
    平台不能把服务商改回待审核（那等于让审核白做）。
    也没带上两个废弃取值。

    放在这里（而不是 schema 层）是因为它不是「接口长什么样」，而是
    **业务规则**：哪些状态允许被设置，service 也要按同一份判断，
    不能只靠请求体校验拦一道（与 ``SettableMasterStatus`` 同一思路）。
    """

    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"


class MasterStatus(str, Enum):
    """师傅状态。"""

    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    DISABLED = "DISABLED"


class SettableMasterStatus(str, Enum):
    """服务商可以设置的师傅状态。

    比 ``MasterStatus`` 少一个 ``PENDING``：PENDING 是入驻流程的初始状态
    （师傅已登记、还没通过审核），由平台侧的入驻卡产生。服务商不能把它
    写回去——否则一个没通过审核的师傅会重新变成「可派单」的状态。

    放在这里（而不是 schema 层）是因为它不是「接口长什么样」，而是
    **业务规则**：哪些状态允许被设置，service 也要按同一份判断，
    不能只靠请求体校验拦一道。
    """

    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    DISABLED = "DISABLED"


class MasterOrderStatus(str, Enum):
    """师傅端订单列表可见的三种状态。

    这是**业务规则**，不是「接口长什么样」：师傅的工作队列只有三组——
    待接单（PENDING_ACCEPT）、已接单待开工（ACCEPTED）、服务中（IN_SERVICE）。

    放在这里（而不是 schema 层）是因为它是**业务规则**，service 也要按
    同一份判断：接口层用窄枚举把别的状态变成 422，service 这边用同一份
    定义做**运行时校验**（见 app.services.master_queries.
    _resolve_master_order_status），把不合法的状态挡在碰库之前——
    类型提示挡不住运行时传错值，有人绕过接口层直接调 service 时
    照样能传进别的枚举值。

    与 ``OrderStatus`` 的取值同名但不是同一个类型：订单状态机有 12 态，
    师傅端只关心其中三个。
    """

    PENDING_ACCEPT = "PENDING_ACCEPT"
    ACCEPTED = "ACCEPTED"
    IN_SERVICE = "IN_SERVICE"


class CatalogStatus(str, Enum):
    """服务分类 / 服务项目状态。"""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class PayStatus(str, Enum):
    """订单支付状态。"""

    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDING = "REFUNDING"
    REFUNDED = "REFUNDED"


class OrderStatus(str, Enum):
    """订单状态机取值（12 态，流转由状态机函数负责）。"""

    PENDING_PAY = "PENDING_PAY"
    PENDING_DISPATCH = "PENDING_DISPATCH"
    PENDING_ACCEPT = "PENDING_ACCEPT"
    ACCEPTED = "ACCEPTED"
    IN_SERVICE = "IN_SERVICE"
    PENDING_CONFIRM = "PENDING_CONFIRM"
    COMPLETED = "COMPLETED"
    PENDING_SETTLE = "PENDING_SETTLE"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"
    REFUNDING = "REFUNDING"
    REFUNDED = "REFUNDED"


class SettlementStatus(str, Enum):
    """结算单状态。

    PENDING：待结算（由 T+1 定时任务生成，等待服务商确认）。
    CONFIRMED：已确认（服务商确认过金额，等待打款）。
    """

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"


class OperatorType(str, Enum):
    """订单状态流转的操作方类型。

    服务商侧区分管理员与普通员工，供 R3「非授权角色可触发金额变更」审计判定使用。

    平台侧同理分三种：PLATFORM_ADMIN（平台管理员）、PLATFORM_OPS（平台运营，
    管目录与改价）、PLATFORM_FINANCE（平台财务，确认结算）。
    拿 PLATFORM_ADMIN 顶替 PLATFORM_OPS 会丢信息——「谁改的价」在审计上是
    两拨人，R3 要靠 operator_type 区分。

    **取值顺序与迁移建出来的库不一样**：0001 建的是
    (..., PLATFORM_ADMIN, SYSTEM)，0006 追加 PLATFORM_FINANCE、
    0008 追加 PLATFORM_OPS，都是追加到末尾；而这里按「谁用得多」排。
    没有任何地方按 operator_type 排序（排序按 id / 时间），所以不影响逻辑。
    """

    USER = "USER"
    MASTER = "MASTER"
    PROVIDER_ADMIN = "PROVIDER_ADMIN"
    PROVIDER_STAFF = "PROVIDER_STAFF"
    PLATFORM_ADMIN = "PLATFORM_ADMIN"
    PLATFORM_OPS = "PLATFORM_OPS"
    PLATFORM_FINANCE = "PLATFORM_FINANCE"
    SYSTEM = "SYSTEM"


def pg_enum(enum_cls: type[Enum], name: str, create_type: bool = True):
    """构造 PostgreSQL 原生枚举列类型。

    同一枚举类型被多列引用时，只有第一处 `create_type=True`，
    其余列传 False，避免重复 CREATE TYPE。
    """
    return postgresql.ENUM(enum_cls, name=name, create_type=create_type)
