// 压测公共件：登录、下单、指标、汇总输出。
//
// 三端共用一份逻辑，避免两个脚本各写一遍后参数口径对不上。
//
// 关键约定：
// - **manifest 由 seed 脚本生成**（perf/manifest.json）：时段 id、客户手机号、
//   地址 id 都在里面。k6 不去猜 id，也不靠「先查列表再挑一个」——
//   那样每次跑挑到的时段不一样，结果没法互相比较。
// - **身份只从 token 来**：每个 VU 拿自己的 token 下单，
//   请求体里不带 user_id（后端 schema 会 422 掉）。
import http from 'k6/http';
import { Counter, Trend } from 'k6/metrics';

export const BASE_URL = __ENV.BASE_URL || 'http://api:8000';
export const SMS_CODE = __ENV.SMS_CODE || '123456';
export const MANIFEST_PATH = __ENV.MANIFEST_PATH || '/perf/manifest.json';

// open() 只能在 init 阶段调（模块顶层），不能在运行时函数里调
export const MANIFEST = JSON.parse(open(MANIFEST_PATH));

// ---- 指标 -----------------------------------------------------------
// 用自定义指标而不是 http_req_duration：后者把 setup 阶段的登录也算进去，
// 压的是「下单」这一个接口时，分位数必须是下单自己的耗时。
export const orderDuration = new Trend('order_duration', true);
export const orderRequests = new Counter('order_requests');
export const orderSuccess = new Counter('order_success');
export const orderConflict = new Counter('order_conflict');
export const orderServerError = new Counter('order_server_error');
export const orderOther = new Counter('order_other');

export function authHeaders(token) {
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  };
}

/** 批量登录（setup 阶段用）。返回与 phones 等长的 token 数组。 */
export function loginBatch(phones) {
  const requests = phones.map((phone) => ({
    method: 'POST',
    url: `${BASE_URL}/api/v1/auth/login`,
    body: JSON.stringify({ phone, code: SMS_CODE }),
    params: { headers: { 'Content-Type': 'application/json' } },
  }));
  const responses = http.batch(requests);
  return responses.map((res, i) => {
    if (res.status !== 200) {
      throw new Error(
        `登录失败 phone=${phones[i]} status=${res.status} body=${res.body}`,
      );
    }
    return res.json('access_token');
  });
}

/**
 * 下单。
 *
 * 期望状态码是 201（抢到）与 409（没抢到）——竞态测试里 409 是**预期结果**，
 * 不是错误，所以用 expectedStatuses 把它们排除在 http_req_failed 之外；
 * 真出现 5xx 时 http_req_failed 才会亮。
 */
export function placeOrder(token, slot, addressId) {
  const res = http.post(
    `${BASE_URL}/api/v1/orders`,
    JSON.stringify({
      item_id: slot.item_id,
      slot_id: slot.slot_id,
      address_id: addressId,
    }),
    {
      headers: authHeaders(token),
      responseCallback: http.expectedStatuses(201, 409),
      tags: { op: 'place_order' },
    },
  );

  orderRequests.add(1);
  orderDuration.add(res.timings.duration);
  if (res.status === 201) {
    orderSuccess.add(1);
  } else if (res.status === 409) {
    orderConflict.add(1);
  } else if (res.status >= 500) {
    orderServerError.add(1);
  } else {
    orderOther.add(1);
  }
  return res;
}

/** 从负载池里取一个时段（按全局迭代序号轮转，保证不同迭代尽量不撞同一格）。 */
export function loadSlotFor(iterationIndex) {
  const pool = MANIFEST.load_slots;
  return pool[iterationIndex % pool.length];
}
