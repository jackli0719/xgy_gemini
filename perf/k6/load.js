// 基线压测：单接口（POST /api/v1/orders）的 QPS 与延迟。
//
// 两种模式：
//
// - 默认（per-vu-iterations）：VUS 个用户各下一次单，**同时**打出去。
//   必测项「500 VU 下单」走的就是这个模式。
// - 恒定到达率（设 RATE 环境变量）：rate req/s 匀速打一段时间，
//   用来量单接口在稳定压力下的 QPS 上限与延迟分布。
//
// 每个迭代用一格**独立**的时段库存（负载池里轮转），
// 这样测到的是下单链路本身，不是「库存抢没了」的 409。
import { check } from 'k6';
import { scenario } from 'k6/execution';

import { MANIFEST, loadSlotFor, loginBatch, placeOrder } from './common.js';
import { renderSummary } from './summary.js';

const VUS = parseInt(__ENV.VUS || '500', 10);
const RATE = __ENV.RATE ? parseInt(__ENV.RATE, 10) : null;
const DURATION = __ENV.DURATION || '30s';
const POOL_CAPACITY = MANIFEST.load_slots.length * MANIFEST.slot_capacity;

// 恒定到达率模式下要打多少个请求（把 '30s' 这种时长解析成秒）
function durationSeconds(text) {
  const match = /^(\d+)([smh])$/.exec(text);
  if (!match) {
    return Number(text) || 0;
  }
  const value = parseInt(match[1], 10);
  if (match[2] === 'm') {
    return value * 60;
  }
  if (match[2] === 'h') {
    return value * 3600;
  }
  return value;
}

const PLANNED = RATE ? RATE * durationSeconds(DURATION) : VUS;

export const options = {
  setupTimeout: '180s',
  // 默认的 summaryTrendStats 不含 p(99)，这里显式要出来
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  scenarios: {
    load: RATE
      ? {
          executor: 'constant-arrival-rate',
          rate: RATE,
          timeUnit: '1s',
          duration: DURATION,
          preAllocatedVUs: parseInt(__ENV.PRE_VUS || '50', 10),
          maxVUs: parseInt(__ENV.MAX_VUS || '500', 10),
          exec: 'orderFlow',
          gracefulStop: '30s',
        }
      : {
          executor: 'per-vu-iterations',
          vus: VUS,
          iterations: 1,
          exec: 'orderFlow',
          gracefulStop: '60s',
        },
  },
  thresholds: {
    // 每个请求都必须下单成功：这条链路上一个 409 / 4xx 都不该有
    order_success: [`count==${PLANNED}`],
    order_conflict: ['count==0'],
    order_server_error: ['count==0'],
    order_other: ['count==0'],
    http_req_failed: ['rate==0'],
    // 下单接口自己的 P95（不含 setup 阶段的登录）
    order_duration: ['p(95)<2000'],
    checks: ['rate==1'],
  },
};

export function setup() {
  if (PLANNED > MANIFEST.customers.length) {
    throw new Error(
      `客户数不够：这一轮要下 ${PLANNED} 单，manifest 里只有 ${MANIFEST.customers.length} 个客户。` +
        '加大 PERF_CUSTOMERS 后重新 make perf-seed。',
    );
  }
  if (PLANNED > POOL_CAPACITY) {
    throw new Error(
      `时段库存不够：这一轮要下 ${PLANNED} 单，负载池总容量只有 ${POOL_CAPACITY}。` +
        '加大 PERF_SLOTS_PER_ITEM / PERF_SLOT_CAPACITY / PERF_CUSTOMERS 后重新 make perf-seed。',
    );
  }
  const phones = MANIFEST.customers.slice(0, PLANNED).map((c) => c.phone);
  return { tokens: loginBatch(phones) };
}

export function orderFlow(data) {
  const index = scenario.iterationInTest;
  const customer = MANIFEST.customers[index];
  const slot = loadSlotFor(index);
  const res = placeOrder(data.tokens[index], slot, customer.address_id);
  check(res, {
    '下单返回 201': (r) => r.status === 201,
  });
}

export function handleSummary(data) {
  const metrics = data.metrics || {};
  const httpReqs =
    metrics.http_reqs && metrics.http_reqs.values
      ? metrics.http_reqs.values.count
      : 0;
  const qps =
    metrics.http_reqs && metrics.http_reqs.values
      ? metrics.http_reqs.values.rate
      : 0;
  const mode = RATE ? `恒定到达率 ${RATE} req/s × ${DURATION}` : `${VUS} VU 同时下单`;
  return {
    stdout: renderSummary(data, `基线压测：下单接口（${mode}）`, [
      `平均吞吐          : ${Number(qps).toFixed(1)} req/s（HTTP 请求 ${httpReqs} 条）`,
      `负载池            : ${MANIFEST.load_slots.length} 格时段，总容量 ${POOL_CAPACITY} 单`,
    ]),
    'out/load-summary.json': JSON.stringify(data, null, 2),
  };
}
