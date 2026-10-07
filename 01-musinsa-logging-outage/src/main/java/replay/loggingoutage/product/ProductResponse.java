package replay.loggingoutage.product;

public record ProductResponse(long id, String name, long price) {

	static ProductResponse from(Product product) {
		return new ProductResponse(product.getId(), product.getName(), product.getPrice());
	}

}
