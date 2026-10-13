package replay.cacheevict.product;

import java.io.Serializable;

// 캐시에 담는 상품. Spring Boot의 Redis 캐시는 값을 JDK 직렬화로 저장해서 Serializable이어야 한다
public record Product(long id, String name) implements Serializable {

}
