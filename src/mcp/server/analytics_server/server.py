import logging
from typing import Optional

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
            None,
            description="The start date of the analysis period in 'YYYY-MM-DD' format. If not provided, defaults to 30 days prior to the current date.",
        ),
        to_date: Optional[str] = Field(
            None,
            description="The end date of the analysis period in 'YYYY-MM-DD' format. If not provided, defaults to the current date.",
        ),
        metric: str = Field(
            default="revenue",
            description="The metric to rank items by. Options are 'qty' (quantity sold) or 'revenue' (total sales value). Defaults to 'revenue'.",
        ),
        top_n: int = Field(
            default=10,
            ge=1,
            description="The number of top-performing items to retrieve. Defaults to 10.",
        ),
    ) -> TopPerformersOutput:
        try:
            response = await self._fetch_top_performers(
                from_date,
                to_date,
                metric,
                top_n,
            )
            return TopPerformersOutput(**response)
        except Exception as e:
            self.logger.error(f"Error in analyze_top_performers: {e}", exc_info=True)
            raise

    async def analyze_slow_movers(
        self,
        from_date: Optional[str] = Field(
            None,
            description="The start date for sales data analysis in 'YYYY-MM-DD' format. If not provided, defaults to 90 days prior to the current date.",
        ),
        to_date: Optional[str] = Field(
            None,
            description="The end date for sales data analysis in 'YYYY-MM-DD' format. If not provided, defaults to the current date.",
        ),
        metric: str = Field(
            default="revenue",
            description="The metric used to evaluate item performance. Options are 'qty' (quantity) or 'revenue' (total value). Defaults to 'revenue'.",
        ),
        top_n: int = Field(
            default=10,
            ge=1,
            description="The number of slow-moving items to retrieve. Defaults to 10.",
        ),
    ) -> SlowMoversOutput:
        try:
            response = await self._fetch_slow_movers(
                from_date,
                to_date,
                metric,
                top_n,
            )
            return SlowMoversOutput(**response)
        except Exception as e:
            self.logger.error(f"Error in analyze_slow_movers: {e}", exc_info=True)
            raise

    async def track_movers_shakers(
        self,
        from_date: Optional[str] = Field(
            None,
            description="The start date of the current period in 'YYYY-MM-DD' format. The previous period is calculated automatically (e.g., previous month). If not provided, defaults to 90 days ago.",
        ),
        to_date: Optional[str] = Field(
            None,
            description="The end date of the current period in 'YYYY-MM-DD' format. If not provided, defaults to the current date.",
        ),
        metric: str = Field(
            default="revenue",
            description="The metric to compare for growth or decline. Options are 'qty' or 'revenue'. Defaults to 'revenue'.",
        ),
        top_n: int = Field(
            default=10,
            ge=1,
            description="The number of items with significant changes (movers/shakers) to retrieve. Defaults to 10.",
        ),
    ) -> MoversShakersOutput:
        try:
            response = await self._fetch_movers_shakers(
                from_date,
                to_date,
                metric,
                top_n,
            )
            return MoversShakersOutput(**response)
        except Exception as e:
            self.logger.error(f"Error in track_movers_shakers: {e}", exc_info=True)
            raise

    async def perform_pareto_analysis(
        self,
        from_date: Optional[str] = Field(
            None,
            description="The start date for the analysis in 'YYYY-MM-DD' format. If not provided, defaults to 30 days prior to the current date.",
        ),
        to_date: Optional[str] = Field(
            None,
            description="The end date for the analysis in 'YYYY-MM-DD' format. If not provided, defaults to the current date.",
        ),
        metric: str = Field(
            default="revenue",
            description="The metric for Pareto analysis. Options are 'revenue' (identifying items driving 80% of revenue) or 'qty' (identifying items driving 80% of volume).",
        ),
        top_n: int = Field(
            default=10,
            ge=1,
            description="The number of items to retrieve in the Pareto analysis. Defaults to 10.",
        ),
    ) -> ParetoAnalysisOutput:
        try:
            response = await self._fetch_pareto_analysis(
                from_date=from_date,
                to_date=to_date,
                metric=metric,
                top_n=top_n,
            )
            return ParetoAnalysisOutput(**response)
        except Exception as e:
            self.logger.error(f"Error in perform_pareto_analysis: {e}", exc_info=True)
            raise

    async def analyze_stock_coverage(
        self,
        item_code: str = Field(
            None,
            description="The specific item code to analyze. If not provided, the analysis is performed on all items.",
        ),
        item_name: str = Field(
            None,
            description="The specific item name to filter by. If not provided, the analysis is performed on all items.",
        ),
        lookback_days: int = Field(
            default=30,
            ge=1,
            description="The number of days of past sales history to use for calculating average daily sales velocity. Defaults to 30 days.",
        ),
    ) -> StockCoverageOutput:
        try:
            response = await self._fetch_stock_coverage(
                item_code,
                item_name,
                lookback_days,
            )
            return StockCoverageOutput(**response)
        except Exception as e:
            self.logger.error(f"Error in analyze_stock_coverage: {e}", exc_info=True)
            raise

    async def get_sales_order_stats(
        self,
        from_date: Optional[str] = Field(
            None,
            description="The start date for the statistics in 'YYYY-MM-DD' format. If not provided, defaults to 90 days prior to the current date.",
        ),
        to_date: Optional[str] = Field(
            None,
            description="The end date for the statistics in 'YYYY-MM-DD' format. If not provided, defaults to the current date.",
        ),
        frequency: str = Field(
            default="monthly",
            description="The time granularity for grouping statistics. Options: 'daily', 'weekly', 'monthly', 'yearly'. Defaults to 'monthly'.",
        ),
        status: Optional[str] = Field(
            None,
            description="Filter by Sales Order status (e.g., 'Completed', 'To Deliver and Bill', 'To Bill', 'To Deliver', 'Draft', 'On Hold', 'Cancelled', 'Closed'). If None, includes all statuses.",
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
        from_date: str | None,
        to_date: str | None,
        metric: str,
        top_n: int,
    ) -> dict:
        params = {
            "from_date": from_date,
            "to_date": to_date,
            "metric": metric,
            "top_n": top_n,
        }
        params = {k: v for k, v in params.items() if v is not None}

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
        from_date: str | None,
        to_date: str | None,
        metric: str,
        top_n: int,
    ) -> dict:
        params = {
            "from_date": from_date,
            "to_date": to_date,
            "metric": metric,
            "top_n": top_n,
        }
        params = {k: v for k, v in params.items() if v is not None}

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
        from_date: str | None,
        to_date: str | None,
        metric: str,
        top_n: int,
    ) -> dict:
        params = {
            "from_date": from_date,
            "to_date": to_date,
            "metric": metric,
            "top_n": top_n,
        }
        params = {k: v for k, v in params.items() if v is not None}

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
        self, from_date: str | None, to_date: str | None, metric: str, top_n: int | None
    ) -> dict:
        params = {
            "from_date": from_date,
            "to_date": to_date,
            "metric": metric,
            "top_n": top_n,
        }
        params = {k: v for k, v in params.items() if v is not None}

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
        item_code: str | None = None,
        item_name: str | None = None,
        lookback_days: int | None = None,
    ) -> dict:
        params = {
            "item_code": item_code,
            "item_name": item_name,
            "lookback_days": lookback_days,
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
        from_date: str | None,
        to_date: str | None,
        frequency: str,
        status: Optional[str],
    ) -> dict:
        params = {
            "from_date": from_date,
            "to_date": to_date,
            "frequency": frequency,
            "status": status,
        }
        params = {k: v for k, v in params.items() if v is not None}

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
