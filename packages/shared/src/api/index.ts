/**
 * API SDK 入口。
 *
 * - ./schema —— 自动生成，勿手改（`npm run generate:api`）
 * - ./client —— 手写的 fetch 封装，类型来自 ./schema
 */
export * from "./schema";
export * from "./client";
