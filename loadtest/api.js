import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = __ENV.TARGET_URL || 'http://127.0.0.1:8001';
const VIEWER_KEY = __ENV.VIEWER_API_KEY || 'netwatch-viewer-secret-key-456';

export const options = {
  stages: [
    { duration: '3s', target: 5 },
    { duration: '10s', target: 15 },
    { duration: '3s', target: 0 },
  ],
  thresholds: {
    http_req_failed: ['rate<0.02'],
    http_req_duration: ['p(95)<500', 'p(99)<1000'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(95)', 'p(99)'],
};

const headers = {
  'X-API-Key': VIEWER_KEY,
  'Accept': 'application/json',
};

export default function () {
  // 1. GET /api/summary
  const resSummary = http.get(`${BASE_URL}/api/summary`, { headers });
  check(resSummary, {
    'summary status is 200': (r) => r.status === 200,
    'summary has targets': (r) => r.json('total_targets') !== undefined,
  });

  // 2. GET /api/results
  const resResults = http.get(`${BASE_URL}/api/results?limit=20`, { headers });
  check(resResults, {
    'results status is 200': (r) => r.status === 200,
    'results is array': (r) => Array.isArray(r.json('items') || r.json()),
  });

  // 3. GET /api/targets
  const resTargets = http.get(`${BASE_URL}/api/targets`, { headers });
  check(resTargets, {
    'targets status is 200': (r) => r.status === 200,
  });

  sleep(0.1);
}

export function handleSummary(data) {
  const reqs = data.metrics.http_reqs ? data.metrics.http_reqs.values.count : 0;
  const rps = data.metrics.http_reqs ? data.metrics.http_reqs.values.rate : 0;
  const p95 = data.metrics.http_req_duration ? data.metrics.http_req_duration.values['p(95)'] : 0;
  const p99 = data.metrics.http_req_duration ? data.metrics.http_req_duration.values['p(99)'] : 0;
  const failRate = data.metrics.http_req_failed ? data.metrics.http_req_failed.values.rate : 0;

  const summary = {
    timestamp: new Date().toISOString(),
    target_url: BASE_URL,
    total_requests: reqs,
    requests_per_second: Math.round(rps * 100) / 100,
    p95_latency_ms: Math.round(p95 * 100) / 100,
    p99_latency_ms: Math.round(p99 * 100) / 100,
    error_rate: Math.round(failRate * 10000) / 10000,
  };

  const output = [
    '==================================================================',
    '                  NETWATCH K6 LOAD TEST SUMMARY                   ',
    '==================================================================',
    ` Target URL:             ${BASE_URL}`,
    ` Total HTTP Requests:    ${summary.total_requests}`,
    ` Throughput:             ${summary.requests_per_second} req/s (RPS)`,
    ` Latency p95:            ${summary.p95_latency_ms} ms`,
    ` Latency p99:            ${summary.p99_latency_ms} ms`,
    ` Error Rate:             ${(summary.error_rate * 100).toFixed(2)} %`,
    '==================================================================',
  ].join('\n');

  console.log('\n' + output + '\n');

  return {
    'stdout': output + '\n',
    'loadtest/last-run.json': JSON.stringify(summary, null, 2) + '\n',
  };
}
