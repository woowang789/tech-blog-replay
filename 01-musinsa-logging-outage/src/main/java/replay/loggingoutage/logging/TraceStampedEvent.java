package replay.loggingoutage.logging;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.classic.spi.IThrowableProxy;
import ch.qos.logback.classic.spi.LoggerContextVO;
import org.slf4j.Marker;
import org.slf4j.event.KeyValuePair;

// 원문의 TraceStampedEvent. 큐에 들어가는 로그 이벤트를 감싸서, caller 스레드에서 캡처한 trace_id와 span_id만 더 들고 간다.
// 나머지 동작은 모두 원본 이벤트에 그대로 위임한다.
public final class TraceStampedEvent implements ILoggingEvent {

	private final ILoggingEvent delegate;

	private final String traceId;

	private final String spanId;

	TraceStampedEvent(ILoggingEvent delegate, String traceId, String spanId) {
		this.delegate = delegate;
		this.traceId = traceId;
		this.spanId = spanId;
	}

	public String getTraceId() {
		return traceId;
	}

	public String getSpanId() {
		return spanId;
	}

	@Override
	public String getThreadName() {
		return delegate.getThreadName();
	}

	@Override
	public Level getLevel() {
		return delegate.getLevel();
	}

	@Override
	public String getMessage() {
		return delegate.getMessage();
	}

	@Override
	public Object[] getArgumentArray() {
		return delegate.getArgumentArray();
	}

	@Override
	public String getFormattedMessage() {
		return delegate.getFormattedMessage();
	}

	@Override
	public String getLoggerName() {
		return delegate.getLoggerName();
	}

	@Override
	public LoggerContextVO getLoggerContextVO() {
		return delegate.getLoggerContextVO();
	}

	@Override
	public IThrowableProxy getThrowableProxy() {
		return delegate.getThrowableProxy();
	}

	@Override
	public StackTraceElement[] getCallerData() {
		return delegate.getCallerData();
	}

	@Override
	public boolean hasCallerData() {
		return delegate.hasCallerData();
	}

	@Override
	public List<Marker> getMarkerList() {
		return delegate.getMarkerList();
	}

	@Override
	public Map<String, String> getMDCPropertyMap() {
		return delegate.getMDCPropertyMap();
	}

	@Override
	@Deprecated
	public Map<String, String> getMdc() {
		return delegate.getMDCPropertyMap();
	}

	@Override
	public long getTimeStamp() {
		return delegate.getTimeStamp();
	}

	@Override
	public int getNanoseconds() {
		return delegate.getNanoseconds();
	}

	@Override
	public Instant getInstant() {
		return delegate.getInstant();
	}

	@Override
	public long getSequenceNumber() {
		return delegate.getSequenceNumber();
	}

	@Override
	public List<KeyValuePair> getKeyValuePairs() {
		return delegate.getKeyValuePairs();
	}

	@Override
	public void prepareForDeferredProcessing() {
		delegate.prepareForDeferredProcessing();
	}

}
