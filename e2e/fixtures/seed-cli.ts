/**
 * 人工测试的种子数据 CLI（E2E-02）。
 *
 * 用途：开发同学想手工点一遍四端闭环（下单 -> 支付 -> 派单 -> 接单 ->
 * 开工 -> 完工 -> 确认）时，需要一个「有账号、有目录、有时段」的库。
 * 这个脚本把那套演示数据种进**开发库**，并且**幂等**：重复跑不会插重，
 * 只会更新已有行（跑第二遍的输出是「更新」而不是「新建」）。
 *
 * 两个子命令：
 *
 *   seed   种数据（默认）
 *   clean  把 seed 种的数据删掉（按手机号 / 名称匹配）
 *
 * 跑法（从仓库根）：
 *
 *   make e2e-seed
 *   make e2e-clean
 *
 * 为什么不引新依赖：卡上要求「不引新依赖，用现有 pg 客户端」。
 * 这里用的是 PostgreSQL 自带的 **psql**——它在 postgres:16-alpine 镜像里，
 * 已经在跑了（make up 起的那个容器），所以一个 npm 包都不用装，
 * 也不动 package.json / package-lock.json。
 * 本文件用 vite-node 跑（vitest 自带的 TS 执行器，仓库里已有）。
 *
 * 三条硬规矩：
 *
 * 1. **只碰开发库**：DATABASE_URL 指向的库名以 `_test` 结尾就直接拒绝执行。
 * 2. **不碰测试库**：TEST_DATABASE_URL 与 DATABASE_URL 相同时也拒绝。
 * 3. **幂等**：所有插入都是 upsert 语义，重复跑不报错、不插重。
 */
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// 仓库根：e2e/fixtures/seed-cli.ts -> 上溯两层
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

// ---------------------------------------------------------------------
// 种子数据的常量（改这里 = 改演示数据）
// ---------------------------------------------------------------------

const PROVIDER_NAME = "演示家政";
const PROVIDER_PHONE = "13900000000";
const CATEGORY_NAME = "家政保洁";
const ITEM_NAME = "日常保洁";
const ITEM_PRICE = "100.00";
const ITEM_DURATION_MIN = 60;
const SLOT_START = "09:00";
const SLOT_END = "11:00";
const SLOT_CAPACITY = 5;

const PROVIDER_ADMIN_PHONE = "13800000002";
const MASTER_PHONE = "13800000003";
const MASTER_NAME = "张师傅";

/**
 * 平台管理员账号（PLAT-01 的服务商管理页只有这个角色能进）。
 *
 * 平台侧角色**不带服务商归属**（数据库 CHECK 约束 ck_user_role_provider
 * 强制：只有 PROVIDER_ADMIN / PROVIDER_STAFF 能有 provider_id），
 * 所以这个账号没有 provider_id。
 */
const PLATFORM_ADMIN_PHONE = "13800000004";

/** 客户手机号：不在库里种——C 端是「登录即注册」。 */
const CUSTOMER_PHONE = "13800000001";

/** dev 下的占位验证码（与 app/core/config.py 的 DEV_LOGIN_SMS_CODE 一致）。 */
const DEFAULT_LOGIN_CODE = "123456";

/** 实体 key -> 中文名（输出用）。 */
const ENTITY_LABELS: Record<string, string> = {
  service_provider: "服务商",
  user_admin: "服务商管理员账号",
  user_platform_admin: "平台管理员账号",
  user_master: "师傅账号",
  master: "师傅",
  service_category: "服务品类",
  service_item: "服务项目",
  schedule_slot: "预约时段",
  user: "账号",
  order: "订单",
  settlement: "结算单",
  settlement_item: "结算明细",
};

// ---------------------------------------------------------------------
// .env 读取
// ---------------------------------------------------------------------

