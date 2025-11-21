import logging

from .worker_agent import WorkerAgent

logger = logging.getLogger(__name__)

AGENT_TYPE = "analytics"
AGENT_DESCRIPTION = "Analyzes sales performance, slow movers, trends, pareto analysis, and stock coverage metrics"
TOOLS_EXAMPLE = """
## Few-shot Examples:

Query: "Show me top 10 best-selling items by revenue last month"
→ {"tool_calls": [{"tool_name": "analyze_top_performers", "parameters": {"from_date": "2025-10-01", "to_date": "2025-10-31", "metric": "revenue", "top_n": 10, "warehouses": ["Main Warehouse"], "channels": ["POS", "Online"]}}]}

Query: "Find slow-moving items with low sell-through rate"
→ {"tool_calls": [{"tool_name": "analyze_slow_movers", "parameters": {"from_date": "2025-09-01", "to_date": "2025-11-15", "top_n": 20, "min_days_on_sale": 30, "warehouses": ["Main Warehouse"], "min_stock_balance": 10}}]}

Query: "Compare sales growth between October and November"
→ {"tool_calls": [{"tool_name": "track_movers_shakers", "parameters": {"period_current": {"from": "2025-11-01", "to": "2025-11-15"}, "period_prev": {"from": "2025-10-01", "to": "2025-10-31"}, "metric": "qty", "top_n": 15}}]}

Query: "Perform pareto analysis for revenue contribution this quarter"
→ {"tool_calls": [{"tool_name": "perform_pareto_analysis", "parameters": {"from_date": "2025-09-01", "to_date": "2025-11-30", "metric": "revenue"}}]}

Query: "Analyze stock coverage for Electronics group in Main Warehouse"
→ {"tool_calls": [{"tool_name": "analyze_stock_coverage", "parameters": {"warehouses": ["Main Warehouse"], "item_groups": ["Electronics"], "lookback_days": 30}}]}

Query: "Show top performers by quantity and their stock coverage"
→ {"tool_calls": [{"tool_name": "analyze_top_performers", "parameters": {"from_date": "2025-10-01", "to_date": "2025-11-15", "metric": "qty", "top_n": 10, "warehouses": ["Main Warehouse"], "channels": ["POS"]}}, {"tool_name": "analyze_stock_coverage", "parameters": {"warehouses": ["Main Warehouse"], "lookback_days": 30, "top_n": 10}}]}
"""


class AnalyticsAgent(WorkerAgent):
    def __init__(self, **kwargs):
        super().__init__(
            agent_type=AGENT_TYPE,
            agent_description=AGENT_DESCRIPTION,
            examples=TOOLS_EXAMPLE,
            **kwargs,
        )
