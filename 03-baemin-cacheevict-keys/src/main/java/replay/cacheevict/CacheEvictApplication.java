package replay.cacheevict;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cache.annotation.EnableCaching;

@EnableCaching
@SpringBootApplication
public class CacheEvictApplication {

	public static void main(String[] args) {
		SpringApplication.run(CacheEvictApplication.class, args);
	}

}
