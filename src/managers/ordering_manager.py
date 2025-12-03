from src.agents.ordering_agent import AGENT_TYPE
from src.managers.base_manager import BaseManager


class OrderingManager(BaseManager):
    def __init__(self):
        super().__init__(AGENT_TYPE)
