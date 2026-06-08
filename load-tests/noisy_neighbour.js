import http from 'k6/http';
import { check } from 'k6';

export const options = {
  scenarios: {
    tenant_a_aggressive: {
      executor: 'constant-arrival-rate',
      exec: 'hitA',
      rate: 20, timeUnit: '1s',
      duration: '60s',
      preAllocatedVUs: 20,
    },
    tenant_b_polite: {
      executor: 'constant-arrival-rate',
      exec: 'hitB',
      rate: 5, timeUnit: '1s',
      duration: '60s',
      preAllocatedVUs: 5,
    },
  },
};

const body = JSON.stringify({
  model: 'local-llama3',
  messages: [{ role: 'user', content: 'hi' }],
  max_tokens: 100,
});

export function hitA() {
  const r = http.post('http://localhost:8000/v1/chat/completions', body, {
    headers: { 'Content-Type': 'application/json', 'X-API-Key': __ENV.KEY_A },
  });
  check(r, { 'a status': (r) => r.status === 200 || r.status === 429 });
}

export function hitB() {
  const r = http.post('http://localhost:8000/v1/chat/completions', body, {
    headers: { 'Content-Type': 'application/json', 'X-API-Key': __ENV.KEY_B },
  });
  check(r, { 'b status': (r) => r.status === 200 || r.status === 429 });
}