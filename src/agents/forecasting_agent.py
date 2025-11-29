import logging

from .worker_agent import WorkerAgent

logger = logging.getLogger(__name__)

AGENT_TYPE = "forecasting"
AGENT_DESCRIPTION = (
    "Specializes in sales forecasting and demand prediction using historical data"
)
TOOLS_EXAMPLE = """
## Few-shot Examples:

Query: "Forecast sales for RCK-0128 for next 2 months"
→ {"tool_calls": [{"tool_name": "predict_sales_forecast", "parameters": {"item_code": "RCK-0128", "months": 2}}]}

Query: "Predict demand for LAPTOP-001 for next 3 months"
→ {"tool_calls": [{"tool_name": "predict_sales_forecast", "parameters": {"item_code": "LAPTOP-001", "months": 3}}]}

Query: "What is the sales outlook for Mouse-Wireless?"
→ {"tool_calls": [{"tool_name": "predict_sales_forecast", "parameters": {"item_code": "Mouse-Wireless", "months": 2}}]}
"""


class ForecastingAgent(WorkerAgent):
    def __init__(self, **kwargs):
        super().__init__(
            agent_type=AGENT_TYPE,
            agent_description=AGENT_DESCRIPTION,
            examples=TOOLS_EXAMPLE,
            **kwargs,
        )
