# apps/h5-master

师傅端 H5（Vue3 + Vant 4 + TypeScript + Vite），覆盖「待接单 → 已接单 → 服务中」这条工作队列：接单 / 拒单 / 开始服务 / 完成服务。

## 跑起来

```bash
npm install                                 # 在仓库根执行（npm workspaces 会一起装）
npm run dev  --workspace @oto/h5-master    # 开发服务器，默认 http://localhost:5174
npm run test --workspace @oto/h5-master    # vitest
npm run build --workspace @oto/h5-master   # 产物在 apps/h5-master/dist
npm run typecheck --workspace @oto/h5-master
```

后端 API 默认走**相对路径**（`/api/...`），开发时由 vite 的 proxy 转发到 `http://localhost:8000`（见 `vite.config.ts`）。要跨域直连时设置 `VITE_API_BASE_URL`。

端口用 5174（用户端 h5-user 用 5173），两个应用可以同时开着调试。

## 目录

```
src/
├─ api/index.ts          API 客户端实例（唯一的 HTTP 出口）
├─ stores/session.ts     pinia：只放 token 和 currentUser
├─ router/index.ts       路由表 + 「没 token 就去登录」的守卫
├─ components/           RejectPopup：拒单原因弹窗（列表页与详情页共用）
├─ constants/status.ts   订单状态文案 + 三个工作分组
└─ views/                3 个页面（登录 / 订单列表 / 订单详情）
tests/                   vitest 测试
```

## 几条硬约束（改代码前先看一眼）

1. **不手写 fetch**：所有请求走 `@oto/shared` 的 client（`createApiClient`）。`src/api/index.ts` 是唯一的出口，页面只调 `api.xxx()`。
2. **不引 vuex / axios**：状态只有 pinia 的 `session` store，里面只有 token 和 currentUser。
3. **不带 master_id / user_id / provider_id**：师傅身份由服务端按 token 里的 user_id 查 master 表得到（见后端 `app/services/master_queries.py`）。前端传了也没用——接口压根没这些入参。
4. **样式用 Vant 默认**：不写自定义主题。Vant 组件由 `unplugin-vue-components` + `VantResolver` 自动按需引入（含样式），生成的类型声明在 `src/components.d.ts`（进版本库）。

## 页面与路由

| 路由 | 页面 | 说明 |
|---|---|---|
| `/login` | 登录 | 手机号 + 验证码（MVP 验证码写死 123456） |
| `/orders` | 我的订单 | 三个 tab：待接单 / 待服务 / 服务中，各自一行操作按钮 |
| `/orders/:orderNo` | 订单详情 | 带客户联系方式与上门地址；按状态给对应操作按钮 |

数据来源：

| 界面 | 接口 |
|---|---|
| 三个分组列表 | `GET /api/v1/master/orders?status=` |
| 订单详情 | `GET /api/v1/master/orders/{order_no}` |
| 顶部资料条 | `GET /api/v1/master/profile` |
| 接单 / 拒单 | `POST /api/v1/orders/{order_no}/accept` / `/reject` |
| 开始服务 / 完成服务 | `POST /api/v1/orders/{order_no}/start` / `/finish` |

## 已知占位 / 技术债

- **拒单弹窗用 `teleport=null` 就地渲染**：正常 H5 里弹窗会传送到 body，这里是为了测试能直接在组件里找到它。将来接真机调试时可以改回默认传送（记得同步改测试的查找方式）。
- **列表不做分页**：每组先拉后端默认的 20 条（上限 100）。订单量大的话要补「上拉加载」。
- **结算不在本应用**：结算由服务商侧确认（见 FE-04 系列），师傅端只看得到与自己相关的订单状态。
