# OTO 家政服务平台

OTO 家政服务平台的 Monorepo，包含 4 个端：用户 H5、师傅 H5、平台端与服务商端（共用一套 Web 后台）。

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | FastAPI（Python 3.11+）、SQLAlchemy、Alembic |
| 数据库 | PostgreSQL |
| 缓存 | Redis |
| 前端 | Vue3；H5 端 Vant，Web 管理端 Element Plus |
| 部署 | Docker Compose |

## 目录结构

```
oto/
├─ apps/
│  ├─ api/          FastAPI 后端，4 端共用一套 API
│  ├─ h5-user/      用户端 H5
│  ├─ h5-master/    师傅端 H5
│  └─ web-admin/    平台端 + 服务商端共用后台（provider_id 租户隔离）
├─ packages/
│  ├─ shared/       跨端共享类型、常量、API SDK
│  ├─ ui/           跨端共享组件与主题
│  └─ config/       共享工程配置
├─ infra/           容器与编排文件（后续任务卡引入）
├─ docs/            架构、ADR、任务卡、接口文档
└─ scripts/         运维与初始化脚本
```

## 关键约定

- **租户隔离**：服务商端与平台端共用 `apps/web-admin` 与后端 API，服务商数据一律按 `provider_id` 隔离；`provider_id` 由服务端从登录态推导，不信任前端传值。
- **师傅归属**：师傅必须挂入一个服务商（`provider_id` 非空）。
- **前端仓库**：`h5-user` 与 `h5-master` 为两个独立工程，各自独立构建发布。

## 本地开发

后端依赖安装、环境变量与本地服务编排由后续任务卡提供；当前仓库仅包含骨架结构。

环境变量清单见 `.env.example`（复制为 `.env` 后填写）。

## 当前状态

T-01b：Monorepo 骨架已创建，尚无业务代码、容器编排与 CI 配置。
