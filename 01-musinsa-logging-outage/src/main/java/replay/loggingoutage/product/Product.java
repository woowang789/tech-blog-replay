package replay.loggingoutage.product;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;

@Entity
public class Product {

	@Id
	private Long id;

	private String name;

	private long price;

	protected Product() {
	}

	public Long getId() {
		return id;
	}

	public String getName() {
		return name;
	}

	public long getPrice() {
		return price;
	}

}
