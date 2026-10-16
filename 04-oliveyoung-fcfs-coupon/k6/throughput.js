import http from 'k6/http';
import exec from 'k6/execution';
import { check } from 'k6';

// 발급 API의 처리량을 잰다(3단계). 사용자 VUS명이 응답을 받는 즉시 다음 요청을 보낸다(closed model).
// 제한 수량을 넉넉히 두어 모든 요청이 수량 검사를 통과하게 한다. 요청마다 다른 사용자다
export const options = {
  scenarios: {
    saturate: {
      executor: 'constant-vus',
      vus: Number(__ENV.VUS || 100),
      duration: __ENV.DURATION || '10s',
    },
  },
};

http.setResponseCallback(http.expectedStatuses(200, 409));

const COUPON = __ENV.COUPON || 'C001';

export default function () {
  const userId = exec.scenario.iterationInTest + 1;
  const res = http.post(`http://localhost:8080/coupons/${COUPON}/issue?userId=${userId}`, null,
    { tags: { name: 'issue' }, timeout: '60s' });
  check(res, { '200(발급 성공) 또는 409(마감)': (r) => r.status === 200 || r.status === 409 });
}
