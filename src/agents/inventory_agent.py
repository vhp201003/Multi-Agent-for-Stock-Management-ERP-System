import logging

from .worker_agent import WorkerAgent

logger = logging.getLogger(__name__)

AGENT_TYPE = "inventory"
AGENT_DESCRIPTION = "Manages inventory operations including stock checks, history analysis, transfer proposals, and health metrics"
TOOLS_EXAMPLE = """
## Few-shot Examples:

Query: "Check stock for LAPTOP-001"
→ {"tool_calls": [{"tool_name": "check_stock", "parameters": {"item_code": "LAPTOP-001"}}]}

Query: "Show Mouse stock in Main Warehouse and Store Warehouse"
→ {"tool_calls": [{"tool_name": "check_stock", "parameters": {"item_name": "Mouse", "warehouses": "Main Warehouse,Store Warehouse"}}]}

Query: "Stock movements for LAPTOP-001 last 60 days"
→ {"tool_calls": [{"tool_name": "retrieve_stock_history", "parameters": {"item_code": "LAPTOP-001", "days_back": 60}}]}

Query: "Transfer Mouse-Wireless to Store Warehouse"
→ {"tool_calls": [{"tool_name": "propose_transfer", "parameters": {"item_code": "Mouse-Wireless", "to_warehouse": "Store Warehouse"}}]}

Query: "Analyze inventory health for Main Warehouse and Store Warehouse"
→ {"tool_calls": [{"tool_name": "inventory_health", "parameters": {"warehouses": ["Main Warehouse", "Store Warehouse"], "horizon_days": 30}}]}

Query: "Check LAPTOP-001 stock and its history last 30 days"
→ {"tool_calls": [{"tool_name": "check_stock", "parameters": {"item_code": "LAPTOP-001"}}, {"tool_name": "retrieve_stock_history", "parameters": {"item_code": "LAPTOP-001", "days_back": 30}}]}
"""


class InventoryAgent(WorkerAgent):
    def __init__(self, **kwargs):
        super().__init__(
            agent_type=AGENT_TYPE,
            agent_description=AGENT_DESCRIPTION,
            examples=TOOLS_EXAMPLE,
            **kwargs,
        )
