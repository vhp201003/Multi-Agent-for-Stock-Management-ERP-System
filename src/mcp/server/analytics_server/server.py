import logging
from typing import Dict, List, Optional

from pydantic import Field

from src.communication import get_erpnext_connection
from src.mcp.server.base_server import BaseMCPServer, ServerConfig
from src.typing.mcp.analytics import (
    MoversShakersOutput,
    ParetoAnalysisOutput,
    SalesOrderStatsOutput,
    SlowMoversOutput,
    StockCoverageOutput,
    TopPerformersOutput,
)

logger = logging.getLogger(__name__)


class AnalyticsServerConfig(ServerConfig):
    erpnext_url: str = Field(
        default="http://localhost:8001", description="ERPNext base URL"
    )
    erpnext_api_key: Optional[str] = Field(default=None, description="ERPNext API key")
    erpnext_api_secret: Optional[str] = Field(
        default=None, description="ERPNext API secret"
    )
    default_lookback_days: int = Field(
        default=30, ge=1, le=365, description="Default lookback period in days"
    )
    default_top_n: int = Field(
        default=10, ge=1, description="Default number of items to return"
    )
    pareto_cutoff: float = Field(
        default=0.8, ge=0.0, le=1.0, description="Pareto analysis cutoff percentage"
    )


