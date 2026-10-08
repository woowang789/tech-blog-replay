package replay.loggingoutage.logging;

import ch.qos.logback.classic.AsyncAppender;
import ch.qos.logback.classic.spi.ILoggingEvent;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanContext;

// 원문의 TraceAwareAsyncAppender. 표준 AsyncAppender를 상속해 append() 한 곳만 바꿨다.
// append()는 큐에 넣기 전, 아직 로그를 남긴 caller 스레드에서 불린다. 여기서 Span.current()를 읽으면 요청의 trace context가 보인다.
public class TraceAwareAsyncAppender extends AsyncAppender {

	@Override
	protected void append(ILoggingEvent event) {
		SpanContext context = Span.current().getSpanContext();
		ILoggingEvent toEnqueue = context.isValid()
				? new TraceStampedEvent(event, context.getTraceId(), context.getSpanId())
				: event;
		// 큐에 넣기, 큐가 찼을 때 버리기(discardingThreshold, neverBlock), 워커 스레드로 넘기기는 표준 구현 그대로 쓴다
		super.append(toEnqueue);
	}

}