function readEnvFile(path: string): Record<string, string> {
  const out: Record<string, string> = {};
  let raw: string;
  try {
    raw = readFileSync(path, "utf8");
  } catch {
    throw new Error(
      `读不到 ${path}。先在仓库根执行 cp .env.example .env 并填写必填项。`,
    );
  }
  for (const line of raw.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq <= 0) continue;
    const key = trimmed.slice(0, eq).trim();
    let value = trimmed.slice(eq + 1).trim();
    // 去掉行尾注释（只处理没被引号包住的值）
    if (!value.startsWith('"') && !value.startsWith("'")) {
      const hash = value.indexOf(" #");
      if (hash >= 0) value = value.slice(0, hash).trim();
    }
    value = value.replace(/^["']/, "").replace(/["']$/, "");
    out[key] = value;
  }
  return out;
}

interface DatabaseTarget {
  database: string;
  user: string;
  host: string;
  port: string;
}

/**
 * 解析 DATABASE_URL。
 *
 * 注意驱动后缀：URL 里是 `postgresql+asyncpg://`，那是 SQLAlchemy 的写法，
 * 标准 URL 解析器不认，所以先把 scheme 上的 `+xxx` 去掉再解析
 * （只动 scheme，`postgresql+asyncpg` -> `postgresql`）。
 */
function parseDatabaseUrl(rawUrl: string): DatabaseTarget {
  const normalized = rawUrl.replace(
    /^([a-zA-Z][a-zA-Z0-9+.-]*)\+[a-zA-Z0-9_]+:/,
    "$1:",
  );
  let parsed: URL;
  try {
    parsed = new URL(normalized);
  } catch {
    throw new Error(`DATABASE_URL 解析不了：${rawUrl}`);
  }
  const database = decodeURIComponent(parsed.pathname.replace(/^\//, ""));
  if (!database) {
    throw new Error(`DATABASE_URL 里没有库名：${rawUrl}`);
  }
  return {
    database,
    user: decodeURIComponent(parsed.username || "postgres"),
    host: parsed.hostname,
    port: parsed.port || "5432",
  };
}

// ---------------------------------------------------------------------
// 库守卫：只碰开发库
// ---------------------------------------------------------------------

function resolveTarget(env: Record<string, string>): DatabaseTarget {
  // 环境变量优先于 .env：临时换个库试的时候不用改文件。
  // 但守卫照样生效——环境变量指向 _test 库一样拒绝。
  const rawUrl = process.env.DATABASE_URL || env.DATABASE_URL;
  if (!rawUrl) {
    throw new Error(".env 里没有 DATABASE_URL，没法知道该连哪个库。");
  }
  const target = parseDatabaseUrl(rawUrl);

  // 规矩 1：库名带 _test 的一律拒绝
  if (target.database.endsWith("_test")) {
    throw new Error(
      `拒绝执行：DATABASE_URL 指向的是测试库（${target.database}）。` +
        "这个脚本只允许操作开发库。",
    );
  }
  // 规矩 2：测试库跟开发库指向同一个库时也拒绝
  const testUrl = process.env.TEST_DATABASE_URL || env.TEST_DATABASE_URL;
  if (testUrl) {
    const testTarget = parseDatabaseUrl(testUrl);
    if (testTarget.database === target.database) {
      throw new Error(
        `拒绝执行：TEST_DATABASE_URL 与 DATABASE_URL 指向同一个库（${target.database}）。`,
      );
    }
  }
  // compose 起的服务商库名（POSTGRES_DB）必须跟 URL 里的库名一致，
  // 不一致说明 .env 与 compose 对不上，这时插进去的数据会落在别的库上
  const composeDb = env.POSTGRES_DB;
  if (composeDb && composeDb !== target.database) {
    throw new Error(
      `拒绝执行：.env 里 POSTGRES_DB=${composeDb} 与 DATABASE_URL 的库名 ` +
        `${target.database} 不一致，先把 .env 对齐。`,
    );
  }
  return target;
}

// ---------------------------------------------------------------------
// 走容器里的 psql
// ---------------------------------------------------------------------

/**
 * 找到开发库的 postgres 容器。
 *
 * 优先用 compose 查（容器名改了也不会失联），查不到再按名字找。
 */
function resolveContainer(): string {
  try {
    const out = execFileSync(
      "docker",
      [
        "compose",
        "--env-file",
        ".env",
        "-f",
        "infra/compose/docker-compose.dev.yml",
        "ps",
        "-q",
        "postgres",
      ],
      { cwd: ROOT, encoding: "utf8" },
    );
    const id = out.trim().split("\n")[0]?.trim();
    if (id) return id;
  } catch {
    // compose 不可用就退回到按名字找
  }
  const out = execFileSync(
    "docker",
    ["ps", "--filter", "name=^/oto-postgres$", "--format", "{{.Names}}"],
    { encoding: "utf8" },
  );
  const name = out.trim().split("\n")[0]?.trim();
  if (!name) {
    throw new Error(
      "开发库没在跑。先执行 make up 起 postgres / redis，再跑这个脚本。",
    );
  }
  return name;
}

/**
 * 在开发库里执行一段 SQL，返回 psql 的输出行。
 *
 * 走 docker exec + 容器里的 psql：
 * - 容器内走 unix socket，不用处理密码；
 * - psql 自带 ON_ERROR_STOP，出错立刻非零退出，不会带着半截数据往下跑。
 */
function runSql(sql: string, user: string, database: string): string[] {
  const container = resolveContainer();
  const args = [
    "exec",
    "-i",
    container,
    "psql",
    "-v",
    "ON_ERROR_STOP=1",
    "-q",
    "-t",
    "-A",
    "-F",
    "|",
    "-U",
    user,
    "-d",
    database,
    "-f",
    "-",
  ];
  try {
    const out = execFileSync("docker", args, {
      input: sql,
      encoding: "utf8",
      cwd: ROOT,
      stdio: ["pipe", "pipe", "pipe"],
    });
    return out
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.length > 0);
  } catch (err) {
    const e = err as { stderr?: string; stdout?: string; status?: number };
    const detail = (e.stderr || e.stdout || String(err)).trim();
    throw new Error(`SQL 执行失败（psql 退出码 ${e.status ?? "?"}）：\n${detail}`);
  }
}

/** SQL 字面量转义（值都是脚本内的常量，但转义一下免得以后改值踩坑）。 */
function lit(value: string): string {
  return `'${value.replace(/'/g, "''")}'`;
}

/** 子查询：按名称取服务端 id（取第一条，保证结果唯一）。 */
function byName(table: string, column: string, value: string): string {
  return `(SELECT id FROM ${table} WHERE ${column} = ${lit(value)} ORDER BY id LIMIT 1)`;
}

// ---------------------------------------------------------------------
// seed
// ---------------------------------------------------------------------

function buildSeedSql(slotDate: string): string {
  const providerId = byName("service_provider", "name", PROVIDER_NAME);
  const categoryId = `(SELECT id FROM service_category WHERE name = ${lit(
    CATEGORY_NAME,
  )} AND parent_id IS NULL ORDER BY id LIMIT 1)`;
  const itemId = `(SELECT id FROM service_item WHERE name = ${lit(
    ITEM_NAME,
  )} AND category_id = ${categoryId} ORDER BY id LIMIT 1)`;

  return `
\\set ON_ERROR_STOP on
BEGIN;

-- 1. 服务商
WITH upd AS (
    UPDATE service_provider
       SET contact_phone = ${lit(PROVIDER_PHONE)}, status = 'ACTIVE', updated_at = now()
     WHERE id = ${providerId}
    RETURNING id
), ins AS (
    INSERT INTO service_provider
           (name, contact_phone, status, commission_rate, created_at, updated_at)
    SELECT ${lit(PROVIDER_NAME)}, ${lit(PROVIDER_PHONE)}, 'ACTIVE', 0.05, now(), now()
     WHERE NOT EXISTS (SELECT 1 FROM upd)
    RETURNING id
)
SELECT 'service_provider', upd.id::text, false, ${lit(PROVIDER_NAME)} FROM upd
UNION ALL
SELECT 'service_provider', ins.id::text, true, ${lit(PROVIDER_NAME)} FROM ins;

-- 2. 服务商管理员账号
WITH ins AS (
    INSERT INTO "user"
           (phone, nickname, role, status, provider_id, created_at, updated_at)
    SELECT ${lit(PROVIDER_ADMIN_PHONE)}, '演示服务商管理员', 'PROVIDER_ADMIN', 'ACTIVE',
           ${providerId}, now(), now()
    ON CONFLICT (phone) DO UPDATE
       SET nickname = EXCLUDED.nickname, role = EXCLUDED.role, status = EXCLUDED.status,
           provider_id = EXCLUDED.provider_id, updated_at = now()
    RETURNING id, phone, role, (xmax = 0) AS created
)
SELECT 'user_admin', ins.id::text, ins.created,
       ins.phone || ' ' || ins.role::text FROM ins;

-- 3. 平台管理员账号（PLAT-01 的服务商管理页只有这个角色能进）
-- 平台侧角色不带服务商归属（数据库 CHECK 约束 ck_user_role_provider 强制）
WITH ins AS (
    INSERT INTO "user"
           (phone, nickname, role, status, provider_id, created_at, updated_at)
    SELECT ${lit(PLATFORM_ADMIN_PHONE)}, '演示平台管理员', 'PLATFORM_ADMIN', 'ACTIVE',
           NULL, now(), now()
    ON CONFLICT (phone) DO UPDATE
       SET nickname = EXCLUDED.nickname, role = EXCLUDED.role, status = EXCLUDED.status,
           provider_id = NULL, updated_at = now()
    RETURNING id, phone, role, (xmax = 0) AS created
)
SELECT 'user_platform_admin', ins.id::text, ins.created,
       ins.phone || ' ' || ins.role::text FROM ins;

-- 4. 师傅账号
-- 师傅的归属权威来源是 master 表，所以 user.provider_id 必须是空的
-- （数据库 CHECK 约束 ck_user_role_provider 强制）
WITH ins AS (
    INSERT INTO "user"
           (phone, nickname, role, status, provider_id, created_at, updated_at)
    SELECT ${lit(MASTER_PHONE)}, '演示师傅', 'MASTER', 'ACTIVE', NULL, now(), now()
    ON CONFLICT (phone) DO UPDATE
       SET nickname = EXCLUDED.nickname, role = EXCLUDED.role, status = EXCLUDED.status,
           provider_id = NULL, updated_at = now()
    RETURNING id, phone, role, (xmax = 0) AS created
)
SELECT 'user_master', ins.id::text, ins.created,
       ins.phone || ' ' || ins.role::text FROM ins;

-- 5. 师傅（挂在服务商下）
WITH ins AS (
    INSERT INTO master
           (provider_id, user_id, real_name, status, rating, created_at, updated_at)
    SELECT ${providerId},
           (SELECT id FROM "user" WHERE phone = ${lit(MASTER_PHONE)}),
           ${lit(MASTER_NAME)}, 'ACTIVE', 4.8, now(), now()
    ON CONFLICT (user_id) DO UPDATE
       SET provider_id = EXCLUDED.provider_id, real_name = EXCLUDED.real_name,
           status = EXCLUDED.status, rating = EXCLUDED.rating, updated_at = now()
    RETURNING id, real_name, (xmax = 0) AS created
)
SELECT 'master', ins.id::text, ins.created, ins.real_name FROM ins;

-- 6. 服务品类
WITH upd AS (
    UPDATE service_category
       SET status = 'ACTIVE', sort_order = 0, updated_at = now()
     WHERE id = ${categoryId}
    RETURNING id
), ins AS (
    INSERT INTO service_category
           (name, parent_id, status, sort_order, created_at, updated_at)
    SELECT ${lit(CATEGORY_NAME)}, NULL, 'ACTIVE', 0, now(), now()
     WHERE NOT EXISTS (SELECT 1 FROM upd)
    RETURNING id
)
SELECT 'service_category', upd.id::text, false, ${lit(CATEGORY_NAME)} FROM upd
UNION ALL
SELECT 'service_category', ins.id::text, true, ${lit(CATEGORY_NAME)} FROM ins;

-- 7. 服务项目
WITH upd AS (
    UPDATE service_item
       SET base_price = ${ITEM_PRICE}, duration_min = ${ITEM_DURATION_MIN},
           status = 'ACTIVE', updated_at = now()
     WHERE id = ${itemId}
    RETURNING id
), ins AS (
    INSERT INTO service_item
           (category_id, name, base_price, duration_min, status, created_at, updated_at)
    SELECT ${categoryId}, ${lit(ITEM_NAME)}, ${ITEM_PRICE}, ${ITEM_DURATION_MIN},
           'ACTIVE', now(), now()
     WHERE NOT EXISTS (SELECT 1 FROM upd)
    RETURNING id
)
SELECT 'service_item', upd.id::text, false, ${lit(ITEM_NAME)} FROM upd
UNION ALL
SELECT 'service_item', ins.id::text, true, ${lit(ITEM_NAME)} FROM ins;

-- 8. 预约时段（明天 ${SLOT_START}-${SLOT_END}）
-- 已经存在的时段只更新 end_time / capacity，不动 used：
-- used 是被订单占掉的库存，重置它会让已下单的时段凭空多出名额。
WITH ins AS (
    INSERT INTO schedule_slot
           (item_id, date, start_time, end_time, capacity, used, created_at, updated_at)
    SELECT ${itemId}, DATE ${lit(slotDate)}, ${lit(SLOT_START)}, ${lit(SLOT_END)},
           ${SLOT_CAPACITY}, 0, now(), now()
    ON CONFLICT (item_id, date, start_time) DO UPDATE
       SET end_time = EXCLUDED.end_time, capacity = EXCLUDED.capacity, updated_at = now()
    RETURNING id, (xmax = 0) AS created
)
SELECT 'schedule_slot', ins.id::text, ins.created,
       ${lit(`${slotDate} ${SLOT_START}-${SLOT_END}`)} FROM ins;

COMMIT;
`;
}

function cmdSeed(env: Record<string, string>, target: DatabaseTarget): void {
  const slotDate = formatDate(addDays(new Date(), 1));
  const sql = buildSeedSql(slotDate);
  const lines = runSql(sql, target.user, target.database);

  console.log(`[seed] 目标库：${target.database}（${target.host}:${target.port}）`);
  console.log(`[seed] 时段：${slotDate} ${SLOT_START}-${SLOT_END}`);
  console.log("[seed] ---------------- 数据 ----------------");
  for (const line of lines) {
    const [entity, id, created, detail] = line.split("|");
    const label = ENTITY_LABELS[entity] ?? entity;
    const action = created === "t" ? "新建" : "更新（已存在）";
    console.log(`[seed] ${label.padEnd(12, " ")} id=${id.padEnd(4, " ")} ${detail}  ${action}`);
  }

  const code = env.LOGIN_SMS_CODE || DEFAULT_LOGIN_CODE;
  console.log("[seed] ---------------- 登录账号 ----------------");
  console.log(
    `[seed] 客户       ${CUSTOMER_PHONE}   验证码 ${code}   （首次登录自动注册）`,
  );
  console.log(`[seed] 服务商     ${PROVIDER_ADMIN_PHONE}   验证码 ${code}`);
  console.log(`[seed] 平台管理员 ${PLATFORM_ADMIN_PHONE}   验证码 ${code}`);
  console.log(`[seed] 师傅       ${MASTER_PHONE}   验证码 ${code}`);
  console.log("[seed] ---------------- 前端 ----------------");
  console.log("[seed] 用户端   http://localhost:5173");
  console.log("[seed] 服务商后台 http://localhost:5174");
  console.log("[seed] 师傅端   http://localhost:5175");
}

// ---------------------------------------------------------------------
// clean
// ---------------------------------------------------------------------

function buildCleanSql(withOrders: boolean): string {
  const providerId = byName("service_provider", "name", PROVIDER_NAME);
  const categoryId = `(SELECT id FROM service_category WHERE name = ${lit(
    CATEGORY_NAME,
  )} AND parent_id IS NULL ORDER BY id LIMIT 1)`;
  const itemId = `(SELECT id FROM service_item WHERE name = ${lit(
    ITEM_NAME,
  )} AND category_id = ${categoryId} ORDER BY id LIMIT 1)`;
  const masterId = `(SELECT id FROM master WHERE user_id =
      (SELECT id FROM "user" WHERE phone = ${lit(MASTER_PHONE)}) ORDER BY id LIMIT 1)`;
  const seedUserIds = `(SELECT id FROM "user" WHERE phone IN
      (${lit(PROVIDER_ADMIN_PHONE)}, ${lit(MASTER_PHONE)}))`;

  const orderCleanup = withOrders
    ? `
-- 订单先删：order 引用 user / master / item / slot，都是 RESTRICT，不先删会挡住
WITH d AS (
    DELETE FROM "order"
     WHERE user_id IN ${seedUserIds}
        OR master_id = ${masterId}
        OR item_id = ${itemId}
        OR slot_id IN (SELECT id FROM schedule_slot WHERE item_id = ${itemId})
    RETURNING id
)
SELECT 'order', count(*)::text, '已删订单' FROM d;
`
    : "";

  return `
\\set ON_ERROR_STOP on
BEGIN;

-- 有订单引用种子数据时先把订单清掉（settlement_item 引用 order，也是 RESTRICT）
WITH d AS (
    DELETE FROM settlement_item
     WHERE order_id IN (SELECT id FROM "order"
                         WHERE user_id IN ${seedUserIds}
                            OR master_id = ${masterId}
                            OR item_id = ${itemId}
                            OR slot_id IN (SELECT id FROM schedule_slot WHERE item_id = ${itemId}))
    RETURNING id
)
SELECT 'settlement_item', count(*)::text, '已删结算明细' FROM d;

WITH d AS (
    DELETE FROM settlement
     WHERE provider_id = ${providerId}
    RETURNING id
)
SELECT 'settlement', count(*)::text, '已删结算单' FROM d;

${orderCleanup}
WITH d AS (
    DELETE FROM schedule_slot WHERE item_id = ${itemId} RETURNING id
)
SELECT 'schedule_slot', count(*)::text, '已删时段' FROM d;

WITH d AS (
    DELETE FROM service_item WHERE id = ${itemId} RETURNING id
)
SELECT 'service_item', count(*)::text, '已删服务项目' FROM d;

WITH d AS (
    DELETE FROM service_category WHERE id = ${categoryId} RETURNING id
)
SELECT 'service_category', count(*)::text, '已删品类' FROM d;

WITH d AS (
    DELETE FROM master WHERE id = ${masterId} RETURNING id
)
SELECT 'master', count(*)::text, '已删师傅' FROM d;

WITH d AS (
    DELETE FROM "user" WHERE phone IN (${lit(PROVIDER_ADMIN_PHONE)}, ${lit(MASTER_PHONE)},
                                        ${lit(PLATFORM_ADMIN_PHONE)})
    RETURNING id
)
SELECT 'user', count(*)::text, '已删账号' FROM d;

WITH d AS (
    DELETE FROM service_provider WHERE id = ${providerId} RETURNING id
)
SELECT 'service_provider', count(*)::text, '已删服务商' FROM d;

COMMIT;
`;
}

/** 统计还剩多少种子数据（clean 前后各跑一次，报「清干净了没」）。 */
function countSeedRows(target: DatabaseTarget): number {
  const sql = `
SELECT count(*) FROM service_provider WHERE name = ${lit(PROVIDER_NAME)}
UNION ALL
SELECT count(*) FROM "user" WHERE phone IN (${lit(PROVIDER_ADMIN_PHONE)}, ${lit(MASTER_PHONE)},
                                        ${lit(PLATFORM_ADMIN_PHONE)})
UNION ALL
SELECT count(*) FROM master WHERE real_name = ${lit(MASTER_NAME)}
UNION ALL
SELECT count(*) FROM service_category WHERE name = ${lit(CATEGORY_NAME)}
UNION ALL
SELECT count(*) FROM service_item WHERE name = ${lit(ITEM_NAME)}
UNION ALL
SELECT count(*) FROM schedule_slot WHERE item_id IN
    (SELECT id FROM service_item WHERE name = ${lit(ITEM_NAME)});
`;
  const lines = runSql(sql, target.user, target.database);
  return lines.reduce((sum, line) => sum + (Number(line.trim()) || 0), 0);
}

function cmdClean(env: Record<string, string>, target: DatabaseTarget, withOrders: boolean): void {
  console.log(`[clean] 目标库：${target.database}（${target.host}:${target.port}）`);
  const before = countSeedRows(target);
  if (before === 0) {
    console.log("[clean] 库里本来就没有种子数据，跳过。");
    return;
  }
  if (!withOrders) {
    const blocked = runSql(
      `SELECT count(*)::text FROM "order"
        WHERE user_id IN (SELECT id FROM "user" WHERE phone IN (${lit(
          PROVIDER_ADMIN_PHONE,
        )}, ${lit(MASTER_PHONE)}))
           OR master_id IN (SELECT id FROM master WHERE real_name = ${lit(MASTER_NAME)})
           OR item_id IN (SELECT id FROM service_item WHERE name = ${lit(ITEM_NAME)});`,
      target.user,
      target.database,
    );
    if (Number(blocked[0] ?? "0") > 0) {
      throw new Error(
        `有 ${blocked[0]} 笔订单还引用着种子数据（外键是 RESTRICT，删不掉）。\n` +
          "先把订单删掉再跑 make e2e-clean，或者跑 `make e2e-clean ARGS=--with-orders` 一并清掉相关订单。",
      );
    }
  }

  const lines = runSql(buildCleanSql(withOrders), target.user, target.database);
  for (const line of lines) {
    const [entity, count, note] = line.split("|");
    if (Number(count) > 0) {
      console.log(`[clean] ${(ENTITY_LABELS[entity] ?? entity).padEnd(12, " ")} ${note} ${count} 行`);
    }
  }
  const after = countSeedRows(target);
  if (after !== 0) {
    throw new Error(`还有 ${after} 行种子数据没清掉。`);
  }
  console.log("[clean] 种子数据已清空。");
}

// ---------------------------------------------------------------------
// 小工具
// ---------------------------------------------------------------------

function addDays(date: Date, days: number): Date {
  const d = new Date(date.getTime());
  d.setDate(d.getDate() + days);
  return d;
}

/** 本地时区的 YYYY-MM-DD（不用 toISOString，那是 UTC，会差一天）。 */
function formatDate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

// ---------------------------------------------------------------------
// 入口
// ---------------------------------------------------------------------

function main(): void {
  const args = process.argv.slice(2);
  const command = args[0] ?? "seed";
  const withOrders = args.includes("--with-orders");

  if (command !== "seed" && command !== "clean") {
    console.error(`用法：seed-cli.ts [seed|clean] [--with-orders]`);
    process.exit(2);
  }

  const env = readEnvFile(resolve(ROOT, ".env"));
  const target = resolveTarget(env);

  if (command === "seed") {
    cmdSeed(env, target);
  } else {
    cmdClean(env, target, withOrders);
  }
}

try {
  main();
} catch (err) {
  console.error(`[seed-cli] ${(err as Error).message}`);
  process.exit(1);
}
