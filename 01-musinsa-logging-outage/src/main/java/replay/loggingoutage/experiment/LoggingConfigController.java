package replay.loggingoutage.experiment;

import java.util.LinkedHashMap;
import java.util.Map;

import ch.qos.logback.classic.AsyncAppender;
import ch.qos.logback.classic.LoggerContext;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.Appender;
import ch.qos.logback.core.spi.AppenderAttachable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

// 3단계 스위치(출력 방식)가 실제로 적용됐는지 확인한다.
// 루트 로거에 붙은 appender와, 그 안에 붙은 appender의 설정을 그대로 보여 준다.
@RestController
@RequestMapping("/experiments")
public class LoggingConfigController {

	@GetMapping("/logging-config")
	public Map<String, Object> loggingConfig() {
		LoggerContext context = (LoggerContext) LoggerFactory.getILoggerFactory();
		return describeAppenders(context.getLogger(Logger.ROOT_LOGGER_NAME));
	}

	private Map<String, Object> describeAppenders(AppenderAttachable<ILoggingEvent> attachable) {
		Map<String, Object> appenders = new LinkedHashMap<>();
		attachable.iteratorForAppenders().forEachRemaining(appender -> appenders.put(appender.getName(), describe(appender)));
		return appenders;
	}

	private Map<String, Object> describe(Appender<ILoggingEvent> appender) {
		Map<String, Object> info = new LinkedHashMap<>();
		info.put("class", appender.getClass().getName());
		if (appender instanceof AsyncAppender async) {
			info.put("queueSize", async.getQueueSize());
			info.put("discardingThreshold", async.getDiscardingThreshold());
			info.put("neverBlock", async.isNeverBlock());
			info.put("appenders", describeAppenders(async));
		}
		return info;
	}

}
