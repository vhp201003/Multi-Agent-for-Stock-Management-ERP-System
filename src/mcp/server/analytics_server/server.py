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
            description="Analyze top-performing items by quantity or revenue with sparkline trends",
            structured_output=True,
        )

        self.add_tool(
            self.analyze_slow_movers,
            name="analyze_slow_movers",
            description="Identify slow-moving items with sell-through rate, GMROI, and actionable suggestions",
            structured_output=True,
        )

        self.add_tool(
            self.track_movers_shakers,
            name="track_movers_shakers",
            description="Track items with significant growth or decline between two periods",
            structured_output=True,
        )

        self.add_tool(
            self.perform_pareto_analysis,
            name="perform_pareto_analysis",
            description="Perform Pareto analysis (80/20 rule) on revenue contribution",
            structured_output=True,
        )

        self.add_tool(
            self.analyze_stock_coverage,
            name="analyze_stock_coverage",
            description="Analyze stock coverage (Days of Cover) with reorder recommendations",
            structured_output=True,
        )

        self.add_tool(
            self.get_sales_order_stats,
            name="get_sales_order_stats",
            description="Get sales order statistics grouped by time period (daily, monthly, yearly)",
            structured_output=True,
        )

        self.logger.info("✅ All analytics tools registered successfully")

    async def analyze_top_performers(
        self,
        from_date: str = Field(..., description="Start date (YYYY-MM-DD)"),
        to_date: str = Field(..., description="End date (YYYY-MM-DD)"),
        metric: str = Field(
            default="revenue",
            description="Ranking metric: 'qty' or 'revenue'",
        ),
        top_n: int = Field(
            default=10, ge=1, description="Number of top items to return"
        ),
        warehouses: List[str] = Field(
            default_factory=list,
            description="List of warehouse names. Leave empty to query all warehouses.",
        ),
        channels: List[str] = Field(
            default=["POS", "Online"], description="Sales channels to include"
        ),
        exclude_returns: bool = Field(
            default=True, description="Exclude return transactions"
        ),
        merge_variants: bool = Field(
            default=False, description="Group by item template instead of variant"
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
        from_date: str = Field(..., description="Start date (YYYY-MM-DD)"),
        to_date: str = Field(..., description="End date (YYYY-MM-DD)"),
        top_n: int = Field(
            default=20, ge=1, description="Number of slow movers to return"
        ),
        min_days_on_sale: int = Field(
            default=30, ge=0, description="Minimum days item must be on sale"
        ),
        warehouses: List[str] = Field(
            default_factory=list,
            description="List of warehouse names. Leave empty to query all warehouses.",
        ),
        min_stock_balance: float = Field(
            default=0.0, ge=0, description="Minimum stock balance to consider"
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
        period_current: Dict[str, str] = Field(
            ...,
            description="Current period: {'from': 'YYYY-MM-DD', 'to': 'YYYY-MM-DD'}",
        ),
        period_prev: Dict[str, str] = Field(
            ...,
            description="Previous period: {'from': 'YYYY-MM-DD', 'to': 'YYYY-MM-DD'}",
        ),
        metric: str = Field(
            default="qty", description="Comparison metric: 'qty' or 'revenue'"
        ),
        top_n: int = Field(default=15, ge=1, description="Number of movers to return"),
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
        from_date: str = Field(..., description="Start date (YYYY-MM-DD)"),
        to_date: str = Field(..., description="End date (YYYY-MM-DD)"),
        metric: str = Field(
            default="revenue", description="Analysis metric: 'revenue' or 'qty'"
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
            description="List of warehouse names. Leave empty to query all warehouses.",
        ),
        item_groups: Optional[List[str]] = Field(
            None, description="Optional list of item groups to filter"
        ),
        items: Optional[List[str]] = Field(
            None, description="Optional list of specific item codes"
        ),
        lookback_days: int = Field(
            default=30, ge=1, description="Days to calculate average daily sales"
        ),
        min_doc_days: Optional[float] = Field(
            None, ge=0, description="Minimum Days of Cover filter"
        ),
        max_doc_days: Optional[float] = Field(
            None, ge=0, description="Maximum Days of Cover filter"
        ),
        top_n: Optional[int] = Field(
            None, ge=1, description="Limit to top N items by stock quantity"
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
        from_date: str = Field(..., description="Start date (YYYY-MM-DD)"),
        to_date: str = Field(..., description="End date (YYYY-MM-DD)"),
        frequency: str = Field(
            default="monthly",
            description="Time grouping: 'daily', 'monthly', or 'yearly'",
        ),
        status: Optional[str] = Field(
            None,
            description="Sales Order status filter. Valid values: Draft, On Hold, To Deliver and Bill, To Bill, To Deliver, Completed, Cancelled, Closed",
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
