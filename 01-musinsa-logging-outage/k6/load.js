import http from 'k6/http';
import { check } from 'k6';

// 응답이 느려져도 초당 도착하는 요청 수가 유지되는 open model.
// 실제 사용자 트래픽처럼 "서버가 느려졌다고 요청이 줄지는 않는" 상황을 만든다.
export const options = {
  scenarios: {
    products: {
      executor: 'constant-arrival-rate',
      rate: Number(__ENV.RATE || 50),
      timeUnit: '1s',
      duration: __ENV.DURATION || '3m',
      preAllocatedVUs: 200,
      maxVUs: 5000,
    },
  },
};

export default function () {
  const id = Math.floor(Math.random() * 1000) + 1;
  const res = http.get(`http://localhost:8080/products/${id}`, { timeout: '120s' });
  check(res, { 'status 200': (r) => r.status === 200 });
}
