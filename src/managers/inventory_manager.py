from src.managers.base_manager import BaseManager

AGENT_TYPE_INVENTORY = "inventory"
REDIS_URL = "redis://localhost:6379"


class InventoryManager(BaseManager):
    def __init__(self):
        super().__init__(AGENT_TYPE_INVENTORY, REDIS_URL)
