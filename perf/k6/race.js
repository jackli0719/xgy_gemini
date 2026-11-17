// 并发压测：N 个 VU 抢**同一格**时段库存。
//
// 验证的是下单链路最关键的一条性质：**不超卖**。
// 100 个 VU 同时抢 5 格的库存，必须恰好 5 个人下单成功（201），
// 其余 95 个拿到 409（库存不足），数据库里 used == capacity == 5，
// 且这一格上的订单数也正好是 5。
//
// 这组跑之前**必须先跑 make perf-seed**：时段库存是种子种出来的，
// 重复跑这组会撞上「库存已经被上一轮吃掉」的 409（阈值会直接判失败，
// 这正是想要的行为——不能把上轮的结果当成本轮的结果）。
import { check } from 'k6';
import { scenario } from 'k6/execution';

import { MANIFEST, loginBatch, placeOrder } from './common.js';
import { renderSummary } from './summary.js';

const VUS = parseInt(__ENV.VUS || '100', 10);
const RACE = MANIFEST.race;

export const options = {
  setupTimeout: '120s',
  // 默认的 summaryTrendStats 不含 p(99)，这里显式要出来
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  scenarios: {
    race: {
      // 每个 VU 只下一次单：N 个 VU 一次性冲到同一格上，
      // 争抢窗口才够集中（跑多轮会把「抢库存」稀释成「慢慢下单」）
      executor: 'per-vu-iterations',
      vus: VUS,
      iterations: 1,
      exec: 'raceFlow',
      gracefulStop: '30s',
    },
  },
  thresholds: {
    // 成功数必须正好等于容量（5）——多了就是超卖，少了就是没跑满
    order_success: [`count==${RACE.capacity}`],
    // 一个 5xx 都不许有
    order_server_error: ['count==0'],
    order_other: ['count==0'],
    // 409 是预期结果（没抢到），不算 HTTP 错误
    http_req_failed: ['rate==0'],
    checks: ['rate==1'],
  },
};

export function setup() {
  if (MANIFEST.customers.length < VUS) {
    throw new Error(
      `客户数不够：需要 ${VUS} 个，manifest 里只有 ${MANIFEST.customers.length} 个。` +
        '加大 PERF_CUSTOMERS 后重新 make perf-seed。',
    );
  }
  const phones = MANIFEST.customers.slice(0, VUS).map((c) => c.phone);
  return { tokens: loginBatch(phones) };
}

export function raceFlow(data) {
  const index = scenario.iterationInTest;
  const customer = MANIFEST.customers[index];
  const res = placeOrder(
    data.tokens[index],
    { item_id: RACE.item_id, slot_id: RACE.slot_id },
    customer.address_id,
  );
  check(res, {
    '下单返回 201（抢到）或 409（没抢到）': (r) => r.status === 201 || r.status === 409,
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
  return {
    stdout: renderSummary(
      data,
      `并发压测：${VUS} VU 抢 ${RACE.capacity} 格库存（slot_id=${RACE.slot_id}）`,
      [
        `竞态时段          : item_id=${RACE.item_id} slot_id=${RACE.slot_id} ` +
          `date=${RACE.date} ${RACE.start_time} 容量=${RACE.capacity}`,
        `平均吞吐          : ${Number(qps).toFixed(1)} req/s（HTTP 请求 ${httpReqs} 条）`,
        '超卖判定          : 由 perf/check_oversell.py 查库给出（used vs capacity vs 订单数）',
      ],
    ),
    'out/race-summary.json': JSON.stringify(data, null, 2),
  };
}
