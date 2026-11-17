// 压测结果汇总输出。
//
// k6 自带的 text summary 好看，但「下单这一个接口」的 P50/P95/P99
// 会被 setup 阶段的登录请求稀释，所以这里自己出一份：
// 只统计下单接口的耗时，外加一眼能看的成功 / 冲突 / 5xx 计数与错误率。
export function fmtMs(value) {
  if (value === undefined || value === null) {
    return 'n/a';
  }
  return Number(value).toFixed(1);
}

export function fmtPct(rate) {
  if (rate === undefined || rate === null) {
    return 'n/a';
  }
  return (Number(rate) * 100).toFixed(2);
}

export function counterValue(metrics, name) {
  const metric = metrics[name];
  if (!metric || !metric.values) {
    return 0;
  }
  return metric.values.count || 0;
}

export function renderSummary(data, title, extraLines) {
  const metrics = data.metrics || {};
  const dur = (metrics.order_duration && metrics.order_duration.values) || {};
  const failed =
    metrics.http_req_failed && metrics.http_req_failed.values
      ? metrics.http_req_failed.values.rate
      : 0;
  const httpReqs =
    metrics.http_reqs && metrics.http_reqs.values
      ? metrics.http_reqs.values.count
      : 0;
  const checks =
    metrics.checks && metrics.checks.values ? metrics.checks.values.rate : null;

  const lines = [];
  lines.push('');
  lines.push(`===== ${title} =====`);
  lines.push(`下单请求数          : ${counterValue(metrics, 'order_requests')}`);
  lines.push(`HTTP 总请求数       : ${httpReqs}`);
  lines.push(`成功 201            : ${counterValue(metrics, 'order_success')}`);
  lines.push(`冲突 409            : ${counterValue(metrics, 'order_conflict')}`);
  lines.push(`服务端错 5xx        : ${counterValue(metrics, 'order_server_error')}`);
  lines.push(`其他非预期状态       : ${counterValue(metrics, 'order_other')}`);
  lines.push(
    `下单耗时 p50/p95/p99 : ${fmtMs(dur.med)} / ${fmtMs(dur['p(95)'])} / ` +
      `${fmtMs(dur['p(99)'])} ms（max ${fmtMs(dur.max)} ms）`,
  );
  lines.push(`HTTP 错误率         : ${fmtPct(failed)}%`);
  if (checks !== null) {
    lines.push(`断言通过率          : ${fmtPct(checks)}%`);
  }
  if (extraLines && extraLines.length) {
    lines.push('');
    for (const line of extraLines) {
      lines.push(line);
    }
  }
  lines.push('');
  return lines.join('\n');
}
