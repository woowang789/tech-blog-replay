package replay.loggingoutage.logging;

import ch.qos.logback.classic.pattern.ClassicConverter;
import ch.qos.logback.classic.spi.ILoggingEvent;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanContext;

// OtelTraceIdConverter와 같은 방식으로 span_id를 읽는다.
public class OtelSpanIdConverter extends ClassicConverter {

	@Override
	public String convert(ILoggingEvent event) {
		if (event instanceof TraceStampedEvent stamped) {
			return stamped.getSpanId();
		}
		SpanContext context = Span.current().getSpanContext();
		return context.isValid() ? context.getSpanId() : "";
	}

}
