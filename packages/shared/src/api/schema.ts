/**
 * 本文件由 `npm run generate:api` 自动生成，请勿手改。
 *
 * 生成器：openapi-typescript（见 packages/shared/scripts/generate-api.mjs）
 * 数据源：apps/api/openapi.json（由 `make openapi` 从 FastAPI 应用导出）
 *
 * 要改这里的类型？改后端接口 / schema，然后重新生成：
 *   make openapi && npm run generate:api
 * 手改这个文件会在下次生成时被覆盖，而且会让前端类型和后端契约悄悄对不上。
 */

export interface paths {
    "/api/v1/orders": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * 我的订单列表
         * @description 列出当前用户的订单（按创建时间倒序，带分页）。
         */
        get: operations["list_my_orders_api_v1_orders_get"];
        put?: never;
        /**
         * 下单
         * @description 创建一笔订单，返回订单摘要。
         */
        post: operations["create_order_api_v1_orders_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/orders/{order_no}/start": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * 师傅开工
         * @description 开工：订单从「已接单」流转到「服务中」。
         */
        post: operations["start_order_service_api_v1_orders__order_no__start_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/orders/{order_no}/finish": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * 师傅完工
         * @description 完工：订单从「服务中」流转到「待确认」，等客户确认。
         */
        post: operations["finish_order_service_api_v1_orders__order_no__finish_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/orders/{order_no}/confirm": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * 客户确认完成
         * @description 客户确认完成：订单从「待确认」流转到「已完成」，并写入完工时间。
         */
        post: operations["confirm_order_service_api_v1_orders__order_no__confirm_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/orders/{order_no}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * 订单详情
         * @description 返回当前用户的一笔订单详情。
         *
         *     订单不存在或不属于当前用户 -> 404（两种情况同构）。
         */
        get: operations["get_my_order_api_v1_orders__order_no__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/pay/mock-notify": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * mock 支付回调（仅 dev）
         * @description 模拟支付成功回调，把订单推进到待派单。
         *
         *     幂等：重复回调同一笔订单不会重复改状态、重复写状态流转日志。
         */
        post: operations["mock_pay_notify_api_v1_pay_mock_notify_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/orders/{order_id}/dispatch": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * 派单
         * @description 把订单派给本商师傅，订单转为「待接单」。
         */
        post: operations["dispatch_order_api_v1_orders__order_id__dispatch_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/orders/{order_no}/accept": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * 师傅接单
         * @description 接下派给自己的订单，订单转为「已接单」。
         */
        post: operations["accept_order_api_v1_orders__order_no__accept_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/orders/{order_no}/reject": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * 师傅拒单
         * @description 拒掉派给自己的订单，订单退回「待派单」，清空承接师傅。
         */
        post: operations["reject_order_api_v1_orders__order_no__reject_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/settlements/{settlement_id}/confirm": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * 财务确认结算
         * @description 确认一张待结算的结算单，关联订单一并转为「已结算」。
         *
         *     角色不对返回 403；结算单不存在或已被确认返回 404（两种情况同构）。
         */
        post: operations["confirm_settlement_api_v1_settlements__settlement_id__confirm_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/catalog": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * 品类列表（含子品类）
         * @description 返回品类树：一级品类，每个带自己的子树。
         *
         *     只返回启用的品类；父品类停用时整棵子树一起下架。
         */
        get: operations["list_categories_api_v1_catalog_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/catalog/{category_id}/items": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * 某品类下的服务项
         * @description 返回某个品类下**直接归属**该品类的服务项（只含启用的）。
         *
         *     子品类下的服务项不在这里返回——前端拿到品类树后自己按 category_id 再查。
         */
        get: operations["list_category_items_api_v1_catalog__category_id__items_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/items/{item_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * 单个服务项
         * @description 返回单个服务项的详情（名称 / 基准价 / 时长）。
         *
         *     服务项不存在或已停用 -> 404（「不存在」与「已停用」共用一句话）。
         */
        get: operations["get_item_api_v1_items__item_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/items/{item_id}/slots": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * 某服务项某天的可预约时段
         * @description 返回某服务项在某天的可预约时段。
         *
         *     只返回还能约的：日期 >= 今天，且 available = capacity - used > 0。
         *     已约满的时段不出现在列表里（点进去也会被下单接口挡成 409）。
         */
        get: operations["list_item_slots_api_v1_items__item_id__slots_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/addresses": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * 我的地址列表
         * @description 返回当前用户的全部地址（按创建顺序）。
         */
        get: operations["list_addresses_api_v1_addresses_get"];
        put?: never;
        /**
         * 新建地址
         * @description 新建一条属于当前用户的地址。
         */
        post: operations["create_address_api_v1_addresses_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/addresses/{address_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * 修改地址
         * @description 修改当前用户的某条地址（整体替换四个字段）。
         *
         *     地址不存在或不属于当前用户 -> 404（两种情况同构）。
         */
        put: operations["update_address_api_v1_addresses__address_id__put"];
        post?: never;
        /**
         * 删除地址
         * @description 删除当前用户的某条地址。
         *
         *     地址不存在或不属于当前用户 -> 404（两种情况同构）。
         */
        delete: operations["delete_address_api_v1_addresses__address_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/provider/orders": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * 本商订单列表（默认待派单）
         * @description 列出本商可见的、处于指定状态的订单。
         *
         *     待派单（PENDING_DISPATCH）时，可见范围 = 公共待派单池（还没归属的单）
         *     + 本商专属（师傅拒单后退回本商的单）。可见范围与「能不能派」
         *     是同一套条件（见 app.services.provider_queries）。
         */
        get: operations["list_provider_orders_api_v1_provider_orders_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/provider/masters": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * 本商师傅列表
         * @description 列出本商的师傅（id / 姓名 / 手机号 / 评分 / 状态）。
         *
         *     所有状态的师傅都返回（含停用 / 休假），由派单的人自己挑。
         */
        get: operations["list_provider_masters_api_v1_provider_masters_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/provider/masters/{master_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * 改本商师傅状态
         * @description 把本商师傅改成指定状态（启用 / 休假 / 停用）。
         *
         *     师傅不属于本商，或这个师傅不存在，都是同一个 404、同一句话
         *     （不泄露存在性）。
         */
        patch: operations["update_provider_master_api_v1_provider_masters__master_id__patch"];
        trace?: never;
    };
    "/api/v1/master/orders": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * 我的订单列表（按状态）
         * @description 列出派给我的、处于指定状态的订单。
         *
         *     归属由 token 决定（服务端按 user_id 查 master 表），
         *     这里不接收 master_id 入参。
         */
        get: operations["list_master_orders_api_v1_master_orders_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/master/orders/{order_no}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * 订单详情
         * @description 返回派给我的一笔订单详情（含客户联系方式与上门地址）。
         *
         *     订单不存在或不是派给我的 -> 404（两种情况同构）。
         */
        get: operations["get_master_order_api_v1_master_orders__order_no__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/master/profile": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * 我的资料
         * @description 返回当前师傅的资料（姓名 / 评分 / 状态 / 所属服务商）。
         */
        get: operations["get_master_profile_api_v1_master_profile_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/platform/providers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * 服务商列表（平台侧，分页）
         * @description 列出平台侧可见的全部服务商。
         */
        get: operations["list_platform_providers_api_v1_platform_providers_get"];
        put?: never;
        /**
         * 新建服务商（初始状态：待审核）
         * @description 建一个服务商，初始状态是「待审核」（PENDING）。
         *
         *     状态**不由请求体决定**：新建一律待审核，要审核通过再调改状态接口。
         */
        post: operations["create_platform_provider_api_v1_platform_providers_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/platform/providers/{provider_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * 改服务商状态（审核通过 / 冻结 / 解冻）
         * @description 把服务商改成指定状态。
         *
         *     当前状态不允许这次流转 -> 409（条件 UPDATE 没命中）。
         *     服务商不存在 -> 404。
         */
        patch: operations["update_platform_provider_status_api_v1_platform_providers__provider_id__patch"];
        trace?: never;
    };
    "/api/v1/platform/providers/{provider_id}/admin": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * 给服务商建管理员账号
         * @description 给某个服务商建一个 PROVIDER_ADMIN 账号（入参只有手机号）。
         *
         *     手机号已被占用 -> 409「手机号已注册」。
         */
        post: operations["create_platform_provider_admin_api_v1_platform_providers__provider_id__admin_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * 手机号 + 验证码登录
         * @description 用手机号和验证码登录，返回访问令牌。
         *
         *     手机号没注册过会自动建号（C 端「登录即注册」）。
         */
        post: operations["login_api_v1_auth_login_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * AcceptResult
         * @description 接单成功后的结果。
         */
        AcceptResult: {
            /**
             * Order No
             * @description 订单号
             */
            order_no: string;
            /** @description 订单状态 */
            status: components["schemas"]["OrderStatus"];
            /**
             * Master Id
             * @description 承接订单的师傅 ID
             */
            master_id: number;
        };
        /**
         * AddressCreateRequest
         * @description 新建地址的请求体。
         *
         *     字段集合就是「联系人 / 电话 / 地区 / 详细地址」四个，多一个少一个都算破坏契约。
         */
        AddressCreateRequest: {
            /**
             * Contact
             * @description 联系人
             */
            contact: string;
            /**
             * Phone
             * @description 联系电话
             */
            phone: string;
            /**
             * Region
             * @description 省市区
             */
            region: string;
            /**
             * Detail
             * @description 详细地址
             */
            detail: string;
        };
        /**
         * AddressResponse
         * @description 一条收货地址。
         */
        AddressResponse: {
            /**
             * Id
             * @description 地址 ID
             */
            id: number;
            /**
             * Contact
             * @description 联系人
             */
            contact: string;
            /**
             * Phone
             * @description 联系电话
             */
            phone: string;
            /**
             * Region
             * @description 省市区
             */
            region: string;
            /**
             * Detail
             * @description 详细地址
             */
            detail: string;
        };
        /**
         * AddressUpdateRequest
         * @description 修改地址的请求体。
         *
         *     PUT 是**整体替换**：四个字段都要给全，不用给就说明客户端以为它是增量更新，
         *     那就该用 PATCH。与新建同构，所以直接继承新建的字段定义。
         */
        AddressUpdateRequest: {
            /**
             * Contact
             * @description 联系人
             */
            contact: string;
            /**
             * Phone
             * @description 联系电话
             */
            phone: string;
            /**
             * Region
             * @description 省市区
             */
            region: string;
            /**
             * Detail
             * @description 详细地址
             */
            detail: string;
        };
        /**
         * CategoryNode
         * @description 品类节点（含子品类）。
         *
         *     ``children`` 只挂**直接下级**；子品类自己的子品类递归嵌在它里面。
         *     停用的品类不出现在树里（它的子树也一起不出现）。
         */
        CategoryNode: {
            /**
             * Id
             * @description 品类 ID
             */
            id: number;
            /**
             * Name
             * @description 品类名称
             */
            name: string;
            /**
             * Parent Id
             * @description 父品类 ID，一级品类为空
             */
            parent_id: number | null;
            /**
             * Sort Order
             * @description 排序值，越小越靠前
             */
            sort_order: number;
            /**
             * Children
             * @description 子品类
             */
            children?: components["schemas"]["CategoryNode"][];
        };
        /**
         * ConfirmSettlementResult
         * @description 确认结算后的结算单状态。
         */
        ConfirmSettlementResult: {
            /**
             * Id
             * @description 结算单 ID
             */
            id: number;
            /** @description 结算单状态（确认后为 CONFIRMED） */
            status: components["schemas"]["SettlementStatus"];
            /**
             * Net Amount
             * @description 服务商实收金额
             */
            net_amount: string;
            /**
             * Confirmed At
             * @description 确认时间（确认后非空）
             */
            confirmed_at?: string | null;
        };
        /**
         * CreateProviderAdminRequest
         * @description 给某个服务商建管理员账号的请求体。
         *
         *     **只有手机号**：账号的角色（PROVIDER_ADMIN）与归属（provider_id）
         *     都由服务端按路径与规则填，客户端说了不算。
         */
        CreateProviderAdminRequest: {
            /**
             * Phone
             * @description 管理员登录用的手机号（纯数字）
             */
            phone: string;
        };
        /**
         * CreateProviderRequest
         * @description 新建服务商的请求体。
         *
         *     **只有这三个字段**：服务商归属（也就是「归谁管」）由平台侧决定，
         *     不在请求体里；状态也不在——新建一律「待审核」（PENDING），
         *     要审核通过再调改状态接口。
         */
        CreateProviderRequest: {
            /**
             * Name
             * @description 服务商名称
             */
            name: string;
            /**
             * Contact Phone
             * @description 联系电话
             */
            contact_phone: string;
            /**
             * Commission Rate
             * @description 佣金比例（0~1，例如 0.15 表示 15%）
             */
            commission_rate: number | string;
        };
        /**
         * DispatchRequest
         * @description 派单请求体。
         */
        DispatchRequest: {
            /**
             * Master Id
             * @description 承接订单的师傅 ID
             */
            master_id: number;
        };
        /**
         * DispatchResult
         * @description 派单成功后的结果。
         */
        DispatchResult: {
            /**
             * Order No
             * @description 订单号
             */
            order_no: string;
            /** @description 订单状态 */
            status: components["schemas"]["OrderStatus"];
            /**
             * Master Id
             * @description 承接订单的师傅 ID
             */
            master_id: number;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /**
         * LoginRequest
         * @description 手机号 + 验证码登录。
         */
        LoginRequest: {
            /**
             * Phone
             * @description 手机号（纯数字）
             */
            phone: string;
            /**
             * Code
             * @description 短信验证码（MVP 写死，见 settings.login_sms_code）
             */
            code: string;
        };
        /**
         * LoginResponse
         * @description 登录成功：给 token 和用户信息。
         */
        LoginResponse: {
            /**
             * Access Token
             * @description 访问令牌（HS256 JWT）
             */
            access_token: string;
            /**
             * Token Type
             * @description 令牌类型
             * @default bearer
             */
            token_type: string;
            /** @description 当前用户 */
            user: components["schemas"]["LoginUser"];
        };
        /**
         * LoginUser
         * @description 登录用户的基本信息 + 身份归属。
         *
         *     ``role`` 与 ``provider_id`` 是**这个账号自己的**归属信息
         *     （JWT 里带着同样的两个 claim），回给客户端是为了让它知道
         *     「我是谁、我属于哪个服务商」——服务商端据此决定展示哪些菜单。
         *
         *     这不是「泄露别家的归属」：这里回的是登录者自己的信息。
         *     租户隔离本身不靠这个字段，靠的是 token（见 app.core.auth）。
         */
        LoginUser: {
            /**
             * Id
             * @description 用户 ID
             */
            id: number;
            /**
             * Nickname
             * @description 昵称
             */
            nickname: string;
            /**
             * Phone
             * @description 手机号
             */
            phone: string;
            /** @description 用户角色 */
            role: components["schemas"]["UserRole"];
            /**
             * Provider Id
             * @description 归属的服务商 ID；服务商侧角色才有值，其余角色为 null
             */
            provider_id: number | null;
        };
        /**
         * MasterOrderDetail
         * @description 订单详情：多了客户联系方式与上门地址。
         *
         *     师傅要上门服务，得知道去哪儿、找谁——所以详情里带地址与电话。
         *     可见范围由服务端保证：只有派给他的订单才查得到（404 同构）。
         */
        MasterOrderDetail: {
            /**
             * Order No
             * @description 订单号
             */
            order_no: string;
            /** @description 订单状态 */
            status: components["schemas"]["OrderStatus"];
            /**
             * Amount
             * @description 订单金额
             */
            amount: string;
            /**
             * Item Id
             * @description 服务项 ID
             */
            item_id: number;
            /**
             * Item Name
             * @description 服务项名称
             */
            item_name: string;
            /**
             * Slot Date
             * Format: date
             * @description 预约日期
             */
            slot_date: string;
            /**
             * Slot Start Time
             * Format: time
             * @description 预约开始时间
             */
            slot_start_time: string;
            /**
             * Slot End Time
             * Format: time
             * @description 预约结束时间
             */
            slot_end_time: string;
            /**
             * Created At
             * Format: date-time
             * @description 下单时间
             */
            created_at: string;
            /**
             * Id
             * @description 订单 ID
             */
            id: number;
            /**
             * Slot Id
             * @description 预约时段 ID
             */
            slot_id: number;
            /**
             * Customer Contact
             * @description 客户称呼
             */
            customer_contact: string;
            /**
             * Customer Phone
             * @description 客户电话
             */
            customer_phone: string;
            /**
             * Address Region
             * @description 地址所在区域
             */
            address_region: string;
            /**
             * Address Detail
             * @description 详细地址
             */
            address_detail: string;
        };
        /**
         * MasterOrderItem
         * @description 师傅端订单列表里的一项。
         *
         *     不含 master_id / provider_id：师傅知道自己是谁，不需要知道订单内部
         *     怎么归属的（也不该由客户端去猜）。
         */
        MasterOrderItem: {
            /**
             * Order No
             * @description 订单号
             */
            order_no: string;
            /** @description 订单状态 */
            status: components["schemas"]["OrderStatus"];
            /**
             * Amount
             * @description 订单金额
             */
            amount: string;
            /**
             * Item Id
             * @description 服务项 ID
             */
            item_id: number;
            /**
             * Item Name
             * @description 服务项名称
             */
            item_name: string;
            /**
             * Slot Date
             * Format: date
             * @description 预约日期
             */
            slot_date: string;
            /**
             * Slot Start Time
             * Format: time
             * @description 预约开始时间
             */
            slot_start_time: string;
            /**
             * Slot End Time
             * Format: time
             * @description 预约结束时间
             */
            slot_end_time: string;
            /**
             * Created At
             * Format: date-time
             * @description 下单时间
             */
            created_at: string;
        };
        /**
         * MasterOrderListResponse
         * @description 订单列表（一页 + 总数）。
         *
         *     带 total 是因为前端要显示「共 N 条」并判断还有没有下一页；
         *     只回一个数组的话，客户端只能靠「这页有没有满 limit」去猜。
         */
        MasterOrderListResponse: {
            /**
             * Items
             * @description 当前页的订单
             */
            items: components["schemas"]["MasterOrderItem"][];
            /**
             * Total
             * @description 符合条件的订单总数（不受分页影响）
             */
            total: number;
            /**
             * Limit
             * @description 本次生效的每页条数（上限 100）
             */
            limit: number;
            /**
             * Offset
             * @description 本次跳过的条数
             */
            offset: number;
        };
        /**
         * MasterOrderStatus
         * @description 师傅端订单列表可见的三种状态。
         *
         *     这是**业务规则**，不是「接口长什么样」：师傅的工作队列只有三组——
         *     待接单（PENDING_ACCEPT）、已接单待开工（ACCEPTED）、服务中（IN_SERVICE）。
         *
         *     放在这里（而不是 schema 层）是因为它是**业务规则**，service 也要按
         *     同一份判断：接口层用窄枚举把别的状态变成 422，service 这边用同一份
         *     定义做**运行时校验**（见 app.services.master_queries.
         *     _resolve_master_order_status），把不合法的状态挡在碰库之前——
         *     类型提示挡不住运行时传错值，有人绕过接口层直接调 service 时
         *     照样能传进别的枚举值。
         *
         *     与 ``OrderStatus`` 的取值同名但不是同一个类型：订单状态机有 12 态，
         *     师傅端只关心其中三个。
         * @enum {string}
         */
        MasterOrderStatus: "PENDING_ACCEPT" | "ACCEPTED" | "IN_SERVICE";
        /**
         * MasterProfile
         * @description 师傅自己的资料。
         *
         *     ``rating`` 可以是空：还没被评价过的师傅没有分数。
         *     ``provider_name`` 是所属服务商的名称（师傅要知道自己是哪家的）。
         */
        MasterProfile: {
            /**
             * Real Name
             * @description 师傅姓名
             */
            real_name: string;
            /**
             * Rating
             * @description 评分（0~5，可空）
             */
            rating?: string | null;
            /** @description 师傅状态 */
            status: components["schemas"]["MasterStatus"];
            /**
             * Provider Name
             * @description 所属服务商名称
             */
            provider_name: string;
        };
        /**
         * MasterStatus
         * @description 师傅状态。
         * @enum {string}
         */
        MasterStatus: "PENDING" | "ACTIVE" | "ON_LEAVE" | "DISABLED";
        /**
         * MockPayNotifyRequest
         * @description mock 支付回调的请求体。
         */
        MockPayNotifyRequest: {
            /**
             * Order No
             * @description 订单号
             */
            order_no: string;
        };
        /**
         * MockPayResult
         * @description mock 支付回调的响应体。
         *
         *     只回三个字段：订单号、订单状态、支付状态。不回金额、不回用户信息。
         */
        MockPayResult: {
            /** Order No */
            order_no: string;
            status: components["schemas"]["OrderStatus"];
            pay_status: components["schemas"]["PayStatus"];
        };
        /**
         * OrderDetail
         * @description 订单详情。
         */
        OrderDetail: {
            /**
             * Order No
             * @description 订单号
             */
            order_no: string;
            /** @description 订单状态 */
            status: components["schemas"]["OrderStatus"];
            /** @description 支付状态 */
            pay_status: components["schemas"]["PayStatus"];
            /**
             * Amount
             * @description 订单金额
             */
            amount: string;
            /**
             * Item Id
             * @description 服务项 ID
             */
            item_id: number;
            /**
             * Item Name
             * @description 服务项名称
             */
            item_name: string;
            /**
             * Slot Date
             * Format: date
             * @description 预约日期
             */
            slot_date: string;
            /**
             * Slot Start Time
             * Format: time
             * @description 预约开始时间
             */
            slot_start_time: string;
            /**
             * Created At
             * Format: date-time
             * @description 下单时间
             */
            created_at: string;
            /**
             * Id
             * @description 订单 ID
             */
            id: number;
            /**
             * Slot Id
             * @description 预约时段 ID
             */
            slot_id: number;
            /**
             * Slot End Time
             * Format: time
             * @description 预约结束时间
             */
            slot_end_time: string;
            /**
             * Address Id
             * @description 收货地址 ID
             */
            address_id: number;
        };
        /**
         * OrderListItem
         * @description 订单列表里的一项。
         */
        OrderListItem: {
            /**
             * Order No
             * @description 订单号
             */
            order_no: string;
            /** @description 订单状态 */
            status: components["schemas"]["OrderStatus"];
            /** @description 支付状态 */
            pay_status: components["schemas"]["PayStatus"];
            /**
             * Amount
             * @description 订单金额
             */
            amount: string;
            /**
             * Item Id
             * @description 服务项 ID
             */
            item_id: number;
            /**
             * Item Name
             * @description 服务项名称
             */
            item_name: string;
            /**
             * Slot Date
             * Format: date
             * @description 预约日期
             */
            slot_date: string;
            /**
             * Slot Start Time
             * Format: time
             * @description 预约开始时间
             */
            slot_start_time: string;
            /**
             * Created At
             * Format: date-time
             * @description 下单时间
             */
            created_at: string;
        };
        /**
         * OrderListResponse
         * @description 订单列表（一页 + 总数）。
         *
         *     带 total 是因为前端要显示「共 N 条」并判断还有没有下一页；
         *     只回一个数组的话，客户端只能靠「这页有没有满 limit」去猜。
         */
        OrderListResponse: {
            /**
             * Items
             * @description 当前页的订单
             */
            items: components["schemas"]["OrderListItem"][];
            /**
             * Total
             * @description 该用户的订单总数（不受分页影响）
             */
            total: number;
            /**
             * Limit
             * @description 本次生效的每页条数（上限 100）
             */
            limit: number;
            /**
             * Offset
             * @description 本次跳过的条数
             */
            offset: number;
        };
        /**
         * OrderStatus
         * @description 订单状态机取值（12 态，流转由状态机函数负责）。
         * @enum {string}
         */
        OrderStatus: "PENDING_PAY" | "PENDING_DISPATCH" | "PENDING_ACCEPT" | "ACCEPTED" | "IN_SERVICE" | "PENDING_CONFIRM" | "COMPLETED" | "PENDING_SETTLE" | "SETTLED" | "CANCELLED" | "REFUNDING" | "REFUNDED";
        /**
         * OrderSummary
         * @description 下单成功后的订单摘要。
         */
        OrderSummary: {
            /**
             * Id
             * @description 订单 ID
             */
            id: number;
            /**
             * Order No
             * @description 订单号
             */
            order_no: string;
            /** @description 订单状态 */
            status: components["schemas"]["OrderStatus"];
            /**
             * Amount
             * @description 订单金额（服务端按服务项基准价快照）
             */
            amount: string;
        };
        /**
         * PayStatus
         * @description 订单支付状态。
         * @enum {string}
         */
        PayStatus: "UNPAID" | "PAID" | "REFUNDING" | "REFUNDED";
        /**
         * PlaceOrderRequest
         * @description 下单请求体。
         *
         *     字段集合就是 ``{item_id, slot_id, address_id}``，多一个少一个都算破坏契约
         *     （有测试盯着）。
         */
        PlaceOrderRequest: {
            /**
             * Item Id
             * @description 服务项 ID
             */
            item_id: number;
            /**
             * Slot Id
             * @description 预约时段 ID
             */
            slot_id: number;
            /**
             * Address Id
             * @description 收货地址 ID
             */
            address_id: number;
        };
        /**
         * PlatformProviderItem
         * @description 平台侧看到的一条服务商。
         */
        PlatformProviderItem: {
            /**
             * Id
             * @description 服务商 ID
             */
            id: number;
            /**
             * Name
             * @description 服务商名称
             */
            name: string;
            /**
             * Contact Phone
             * @description 联系电话
             */
            contact_phone: string;
            /**
             * Commission Rate
             * @description 佣金比例（0~1）
             */
            commission_rate: string;
            /** @description 服务商状态 */
            status: components["schemas"]["ProviderStatus"];
            /**
             * Created At
             * Format: date-time
             * @description 建档时间
             */
            created_at: string;
        };
        /**
         * PlatformProviderListResponse
         * @description 服务商列表（一页 + 总数）。
         */
        PlatformProviderListResponse: {
            /**
             * Items
             * @description 当前页的服务商
             */
            items: components["schemas"]["PlatformProviderItem"][];
            /**
             * Total
             * @description 符合条件的服务商总数（不受分页影响）
             */
            total: number;
            /**
             * Page
             * @description 当前页码（从 1 开始）
             */
            page: number;
            /**
             * Limit
             * @description 本次生效的每页条数（上限 100）
             */
            limit: number;
        };
        /**
         * ProviderAdminItem
         * @description 刚建出来的服务商管理员账号。
         */
        ProviderAdminItem: {
            /**
             * Id
             * @description 用户 ID
             */
            id: number;
            /**
             * Phone
             * @description 登录手机号
             */
            phone: string;
            /** @description 用户角色（PROVIDER_ADMIN） */
            role: components["schemas"]["UserRole"];
            /**
             * Provider Id
             * @description 归属的服务商 ID
             */
            provider_id: number;
            /**
             * Created At
             * Format: date-time
             * @description 建号时间
             */
            created_at: string;
        };
        /**
         * ProviderMasterItem
         * @description 本商师傅的一项。
         *
         *     ``rating`` 可以是空：还没被评价过的师傅没有分数。
         *     ``phone`` 是师傅登录账号的手机号（master 表上没有这一列，
         *     来自它关联的 user）。
         */
        ProviderMasterItem: {
            /**
             * Id
             * @description 师傅 ID（派单接口用它）
             */
            id: number;
            /**
             * Real Name
             * @description 师傅姓名
             */
            real_name: string;
            /**
             * Phone
             * @description 师傅登录账号的手机号
             */
            phone: string;
            /**
             * Rating
             * @description 评分（0~5，可空）
             */
            rating?: string | null;
            /** @description 师傅状态 */
            status: components["schemas"]["MasterStatus"];
        };
        /**
         * ProviderMasterListResponse
         * @description 本商师傅列表。
         */
        ProviderMasterListResponse: {
            /**
             * Items
             * @description 师傅列表
             */
            items: components["schemas"]["ProviderMasterItem"][];
            /**
             * Total
             * @description 师傅总数
             */
            total: number;
        };
        /**
         * ProviderOrderItem
         * @description 待派单列表里的一笔订单。
         *
         *     带 ``id``（数字主键）：派单接口 ``POST /orders/{order_id}/dispatch``
         *     收的是数字 id，不是订单号——前端拿它拼 URL，不用再查一次。
         */
        ProviderOrderItem: {
            /**
             * Id
             * @description 订单 ID（派单接口用它）
             */
            id: number;
            /**
             * Order No
             * @description 订单号
             */
            order_no: string;
            /** @description 订单状态 */
            status: components["schemas"]["OrderStatus"];
            /** @description 支付状态 */
            pay_status: components["schemas"]["PayStatus"];
            /**
             * Amount
             * @description 订单金额
             */
            amount: string;
            /**
             * Item Id
             * @description 服务项 ID
             */
            item_id: number;
            /**
             * Item Name
             * @description 服务项名称
             */
            item_name: string;
            /**
             * Slot Date
             * Format: date
             * @description 预约日期
             */
            slot_date: string;
            /**
             * Slot Start Time
             * Format: time
             * @description 预约开始时间
             */
            slot_start_time: string;
            /**
             * Created At
             * Format: date-time
             * @description 下单时间
             */
            created_at: string;
        };
        /**
         * ProviderOrderListResponse
         * @description 待派单列表（一页 + 总数）。
         *
         *     带 total 是因为前端要显示「共 N 条」；只回一个数组的话，
         *     客户端只能靠「这页有没有满 limit」去猜还有没有下一页。
         */
        ProviderOrderListResponse: {
            /**
             * Items
             * @description 当前页的订单
             */
            items: components["schemas"]["ProviderOrderItem"][];
            /**
             * Total
             * @description 符合条件的订单总数（不受分页影响）
             */
            total: number;
            /**
             * Limit
             * @description 本次生效的每页条数（上限 100）
             */
            limit: number;
            /**
             * Offset
             * @description 本次跳过的条数
             */
            offset: number;
        };
        /**
         * ProviderStatus
         * @description 服务商状态。
         *
         *     - ``PENDING``：待审核。平台侧刚建出来的初始状态，审核通过后转 ACTIVE；
         *     - ``ACTIVE``：正常营业；
         *     - ``FROZEN``：被平台冻结（不能接新单，但已有订单还要继续处理）。
         *
         *     ``SUSPENDED`` / ``CLOSED`` 是早期设计的停用 / 关停取值，**现在已废弃**：
         *     全仓库没有任何代码写这两个值。但 PostgreSQL 的枚举取值删不掉
         *     （见迁移 0007），所以它们仍然留在类型里——留着是为了让
         *     「create_all 建的测试库」与「alembic 建的开发库」枚举取值集合一致。
         *
         *     **取值顺序与迁移建出来的库不一样**：迁移 0001 建的是
         *     (ACTIVE, SUSPENDED, CLOSED)，0007 追加的是 (PENDING, FROZEN)，
         *     而这里是按业务含义排的。PostgreSQL 的枚举排序按「取值在类型里的
         *     先后」，所以**不要按 status 排序**（列表接口按 id 排，见
         *     app.services.platform_provider.list_providers）。
         * @enum {string}
         */
        ProviderStatus: "PENDING" | "ACTIVE" | "FROZEN" | "SUSPENDED" | "CLOSED";
        /**
         * RejectRequest
         * @description 拒单请求体。
         */
        RejectRequest: {
            /**
             * Reason
             * @description 拒单原因，会原样写进订单状态流转日志
             */
            reason: string;
        };
        /**
         * RejectResult
         * @description 拒单成功后的结果。
         *
         *     master_id 为空：拒单后订单退回「待派单」，当前没有承接师傅。
         */
        RejectResult: {
            /**
             * Order No
             * @description 订单号
             */
            order_no: string;
            /** @description 订单状态 */
            status: components["schemas"]["OrderStatus"];
            /**
             * Master Id
             * @description 承接订单的师傅 ID（拒单后为空）
             */
            master_id: number | null;
        };
        /**
         * ServiceFlowResult
         * @description 服务流转动作执行后的订单状态。
         */
        ServiceFlowResult: {
            /**
             * Order No
             * @description 订单号
             */
            order_no: string;
            /** @description 流转后的订单状态 */
            status: components["schemas"]["OrderStatus"];
            /**
             * Completed At
             * @description 完工时间（订单完成时非空）
             */
            completed_at?: string | null;
        };
        /**
         * ServiceItemSummary
         * @description 服务项摘要（可下单的具体服务与价格）。
         */
        ServiceItemSummary: {
            /**
             * Id
             * @description 服务项 ID
             */
            id: number;
            /**
             * Category Id
             * @description 所属品类 ID
             */
            category_id: number;
            /**
             * Name
             * @description 服务项名称
             */
            name: string;
            /**
             * Base Price
             * @description 基准价（服务端按它快照下单金额）
             */
            base_price: string;
            /**
             * Duration Min
             * @description 服务时长（分钟）
             */
            duration_min: number;
        };
        /**
         * SettableMasterStatus
         * @description 服务商可以设置的师傅状态。
         *
         *     比 ``MasterStatus`` 少一个 ``PENDING``：PENDING 是入驻流程的初始状态
         *     （师傅已登记、还没通过审核），由平台侧的入驻卡产生。服务商不能把它
         *     写回去——否则一个没通过审核的师傅会重新变成「可派单」的状态。
         *
         *     放在这里（而不是 schema 层）是因为它不是「接口长什么样」，而是
         *     **业务规则**：哪些状态允许被设置，service 也要按同一份判断，
         *     不能只靠请求体校验拦一道。
         * @enum {string}
         */
        SettableMasterStatus: "ACTIVE" | "ON_LEAVE" | "DISABLED";
        /**
         * SettableProviderStatus
         * @description 平台侧可以把服务商置成的状态。
         *
         *     比 ``ProviderStatus`` 少了 ``PENDING``：PENDING 是建号时的初始状态，
         *     平台不能把服务商改回待审核（那等于让审核白做）。
         *     也没带上两个废弃取值。
         *
         *     放在这里（而不是 schema 层）是因为它不是「接口长什么样」，而是
         *     **业务规则**：哪些状态允许被设置，service 也要按同一份判断，
         *     不能只靠请求体校验拦一道（与 ``SettableMasterStatus`` 同一思路）。
         * @enum {string}
         */
        SettableProviderStatus: "ACTIVE" | "FROZEN";
        /**
         * SettlementStatus
         * @description 结算单状态。
         *
         *     PENDING：待结算（由 T+1 定时任务生成，等待服务商确认）。
         *     CONFIRMED：已确认（服务商确认过金额，等待打款）。
         * @enum {string}
         */
        SettlementStatus: "PENDING" | "CONFIRMED";
        /**
         * SlotAvailability
         * @description 某个时段的可预约情况。
         *
         *     ``available`` = capacity - used，只返回 available > 0 的时段。
         *     容量与已占用数一起返回，是为了让前端能显示「还剩几个」，
         *     而不是让前端自己算一遍（两边的口径容易不一致）。
         */
        SlotAvailability: {
            /**
             * Id
             * @description 时段 ID
             */
            id: number;
            /**
             * Item Id
             * @description 服务项 ID
             */
            item_id: number;
            /**
             * Date
             * Format: date
             * @description 时段日期
             */
            date: string;
            /**
             * Start Time
             * Format: time
             * @description 开始时间
             */
            start_time: string;
            /**
             * End Time
             * Format: time
             * @description 结束时间
             */
            end_time: string;
            /**
             * Capacity
             * @description 总容量
             */
            capacity: number;
            /**
             * Used
             * @description 已占用数
             */
            used: number;
            /**
             * Available
             * @description 剩余可预约数 = capacity - used
             */
            available: number;
        };
        /**
         * UpdateMasterStatusRequest
         * @description 改师傅状态的请求体。
         *
         *     **只有 status 一个字段**：master_id 从路径来，服务商归属从 token 来。
         *     带上别的字段（比如 provider_id）会被 ``extra="forbid"`` 直接 422，
         *     而不是被静默忽略——静默忽略会让人以为字段生效了。
         *
         *     ``status`` 用的是**窄枚举** ``SettableMasterStatus``（少了 PENDING），
         *     所以接口这一层就把「PENDING 不许设置」变成 422。
         *     但这只是一道防线：service 那边按同一份枚举再挡一次
         *     （见 app.services.master_management），免得有人绕过接口层直接调 service。
         */
        UpdateMasterStatusRequest: {
            /** @description 要把师傅改成什么状态 */
            status: components["schemas"]["SettableMasterStatus"];
        };
        /**
         * UpdateProviderStatusRequest
         * @description 改服务商状态的请求体。
         *
         *     ``status`` 用的是**窄枚举** ``SettableProviderStatus``（ACTIVE / FROZEN），
         *     所以接口这一层就把「PENDING 不许设置」变成 422。
         *     但这只是一道防线：service 那边按同一份枚举再挡一次
         *     （见 app.services.platform_provider），免得有人绕过接口层直接调 service。
         */
        UpdateProviderStatusRequest: {
            /** @description 要把服务商改成什么状态 */
            status: components["schemas"]["SettableProviderStatus"];
        };
        /**
         * UserRole
         * @description 用户角色。
         *
         *     角色与「是否归属某个服务商」强绑定：只有 PROVIDER_ADMIN / PROVIDER_STAFF
         *     带 provider_id，其余角色必须没有（数据库 CHECK 约束 ck_user_role_provider 强制）。
         *
         *     注意 MASTER（师傅）：师傅的归属权威来源是 master 表，不是 user.provider_id。
         *     一个师傅可能同时是某个服务商的管理员，但「这个用户对应哪个师傅身份」
         *     只能查 master 表——user.provider_id 记的是**登录账号**的服务商归属，
         *     与师傅身份是两回事。技术债：两者没有在模型层做一致性校验。
         * @enum {string}
         */
        UserRole: "USER" | "MASTER" | "PROVIDER_ADMIN" | "PROVIDER_STAFF" | "PLATFORM_ADMIN" | "PLATFORM_OPS" | "PLATFORM_FINANCE" | "PLATFORM_CS";
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
            /** Input */
            input?: unknown;
            /** Context */
            ctx?: Record<string, never>;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    list_my_orders_api_v1_orders_get: {
        parameters: {
            query?: {
                /** @description 每页条数，默认 20，上限 100（超过按 100 算） */
                limit?: number;
                /** @description 跳过的条数，默认 0 */
                offset?: number;
            };
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OrderListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_order_api_v1_orders_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PlaceOrderRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OrderSummary"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    start_order_service_api_v1_orders__order_no__start_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                order_no: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ServiceFlowResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    finish_order_service_api_v1_orders__order_no__finish_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                order_no: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ServiceFlowResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    confirm_order_service_api_v1_orders__order_no__confirm_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                order_no: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ServiceFlowResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_my_order_api_v1_orders__order_no__get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                /** @description 订单号 */
                order_no: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OrderDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    mock_pay_notify_api_v1_pay_mock_notify_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MockPayNotifyRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MockPayResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    dispatch_order_api_v1_orders__order_id__dispatch_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                order_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DispatchRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DispatchResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    accept_order_api_v1_orders__order_no__accept_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                order_no: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AcceptResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reject_order_api_v1_orders__order_no__reject_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                order_no: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RejectRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RejectResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    confirm_settlement_api_v1_settlements__settlement_id__confirm_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                settlement_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConfirmSettlementResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_categories_api_v1_catalog_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CategoryNode"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_category_items_api_v1_catalog__category_id__items_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                /** @description 品类 ID */
                category_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ServiceItemSummary"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_item_api_v1_items__item_id__get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                /** @description 服务项 ID */
                item_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ServiceItemSummary"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_item_slots_api_v1_items__item_id__slots_get: {
        parameters: {
            query: {
                /** @description 查询日期，YYYY-MM-DD */
                date: string;
            };
            header?: {
                authorization?: string | null;
            };
            path: {
                /** @description 服务项 ID */
                item_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SlotAvailability"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_addresses_api_v1_addresses_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AddressResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_address_api_v1_addresses_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AddressCreateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AddressResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_address_api_v1_addresses__address_id__put: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                /** @description 地址 ID */
                address_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AddressUpdateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AddressResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_address_api_v1_addresses__address_id__delete: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                /** @description 地址 ID */
                address_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_provider_orders_api_v1_provider_orders_get: {
        parameters: {
            query?: {
                /** @description 按订单状态过滤，默认待派单（PENDING_DISPATCH） */
                status?: components["schemas"]["OrderStatus"];
                /** @description 每页条数，默认 20，上限 100（超过按 100 算） */
                limit?: number;
                /** @description 跳过的条数，默认 0 */
                offset?: number;
            };
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProviderOrderListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_provider_masters_api_v1_provider_masters_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProviderMasterListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_provider_master_api_v1_provider_masters__master_id__patch: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                master_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateMasterStatusRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProviderMasterItem"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_master_orders_api_v1_master_orders_get: {
        parameters: {
            query?: {
                /** @description 按订单状态过滤，只接受师傅端的三种：PENDING_ACCEPT（待接单）/ ACCEPTED（已接单待开工）/ IN_SERVICE（服务中） */
                status?: components["schemas"]["MasterOrderStatus"];
                /** @description 每页条数，默认 20，上限 100（超过按 100 算） */
                limit?: number;
                /** @description 跳过的条数，默认 0 */
                offset?: number;
            };
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MasterOrderListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_master_order_api_v1_master_orders__order_no__get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                /** @description 订单号 */
                order_no: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MasterOrderDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_master_profile_api_v1_master_profile_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MasterProfile"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_platform_providers_api_v1_platform_providers_get: {
        parameters: {
            query?: {
                /** @description 按状态过滤，不传=全部 */
                status?: components["schemas"]["ProviderStatus"] | null;
                /** @description 页码，从 1 开始 */
                page?: number;
                /** @description 每页条数，默认 20，上限 100（超过按 100 算） */
                limit?: number;
            };
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlatformProviderListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_platform_provider_api_v1_platform_providers_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateProviderRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlatformProviderItem"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_platform_provider_status_api_v1_platform_providers__provider_id__patch: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                /** @description 服务商 ID */
                provider_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateProviderStatusRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlatformProviderItem"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_platform_provider_admin_api_v1_platform_providers__provider_id__admin_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                /** @description 服务商 ID */
                provider_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateProviderAdminRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProviderAdminItem"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    login_api_v1_auth_login_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LoginRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LoginResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}
