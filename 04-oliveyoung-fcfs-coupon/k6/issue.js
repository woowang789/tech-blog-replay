import http from 'k6/http';
import exec from 'k6/execution';
import { check } from 'k6';
import { Counter } from 'k6/metrics';

// 선착순 쿠폰이 열리는 순간처럼, 서로 다른 사용자가 같은 쿠폰의 발급을 한꺼번에 요청한다.
// 요청 수(REQUESTS)는 제한 수량보다 많게 두어, 마감된 뒤의 요청까지 섞인다. 사용자마다 한 번씩만 요청한다
export const options = {
  scenarios: {
    burst: {
      executor: 'shared-iterations',
      vus: Number(__ENV.VUS || 100),
      iterations: Number(__ENV.REQUESTS || 300),
      maxDuration: '5m',
    },
  },
};

// 마감(409)은 정상 응답이라 실패로 세지 않는다
http.setResponseCallback(http.expectedStatuses(200, 409));

const COUPON = __ENV.COUPON || 'C001';
const successResponses = new Counter('issue_success_responses');
const soldOutResponses = new Counter('issue_sold_out_responses');

export default function () {
  const userId = exec.scenario.iterationInTest + 1;
  const res = http.post(`http://localhost:8080/coupons/${COUPON}/issue?userId=${userId}`, null,
    { tags: { name: 'issue' }, timeout: '60s' });
  check(res, { '200(발급 성공) 또는 409(마감)': (r) => r.status === 200 || r.status === 409 });
  if (res.status === 200) {
    successResponses.add(1);
  } else if (res.status === 409) {
    soldOutResponses.add(1);
  }
}
