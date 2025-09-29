import redis

def set_key_value(redis_url: str = "redis://localhost:6379"):
    """Tạo và set các cặp key-value trong Redis."""
    redis_client = redis.from_url(redis_url, decode_responses=True)
    
    # Ví dụ set một số key-value
    redis_client.set("product:P001", "Stock: 100")
    redis_client.set("product:P002", "Stock: 50")
    redis_client.set("agent:inventory", "Active")
    
    print("Đã set các key-value: product:P001, product:P002, agent:inventory")
    
    # Lấy và in giá trị để kiểm tra
    print(f"product:P001: {redis_client.get('product:P001')}")
    print(f"product:P002: {redis_client.get('product:P002')}")
    print(f"agent:inventory: {redis_client.get('agent:inventory')}")
    
    redis_client.close()

if __name__ == "__main__":
    set_key_value()