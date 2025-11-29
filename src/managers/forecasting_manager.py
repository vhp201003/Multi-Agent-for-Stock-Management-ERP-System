from src.agents.forecasting_agent import AGENT_TYPE
from src.managers.base_manager import BaseManager


class ForecastingManager(BaseManager):
    def __init__(self):
        super().__init__(AGENT_TYPE)
