package replay.fcfscoupon.issue;

import org.springframework.amqp.core.Queue;
import org.springframework.amqp.support.converter.JacksonJsonMessageConverter;
import org.springframework.amqp.support.converter.MessageConverter;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration(proxyBeanMethods = false)
class RabbitConfig {

	// 발급 요청 큐. 앱이 뜰 때 RabbitAdmin이 선언한다. 기본 exchange에 큐 이름으로 라우팅한다
	@Bean
	Queue issueQueue(@Value("${replay.queue-name}") String queueName) {
		return new Queue(queueName, true);
	}

	// 메시지(IssueMessage)를 JSON으로 싣는다. RabbitTemplate과 리스너 양쪽에 자동으로 적용된다
	@Bean
	MessageConverter jsonMessageConverter() {
		return new JacksonJsonMessageConverter();
	}

}
