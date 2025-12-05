from src.managers.base_manager import BaseManager

# Agent types that need managers
MANAGED_AGENT_TYPES = ["inventory", "analytics", "forecasting", "ordering"]


def create_manager(agent_type: str) -> BaseManager:
    if agent_type not in MANAGED_AGENT_TYPES:
        raise ValueError(
            f"Unknown agent type: {agent_type}. Valid types: {MANAGED_AGENT_TYPES}"
        )
    return BaseManager(agent_type=agent_type)


# Backward compatibility - class aliases for type hints if needed
class InventoryManager(BaseManager):
    def __init__(self):
        super().__init__("inventory")


class AnalyticsManager(BaseManager):
    def __init__(self):
        super().__init__("analytics")


class ForecastingManager(BaseManager):
    def __init__(self):
        super().__init__("forecasting")


class OrderingManager(BaseManager):
    def __init__(self):
        super().__init__("ordering")


__all__ = [
    "BaseManager",
    "create_manager",
    "MANAGED_AGENT_TYPES",
    # Backward compat
    "InventoryManager",
    "AnalyticsManager",
    "ForecastingManager",
    "OrderingManager",
]
