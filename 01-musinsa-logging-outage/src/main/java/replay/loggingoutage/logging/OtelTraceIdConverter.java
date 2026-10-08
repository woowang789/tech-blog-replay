package replay.loggingoutage.logging;

import ch.qos.logback.classic.pattern.ClassicConverter;
import ch.qos.logback.classic.spi.ILoggingEvent;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanContext;

// 원문의 표준 로깅 라이브러리처럼, 로그를 문자열로 만드는 순간 Span.current()에서 trace_id를 읽는다.
// Span.current()는 지금 실행 중인 스레드의 컨텍스트를 보므로, 이 코드가 어느 스레드에서 도느냐에 따라 값이 달라진다.
// TraceAwareAsyncAppender를 거친 이벤트면 Span.current()를 다시 부르지 않고 caller 스레드에서 캡처해 둔 값을 쓴다.
public class OtelTraceIdConverter extends ClassicConverter {

	@Override
	public String convert(ILoggingEvent event) {
		if (event instanceof TraceStampedEvent stamped) {
			return stamped.getTraceId();
		}
		SpanContext context = Span.current().getSpanContext();
		return context.isValid() ? context.getTraceId() : "";
	}

}