class AnalyticsMCPServer(BaseMCPServer):
    def __init__(self, config: AnalyticsServerConfig):
        super().__init__(config)
        self.analytics_config = config
        self.erpnext = get_erpnext_connection()

    def setup(self) -> None:
        self.logger.info("Setting up Analytics MCP Server tools...")

        self.add_tool(
            self.analyze_top_performers,
            name="analyze_top_performers",
            description="Identify best-selling items by quantity or revenue during a period. Defaults to last 30 days, all warehouses, and POS+Online channels. Returns top items with sales trends and market share percentages.",
            structured_output=True,
        )

        self.add_tool(
            self.analyze_slow_movers,
            name="analyze_slow_movers",
            description="Find low-velocity items with current stock. Analyzes sell-through rate, profitability (GMROI), and suggests markdown or bundling actions. Only includes items with existing stock and minimum age (default: 30+ days).",
            structured_output=True,
        )

        self.add_tool(
            self.track_movers_shakers,
            name="track_movers_shakers",
            description="Compare sales performance between two time periods to identify items with biggest growth or decline. Defaults to current month vs previous month. Shows percentage change in quantity or revenue.",
            structured_output=True,
        )

        self.add_tool(
            self.perform_pareto_analysis,
            name="perform_pareto_analysis",
            description="Apply 80/20 rule to identify which items drive 80% of revenue. Defaults to last 30 days. Shows cumulative contribution percentage and count of vital items.",
            structured_output=True,
        )

        self.add_tool(
            self.analyze_stock_coverage,
            name="analyze_stock_coverage",
            description="Calculate how many days current inventory will last based on sales velocity. Defaults to last 30 days of sales. Auto-suggests reorder actions for low-coverage items and markdown for overstocked items.",
            structured_output=True,
        )

        self.add_tool(
            self.get_sales_order_stats,
            name="get_sales_order_stats",
            description="Aggregate sales order counts and revenue by day, week, month, or year. Defaults to last 90 days by month. Optionally filter by order status (e.g., Completed, To Deliver and Bill).",
            structured_output=True,
        )

        self.logger.info("✅ All analytics tools registered successfully")

    async def analyze_top_performers(
        self,
        from_date: Optional[str] = Field(
            None, description="Start date (YYYY-MM-DD). None/empty = last 30 days"
        ),
        to_date: Optional[str] = Field(
            None, description="End date (YYYY-MM-DD). None/empty = today"
        ),
        metric: str = Field(
            default="revenue",
            description="Rank by: 'qty' (quantity sold) or 'revenue' (total value)",
        ),
        top_n: int = Field(default=10, ge=1, description="Top N items to return"),
        warehouses: List[str] = Field(
            default_factory=list,
            description="Warehouse filter. Empty = all warehouses",
        ),
        channels: List[str] = Field(
            default=["POS", "Online"],
            description="Sales channels (e.g. POS, Online, Wholesale)",
        ),
        exclude_returns: bool = Field(
            default=True, description="Skip return transactions"
        ),
        merge_variants: bool = Field(
            default=False, description="Group variants under parent item"
        ),
    ) -> TopPerformersOutput:
        try:
            response = await self._fetch_top_performers(
                from_date,
                to_date,
                metric,
                top_n,
                warehouses,
                channels,
                exclude_returns,
                merge_variants,
            )
            return TopPerformersOutput(**response)
        except Exception as e:
            self.logger.error(f"Error in analyze_top_performers: {e}", exc_info=True)
            raise

    async def analyze_slow_movers(
        self,
        from_date: Optional[str] = Field(
            None, description="Start date (YYYY-MM-DD). None/empty = 90 days ago"
        ),
        to_date: Optional[str] = Field(
            None, description="End date (YYYY-MM-DD). None/empty = today"
        ),
        top_n: int = Field(
            default=20, ge=1, description="Number of slowest items to return"
        ),
        min_days_on_sale: int = Field(
            default=30, ge=0, description="Item must exist for at least this many days"
        ),
        warehouses: List[str] = Field(
            default_factory=list,
            description="Warehouse filter. Empty = all warehouses",
        ),
        min_stock_balance: float = Field(
            default=0.0, ge=0, description="Minimum current stock to include"
        ),
    ) -> SlowMoversOutput:
        try:
            response = await self._fetch_slow_movers(
                from_date,
                to_date,
                top_n,
                min_days_on_sale,
                warehouses,
                min_stock_balance,
            )
            return SlowMoversOutput(**response)
        except Exception as e:
            self.logger.error(f"Error in analyze_slow_movers: {e}", exc_info=True)
            raise

    async def track_movers_shakers(
        self,
        period_current: Optional[Dict[str, str]] = Field(
            None,
            description="Current period: {'from': 'YYYY-MM-DD', 'to': 'YYYY-MM-DD'}. None = current month",
        ),
        period_prev: Optional[Dict[str, str]] = Field(
            None,
            description="Previous period: {'from': 'YYYY-MM-DD', 'to': 'YYYY-MM-DD'}. None = auto-calc",
        ),
        metric: str = Field(
            default="qty",
            description="Track: 'qty' (units sold) or 'revenue' (sales value)",
        ),
        top_n: int = Field(
            default=15, ge=1, description="Top N biggest movers/shakers to return"
        ),
    ) -> MoversShakersOutput:
        try:
            response = await self._fetch_movers_shakers(
                period_current, period_prev, metric, top_n
            )
            return MoversShakersOutput(**response)
        except Exception as e:
            self.logger.error(f"Error in track_movers_shakers: {e}", exc_info=True)
            raise

    async def perform_pareto_analysis(
        self,
        from_date: Optional[str] = Field(
            None, description="Start date (YYYY-MM-DD). None/empty = 30 days ago"
        ),
        to_date: Optional[str] = Field(
            None, description="End date (YYYY-MM-DD). None/empty = today"
        ),
        metric: str = Field(
            default="revenue",
            description="Analyze by: 'revenue' (top revenue drivers) or 'qty' (top volume items)",
        ),
    ) -> ParetoAnalysisOutput:
        try:
            response = await self._fetch_pareto_analysis(from_date, to_date, metric)
            return ParetoAnalysisOutput(**response)
        except Exception as e:
            self.logger.error(f"Error in perform_pareto_analysis: {e}", exc_info=True)
            raise

    async def analyze_stock_coverage(
        self,
        warehouses: List[str] = Field(
            default_factory=list,
            description="Warehouse filter. Empty = all warehouses",
        ),
        item_groups: Optional[List[str]] = Field(
            None,
            description="Filter by item group (e.g., Electronics, Clothing). None = all groups",
        ),
        items: Optional[List[str]] = Field(
            None, description="Filter by specific item codes. None = all items"
        ),
        lookback_days: int = Field(
            default=30, ge=1, description="Days of sales history to calculate velocity"
        ),
        min_doc_days: Optional[float] = Field(
            None, ge=0, description="Show only items with >= this Days of Cover"
        ),
        max_doc_days: Optional[float] = Field(
            None, ge=0, description="Show only items with <= this Days of Cover"
        ),
        top_n: Optional[int] = Field(
            None, ge=1, description="Limit results to top N items by stock quantity"
        ),
    ) -> StockCoverageOutput:
        try:
            response = await self._fetch_stock_coverage(
                warehouses,
                item_groups,
                items,
                lookback_days,
                min_doc_days,
                max_doc_days,
                top_n,
            )
            return StockCoverageOutput(**response)
        except Exception as e:
            self.logger.error(f"Error in analyze_stock_coverage: {e}", exc_info=True)
            raise

    async def get_sales_order_stats(
        self,
        from_date: Optional[str] = Field(
            None, description="Start date (YYYY-MM-DD). None/empty = 90 days ago"
        ),
        to_date: Optional[str] = Field(
            None, description="End date (YYYY-MM-DD). None/empty = today"
        ),
        frequency: str = Field(
            default="monthly",
            description="Group by: 'daily', 'weekly', 'monthly', or 'yearly'",
        ),
        status: Optional[str] = Field(
            None,
            description="Filter by SO status: Completed, To Deliver and Bill, To Bill, To Deliver, Draft, On Hold, Cancelled, Closed. None = all",
        ),
    ) -> SalesOrderStatsOutput:
        try:
            response = await self._fetch_sales_order_stats(
                from_date, to_date, frequency, status
            )
            return SalesOrderStatsOutput(**response)
        except Exception as e:
            self.logger.error(f"Error in get_sales_order_stats: {e}", exc_info=True)
            raise

    async def _fetch_top_performers(
        self,
        from_date: str,
        to_date: str,
        metric: str,
        top_n: int,
        warehouses: List[str],
        channels: List[str],
        exclude_returns: bool,
        merge_variants: bool,
    ) -> dict:
        params = {
            "from_date": from_date,
            "to_date": to_date,
            "metric": metric,
            "top_n": top_n,
            "warehouses": warehouses,
            "channels": ",".join(channels),
            "exclude_returns": exclude_returns,
            "merge_variants": merge_variants,
        }

        try:
            result = await self.erpnext.call_method(
                "agent_stock_system.controller.analytics.analyze_top_performers",
                method="GET",
                params=params,
            )

            if isinstance(result, dict) and result.get("success") is False:
                raise ValueError(f"Backend error: {result.get('error_message')}")

            return result
        except Exception as e:
            self.logger.error(f"Error in analyze_top_performers: {e}")
            raise

    async def _fetch_slow_movers(
        self,
        from_date: str,
        to_date: str,
        top_n: int,
        min_days_on_sale: int,
        warehouses: List[str],
        min_stock_balance: float,
    ) -> dict:
        params = {
            "from_date": from_date,
            "to_date": to_date,
            "top_n": top_n,
            "min_days_on_sale": min_days_on_sale,
            "warehouses": warehouses,
            "min_stock_balance": min_stock_balance,
        }

        try:
            result = await self.erpnext.call_method(
                "agent_stock_system.controller.analytics.analyze_slow_movers",
                method="GET",
                params=params,
            )

            if isinstance(result, dict) and result.get("success") is False:
                raise ValueError(f"Backend error: {result.get('error_message')}")

            return result
        except Exception as e:
            self.logger.error(f"Error in analyze_slow_movers: {e}")
            raise

    async def _fetch_movers_shakers(
        self,
        period_current: Dict[str, str],
        period_prev: Dict[str, str],
        metric: str,
        top_n: int,
    ) -> dict:
        params = {
            "period_current_from": period_current.get("from"),
            "period_current_to": period_current.get("to"),
            "period_prev_from": period_prev.get("from"),
            "period_prev_to": period_prev.get("to"),
            "metric": metric,
            "top_n": top_n,
        }

        try:
            result = await self.erpnext.call_method(
                "agent_stock_system.controller.analytics.track_movers_shakers",
                method="GET",
                params=params,
            )

            if isinstance(result, dict) and result.get("success") is False:
                raise ValueError(f"Backend error: {result.get('error_message')}")

            return result
        except Exception as e:
            self.logger.error(f"Error in track_movers_shakers: {e}")
            raise

    async def _fetch_pareto_analysis(
        self, from_date: str, to_date: str, metric: str
    ) -> dict:
        params = {
            "from_date": from_date,
            "to_date": to_date,
            "metric": metric,
        }

        try:
            result = await self.erpnext.call_method(
                "agent_stock_system.controller.analytics.perform_pareto_analysis",
                method="GET",
                params=params,
            )

            if isinstance(result, dict) and result.get("success") is False:
                raise ValueError(f"Backend error: {result.get('error_message')}")

            return result
        except Exception as e:
            self.logger.error(f"Error in perform_pareto_analysis: {e}")
            raise

    async def _fetch_stock_coverage(
        self,
        warehouses: List[str],
        item_groups: Optional[List[str]],
        items: Optional[List[str]],
        lookback_days: int,
        min_doc_days: Optional[float],
        max_doc_days: Optional[float],
        top_n: Optional[int],
    ) -> dict:
        params = {
            "warehouses": ",".join(warehouses),
            "item_groups": ",".join(item_groups) if item_groups else None,
            "items": ",".join(items) if items else None,
            "lookback_days": lookback_days,
            "min_doc_days": min_doc_days,
            "max_doc_days": max_doc_days,
            "top_n": top_n,
        }
        params = {k: v for k, v in params.items() if v is not None}

        try:
            result = await self.erpnext.call_method(
                "agent_stock_system.controller.analytics.analyze_stock_coverage",
                method="GET",
                params=params,
            )

            if isinstance(result, dict) and result.get("success") is False:
                raise ValueError(f"Backend error: {result.get('error_message')}")

            return result
        except Exception as e:
            self.logger.error(f"Error in analyze_stock_coverage: {e}")
            raise

    async def _fetch_sales_order_stats(
        self,
        from_date: str,
        to_date: str,
        frequency: str,
        status: Optional[str],
    ) -> dict:
        params = {
            "from_date": from_date,
            "to_date": to_date,
            "frequency": frequency,
        }
        if status:
            params["status"] = status

        try:
            result = await self.erpnext.call_method(
                "agent_stock_system.controller.analytics.get_sales_order_stats",
                method="GET",
                params=params,
            )

            if isinstance(result, dict) and result.get("success") is False:
                raise ValueError(f"Backend error: {result.get('error_message')}")

            return result
        except Exception as e:
            self.logger.error(f"Error in get_sales_order_stats: {e}")
            raise

    async def cleanup(self) -> None:
        await self.erpnext.close()
