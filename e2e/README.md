# 人工测试工具（E2E-02）

手工点一遍四端闭环（下单 -> 支付 -> 派单 -> 接单 -> 开工 -> 完工 -> 确认）时用的三件套。

```
make e2e-seed     # 往开发库种演示数据（幂等）
make e2e-serve    # 起三端前端（Ctrl+C 一起停）
make e2e-clean    # 清掉 seed 种的数据
```

## 前置

- 开发库在跑：`make up`（只起 postgres / redis）
- 后端在跑（`make up` **不**起 API，compose 里没有 api 服务）：

  ```
  cd apps/api && uvicorn app.main:app --port 8000
  ```

## make e2e-seed

往**开发库**（.env 的 `DATABASE_URL`）种一套演示数据：

| 数据 | 匹配字段 |
| --- | --- |
| 服务商「演示家政」 | name |
| 服务商管理员账号 | phone 13800000002 |
| 平台管理员账号 | phone 13800000004 |
| 师傅账号 | phone 13800000003 |
| 师傅「张师傅」 | 挂在上面的师傅账号下 |
| 服务品类「家政保洁」 | name |
| 服务项目「日常保洁」 | 品类下的同名项目 |
| 预约时段 | 明天 09:00-11:00，容量 5 |

- **幂等**：重复跑只会更新已有行，不插重（第二遍输出是「更新（已存在）」）。
- **只碰开发库**：库名带 `_test` 直接拒绝执行；`TEST_DATABASE_URL` 与 `DATABASE_URL` 指向同一个库也拒绝。
- 客户账号**不种**：C 端是「登录即注册」，用手机号 `13800000001` 第一次登录就建号。
- 跑完打印每行数据的 id 与四个登录账号（验证码取 `LOGIN_SMS_CODE`，没配就是 dev 占位码 123456）。
- **平台管理员**（13800000004）是 PLAT-01 的服务商管理页用的：那一页只有
  `PLATFORM_ADMIN` 角色能进（后端按 token 里的角色判），服务商账号进不去。
  平台侧角色**不带服务商归属**，所以这个账号没有 provider_id。

## make e2e-serve

同时起三端前端：

| 端 | 端口 |
| --- | --- |
| 用户端 H5（apps/h5-user） | 5173 |
| 服务商后台（apps/web-admin） | 5174 |
| 师傅端 H5（apps/h5-master） | 5175 |

这张表是三端端口的**唯一出处**：各端 README 只指向这里，不各自抄一份端口号。

- Ctrl+C 三个一起停（脚本会递归杀进程树，不留 vite 残留）。
- 端口被占（比如本机还跑着别的项目）时换个端口：

  ```
  H5_USER_PORT=5183 WEB_ADMIN_PORT=5184 H5_MASTER_PORT=5185 make e2e-serve
  ```

- 三端都把 `/api` 代理到 `http://localhost:8000`，后端没起的话接口会失败（脚本开头会提醒）。

## make e2e-clean

把 seed 种的数据删掉（按手机号 / 名称匹配），删完会再数一遍确认清干净了。

订单的外键是 `RESTRICT`：有订单还引用着种子数据时，直接跑会报错并说明原因。
连相关订单一起清：

```
make e2e-clean ARGS=--with-orders
```

## 实现说明

- 种子脚本：`e2e/fixtures/seed-cli.ts`，用 `vite-node` 跑（vitest 自带的 TS 执行器，仓库里已有）。
- 连库走的是 **postgres 容器里的 psql**（`docker exec`）：不引新依赖，
  也不动 package.json / package-lock.json。
