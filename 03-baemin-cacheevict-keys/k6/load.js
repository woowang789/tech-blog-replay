import http from 'k6/http';
import { check } from 'k6';

// 상품 조회 부하를 걸어 둔 채, 정해진 시각에 전체 삭제(@CacheEvict(allEntries = true))를 한 번 부른다.
// 조회는 응답이 느려져도 초당 도착하는 요청 수가 유지되는 open model이다.
// 실제 사용자 트래픽처럼 "서버가 느려졌다고 요청이 줄지는 않는" 상황을 만든다.
export const options = {
  scenarios: {
    reads: {
      executor: 'constant-arrival-rate',
      exec: 'read',
      rate: Number(__ENV.RATE || 200),
      timeUnit: '1s',
      duration: __ENV.DURATION || '40s',
      // 조회가 멈춘 동안 기다리는 요청마다 VU 하나가 묶인다. 동기 300만 개에서 4초 가까이 멈춰 넉넉히 둔다
      preAllocatedVUs: 1500,
      maxVUs: 3000,
    },
    // 관리자가 캐시 전체 삭제 API를 한 번 부르는 상황
    evict: {
      executor: 'shared-iterations',
      exec: 'evictAll',
      vus: 1,
      iterations: 1,
      startTime: __ENV.EVICT_AT || '20s',
    },
  },
};

// 인기 상품 수. 조회는 1~HOT번 상품 중 하나를 고르고, 이 상품들은 모두 캐시에 들어 있다
const HOT = Number(__ENV.HOT || 1000);

export function read() {
  const id = Math.floor(Math.random() * HOT) + 1;
  const res = http.get(`http://localhost:8080/products/${id}`, { tags: { name: 'read' }, timeout: '60s' });
  check(res, { 'status 200': (r) => r.status === 200 });
}

export function evictAll() {
  const res = http.post('http://localhost:8080/experiments/evict-all', null, { tags: { name: 'evict-all' }, timeout: '120s' });
  check(res, { 'status 200': (r) => r.status === 200 });
}
