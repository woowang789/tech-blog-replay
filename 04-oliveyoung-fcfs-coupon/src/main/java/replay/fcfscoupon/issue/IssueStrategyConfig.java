package replay.fcfscoupon.issue;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import replay.fcfscoupon.experiment.FaultInjector;

// 스위치 ISSUE_MODE(replay.issue-mode)로 수량을 다루는 방식을 고른다(3단계). COMPENSATE(replay.compensate)는 4단계의 보상 스위치다
@Configuration(proxyBeanMethods = false)
class IssueStrategyConfig {

	@Bean
	IssueStrategy issueStrategy(@Value("${replay.issue-mode}") String mode, @Value("${replay.compensate}") boolean compensate,
			IssueCountStore counts, FaultInjector faults) {
		return switch (mode) {
			case "original" -> new OriginalStrategy(counts);
			case "precharge" -> new PrechargeStrategy(counts);
			case "lua" -> new LuaStrategy(counts);
			case "double-counter" -> new DoubleCounterStrategy(counts, faults, compensate);
			default -> throw new IllegalArgumentException(
					"모르는 issue-mode: " + mode + " (original, precharge, lua, double-counter 중 하나)");
		};
	}

}
