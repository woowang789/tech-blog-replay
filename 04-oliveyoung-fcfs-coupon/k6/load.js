import http from 'k6/http';
import exec from 'k6/execution';
import { check } from 'k6';
import { Counter } from 'k6/metrics';

// 선착순 쿠폰이 열린 뒤 발급 요청이 초당 RATE건씩 DURATION 동안 들어온다(1단계부터).
// 서버가 느려져도 도착 속도는 그대로인 open model이다. 요청마다 다른 사용자이고,
// 요청 수(RATE × DURATION)는 제한 수량보다 많게 두어 마감 뒤의 요청까지 섞인다
export const options = {
  scenarios: {
    issue: {
      executor: 'constant-arrival-rate',
      rate: Number(__ENV.RATE || 1000),
      timeUnit: '1s',
      duration: __ENV.DURATION || '10s',
      // 응답이 느려지는 동안 기다리는 요청마다 VU 하나가 묶인다. 모자라면 k6가 요청을 건너뛴다(dropped_iterations).
      // 앱이 0.5초쯤 멈추는 때가 있어(GC 등) 1초치 요청을 미리 만들어 둔다
      preAllocatedVUs: 1000,
      maxVUs: 3000,
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
