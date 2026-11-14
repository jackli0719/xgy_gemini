# apps/h5-user

用户端 H5（Vue3 + Vant 4 + TypeScript + Vite），覆盖「看品类 → 选服务项 → 约时段 → 下单 → 看订单 → 确认完成」这条最小闭环。

## 跑起来

```bash
npm install                              # 在仓库根执行（npm workspaces 会一起装）
npm run dev  --workspace @oto/h5-user    # 开发服务器，默认 http://localhost:5173
npm run test --workspace @oto/h5-user    # vitest
npm run build --workspace @oto/h5-user   # 产物在 apps/h5-user/dist
npm run typecheck --workspace @oto/h5-user
```

后端 API 默认走**相对路径**（`/api/...`），开发时由 vite 的 proxy 转发到 `http://localhost:8000`（见 `vite.config.ts`）。要跨域直连时设置 `VITE_API_BASE_URL`。

## 目录

```
src/
├─ api/index.ts        API 客户端实例（唯一的 HTTP 出口）
├─ stores/session.ts   pinia：只放 token 和 currentUser
├─ router/index.ts     路由表 + 「没 token 就去请先登录」的守卫
├─ constants/          地址占位数据、订单状态文案
├─ utils/              query 取值、日期
└─ views/              5 个页面 + 1 个「请先登录」占位页
tests/                 vitest 测试
```

## 几条硬约束（改代码前先看一眼）

1. **不手写 fetch**：所有请求走 `@oto/shared` 的 client（`createApiClient`）。`src/api/index.ts` 是唯一的出口，页面只调 `api.xxx()`。
2. **不引 vuex / axios**：状态只有 pinia 的 `session` store，里面只有 token 和 currentUser。
3. **不写登录页、不写地址管理页**（属于 FE-03）：
   - token 从 `localStorage` 的 `oto.token` 读，没有就跳「请先登录」；
   - 地址是**占位数据**（`src/constants/addresses.ts`），后端目前没有地址接口。
4. **样式用 Vant 默认**：不写自定义主题。Vant 组件由 `unplugin-vue-components` + `VantResolver` 自动按需引入（含样式），生成的类型声明在 `src/components.d.ts`（进版本库）。

## 页面与路由

| 路由 | 页面 | 说明 |
|---|---|---|
| `/catalog` | 品类列表 | 一级品类 + 子品类，点进去看服务项 |
| `/catalog/:id` | 服务项列表 | 服务项 + 当天可约时段，点时段进下单页 |
| `/order/new?itemId=&slotId=` | 下单 | 选地址 + 选时段 + 提交，下单成功跳 `/orders` |
| `/orders` | 我的订单 | 分页 20 条，点进去是详情 |
| `/orders/:orderNo` | 订单详情 | `PENDING_CONFIRM` 时出现「确认完成」 |
| `/need-login` | 请先登录 | 占位页，登录页留给 FE-03 |

## 已知占位 / 技术债

- **地址是写死的**（`src/constants/addresses.ts`）：后端没有「我的地址」接口，FE-03 上了接口后把这里换成一次 API 调用即可，页面不用改。
- **「今天」按 UTC 算**（`src/utils/date.ts`），与后端 `app/services/user_queries.py` 的 `today()` 保持一致。面向国内用户时两边都要改成 Asia/Shanghai，不能只改一边。
- **没有 `GET /api/v1/items/{id}`**：下单页拿不到服务项详情，商品名称由列表页通过 query 带过去（`itemName`）。
