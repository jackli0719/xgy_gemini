/**
 * 从后端导出的 OpenAPI 契约生成 TypeScript 类型。
 *
 * 用法：
 *   npm run generate:api            # 在 packages/shared 下
 *   npm run generate:api -w @oto/shared   # 在仓库根下（转发到本包）
 *
 * 输入：apps/api/openapi.json（由 `make openapi` 导出，已进版本库）
 * 输出：packages/shared/src/api/schema.ts（自动生成，进版本库）
 *
 * 为什么生成物要进版本库：openapi-typescript 是构建时工具，
 * 不要求每个前端开发者本地都装一遍依赖才能写代码。契约变了的时候，
 * 由改后端的人（或专门跑一遍生成的人）把生成物一起提交，
 * 评审时能直接看到「接口变了」和「类型变了」是同一件事。
 *
 * 前提：apps/api/openapi.json 必须是最新的。
 * 后端加了接口忘了重新导出，生成的类型就会少一截——
 * 契约检查测试（apps/api/tests/api/test_openapi_contract.py）会先把这件事拦下来。
 */
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import openapiTS, { astToString } from "openapi-typescript";

const HERE = dirname(fileURLToPath(import.meta.url));
/** packages/shared —— 本包的根目录 */
const PKG_ROOT = resolve(HERE, "..");
/** 仓库根 —— 契约文件在 apps/api/openapi.json */
const REPO_ROOT = resolve(PKG_ROOT, "../..");
const SCHEMA_PATH = resolve(REPO_ROOT, "apps/api/openapi.json");
const OUT_PATH = resolve(PKG_ROOT, "src/api/schema.ts");

/**
 * 生成文件的头注释。
 * 写清楚三件事：这是自动生成的、别手改、怎么改（改后端契约而不是改这个文件）。
 */
const BANNER = `/**
 * 本文件由 \`npm run generate:api\` 自动生成，请勿手改。
 *
 * 生成器：openapi-typescript（见 packages/shared/scripts/generate-api.mjs）
 * 数据源：apps/api/openapi.json（由 \`make openapi\` 从 FastAPI 应用导出）
 *
 * 要改这里的类型？改后端接口 / schema，然后重新生成：
 *   make openapi && npm run generate:api
 * 手改这个文件会在下次生成时被覆盖，而且会让前端类型和后端契约悄悄对不上。
 */
`;

async function main() {
  let source;
  try {
    source = await readFile(SCHEMA_PATH, "utf-8");
  } catch (err) {
    console.error(`读不到契约文件：${SCHEMA_PATH}`);
    console.error("先跑 \`make openapi\` 导出契约，再生成类型。");
    throw err;
  }

  const schema = JSON.parse(source);
  const ast = await openapiTS(schema);
  const contents = `${BANNER}\n${astToString(ast)}`;

  await mkdir(dirname(OUT_PATH), { recursive: true });
  await writeFile(OUT_PATH, contents, "utf-8");

  const pathCount = Object.keys(schema.paths ?? {}).length;
  console.log(`已生成 ${OUT_PATH}`);
  console.log(`  契约路径 ${pathCount} 条 / schema ${Object.keys(schema.components?.schemas ?? {}).length} 个`);
}

await main();
