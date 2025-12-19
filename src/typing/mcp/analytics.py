from pydantic import BaseModel, Field

from src.typing.mcp.base import MCPToolOutputSchema


# AnalyticsAgent Schemas
# Tool 1: analyze_top_performers
class TopPerformersItem(BaseModel):
    """Schema for individual item in analyze_top_performers output."""

    rank: int = Field(
        ...,
        description="The rank of the item based on the selected metric (1 is highest).",
    )
    item_code: str = Field(..., description="The unique ERPNext item code.")
    item_name: str = Field(..., description="The descriptive name of the item.")
    qty: int = Field(..., description="Total quantity sold in the period.")
    revenue: float = Field(..., description="Total revenue generated in the period.")
    share_pct: float = Field(
        ...,
        description="The item's contribution percentage to the total metric (qty or revenue).",
    )
    sparkline_qty: list[int] = Field(
        ...,
        description="A list of daily sales quantities to visualize the sales trend over the period.",
    )


class TopPerformersSummary(BaseModel):
    """Schema for summary in analyze_top_performers."""

    total_qty: float = Field(..., description="Total sold quantity")
    total_revenue: float = Field(..., description="Total revenue")
    total_sku_sold: int = Field(..., description="Number of unique SKUs sold in top N")
    top_item_code: str = Field(..., description="Best-performing item code")
    top_item_name: str = Field(..., description="Best-performing item name")
    top_item_share_pct: float = Field(
        ..., description="Percentage of top item in total metric"
    )
    avg_metric_per_item: float = Field(..., description="Average metric value per item")
    concentration_pct: float = Field(
        ...,
        description="Concentration of top N items (% of all items that contribute top N %)",
    )


class TopPerformersFilters(BaseModel):
    """Schema for filters_applied in analyze_top_performers."""

    from_date: str = Field(..., description="Start date for sales data (YYYY-MM-DD)")
    to_date: str = Field(..., description="End date for sales data (YYYY-MM-DD)")
    metric: str = Field(..., description="Ranking metric: qty or revenue")
    top_n: int = Field(..., description="Number of top items to return")


class TopPerformersOutput(MCPToolOutputSchema):
    """Schema for analyze_top_performers tool output."""

    items: list[TopPerformersItem] | None = None
    summary: TopPerformersSummary | None = None
    filters_applied: TopPerformersFilters | None = None


# Tool 2: analyze_slow_movers
class SlowMoversSuggestion(BaseModel):
    """Schema for action suggestions in analyze_slow_movers."""

    action: str = Field(..., description="Suggested action: markdown, bundle")
    discount_pct: float | None = Field(
        None, description="Discount percentage for markdown"
    )
    bundle_with: list[str] | None = Field(None, description="Item codes to bundle with")


class SlowMoversItem(BaseModel):
    """Schema for individual item in analyze_slow_movers output."""

    item_code: str = Field(..., description="ERPNext item code")
    item_name: str = Field(..., description="Item name")
    sell_through_rate: float = Field(
        ...,
        description="Sell-through rate calculated as Sold Qty / (Opening Stock + Incoming Stock). Measures inventory efficiency.",
    )
    gmroi: float = Field(
        ...,
        description="Gross Margin Return on Investment. Indicates profitability relative to inventory investment.",
    )
    stock_balance: int = Field(..., description="Current stock quantity available.")
    days_without_sale: int = Field(
        ..., description="Number of consecutive days with zero sales."
    )
    suggestion: SlowMoversSuggestion | None = Field(
        None, description="Suggested action"
    )


class SlowMoversFilters(BaseModel):
    """Schema for filters_applied in analyze_slow_movers."""

    from_date: str = Field(..., description="Start date for sales data (YYYY-MM-DD)")
    to_date: str = Field(..., description="End date for sales data (YYYY-MM-DD)")
    metric: str = Field(..., description="Ranking metric: qty or revenue")
    top_n: int = Field(..., description="Number of slow-moving items to return")


class SlowMoversSummary(BaseModel):
    """Schema for summary in analyze_slow_movers."""

    total_stock_balance: int = Field(
        ..., description="Total stock balance of slow movers"
    )
    total_stock_value: float = Field(
        ..., description="Total stock value (revenue impact)"
    )
    avg_sell_through_rate: float = Field(..., description="Average sell-through rate")
    avg_gmroi: float = Field(..., description="Average GMROI")
    slowest_item_code: str = Field(..., description="Slowest-moving item code")
    slowest_item_name: str = Field(..., description="Slowest-moving item name")
    slowest_item_sell_through: float = Field(
        ..., description="Sell-through rate of slowest item"
    )
    items_with_no_sale: int = Field(
        ..., description="Number of items with zero sales in period"
    )


class SlowMoversOutput(MCPToolOutputSchema):
    """Schema for analyze_slow_movers tool output."""

    items: list[SlowMoversItem] | None = None
    summary: SlowMoversSummary | None = None
    filters_applied: SlowMoversFilters | None = None


# Tool 3: track_movers_shakers
class MoversShakersItem(BaseModel):
    """Schema for individual item in track_movers_shakers output."""

    item_code: str = Field(..., description="ERPNext item code")
    item_name: str = Field(..., description="Item name")
    growth_pct: float = Field(
        ...,
        description="Percentage growth (or decline if negative) compared to the previous period.",
    )
    qty_current: int = Field(..., description="Quantity in current period")
    qty_prev: int = Field(..., description="Quantity in previous period")
    revenue_current: float = Field(..., description="Revenue in current period")
    revenue_prev: float = Field(..., description="Revenue in previous period")


class MoversShakersFilters(BaseModel):
    """Schema for filters_applied in track_movers_shakers."""

    from_date: str = Field(..., description="Current period start date (YYYY-MM-DD)")
    to_date: str = Field(..., description="Current period end date (YYYY-MM-DD)")
    metric: str = Field(..., description="Comparison metric: qty or revenue")
    top_n: int = Field(..., description="Number of movers to return")


class MoversShakersSummary(BaseModel):
    """Schema for summary in track_movers_shakers."""

    total_movers_up: int = Field(
        ..., description="Number of items with positive growth"
    )
    total_movers_down: int = Field(
        ..., description="Number of items with negative growth"
    )
    avg_growth_pct: float = Field(..., description="Average growth percentage")
    top_gainer_code: str = Field(..., description="Item code with highest growth")
    top_gainer_name: str = Field(..., description="Item name with highest growth")
    top_gainer_growth_pct: float = Field(..., description="Highest growth percentage")
    top_loser_code: str = Field(..., description="Item code with biggest decline")
    top_loser_name: str = Field(..., description="Item name with biggest decline")
    top_loser_decline_pct: float = Field(..., description="Biggest decline percentage")
    avg_decline_pct: float = Field(
        ..., description="Average decline percentage for declining items"
    )


class MoversShakersOutput(MCPToolOutputSchema):
    """Schema for track_movers_shakers tool output."""

    items: list[MoversShakersItem] | None = None
    summary: MoversShakersSummary | None = None
    filters_applied: MoversShakersFilters | None = None


# Tool 4: perform_pareto_analysis
class ParetoAnalysisItem(BaseModel):
    """Schema for individual item in perform_pareto_analysis output."""

    item_code: str = Field(..., description="ERPNext item code")
    item_name: str = Field(..., description="Item name")
    revenue: float = Field(..., description="Revenue contribution")
    cum_share: float = Field(
        ...,
        description="Cumulative percentage share of the total metric (used for Pareto/ABC analysis).",
    )
    abc_class: str = Field(
        ...,
        description="ABC classification: 'A' (high value), 'B' (medium value), or 'C' (low value)",
    )


class ParetoAnalysisFilters(BaseModel):
    """Schema for filters_applied in perform_pareto_analysis."""

    from_date: str = Field(..., description="Start date for sales data (YYYY-MM-DD)")
    to_date: str = Field(..., description="End date for sales data (YYYY-MM-DD)")
    metric: str = Field(..., description="Metric for analysis: qty or revenue")
    top_n: int | None = Field(
        None, description="Number of top items returned (if applied)"
    )


class ParetoAnalysisSummary(BaseModel):
    """Schema for summary in perform_pareto_analysis with ABC classification."""

    total_revenue: float = Field(..., description="Total revenue across all items")
    total_sku_count: int = Field(
        ..., description="Total number of unique items in period"
    )
    items_a_count: int = Field(
        ..., description="Number of A-class items (cumulative share ≤ 80%)"
    )
    items_b_count: int = Field(
        ..., description="Number of B-class items (cumulative share ≤ 95%)"
    )
    items_c_count: int = Field(
        ..., description="Number of C-class items (cumulative share > 95%)"
    )
    revenue_a: float = Field(..., description="Total revenue from A-class items")
    revenue_b: float = Field(..., description="Total revenue from B-class items")
    revenue_c: float = Field(..., description="Total revenue from C-class items")
    avg_revenue_a: float = Field(..., description="Average revenue per A-class item")
    avg_revenue_b: float = Field(..., description="Average revenue per B-class item")
    avg_revenue_c: float = Field(..., description="Average revenue per C-class item")
    concentration_pct: float = Field(
        ...,
        description="Concentration metric: percentage of A+B items that contribute 95% of revenue",
    )


class ParetoAnalysisOutput(MCPToolOutputSchema):
    """Schema for perform_pareto_analysis tool output."""

    items: list[ParetoAnalysisItem] | None = None
    summary: ParetoAnalysisSummary | None = None
    filters_applied: ParetoAnalysisFilters | None = None


# Tool 5: analyze_stock_coverage
class StockCoverageRecommendation(BaseModel):
    """Schema for action recommendations in analyze_stock_coverage."""

    action: str = Field(
        ..., description="Recommended action: monitor, order, markdown, bundle"
    )
    note: str | None = Field(None, description="Additional note for the recommendation")
    discount_pct: float | None = Field(
        None, description="Discount percentage for markdown"
    )
    order_qty: float | None = Field(None, description="Suggested order quantity")


class StockCoverageItem(BaseModel):
    """Schema for individual item in analyze_stock_coverage output."""

    item_code: str = Field(..., description="ERPNext item code")
    item_name: str = Field(..., description="Item name")
    warehouse: str = Field(..., description="Warehouse name")
    stock_qty: int = Field(..., description="Current stock quantity")
    avg_daily_sales: float = Field(
        ..., description="Average daily sales over lookback period"
    )
    doc_days: float = Field(
        ...,
        description="Days of Cover (DOC). Estimated number of days current stock will last based on average daily sales.",
    )
    recommendation: StockCoverageRecommendation | None = Field(
        None, description="Recommended action"
    )


class StockCoverageFilters(BaseModel):
    """Schema for filters_applied in analyze_stock_coverage."""

    item_code: str = Field(..., description="Resolved item code")
    item_name: str = Field(..., description="Resolved item name")
    lookback_days: int = Field(..., description="Days to calculate avg daily sales")


class StockCoverageSummary(BaseModel):
    """Schema for summary in analyze_stock_coverage."""

    item_code: str = Field(..., description="Item code analyzed")
    item_name: str = Field(..., description="Item name analyzed")
    avg_doc_days: float = Field(
        ..., description="Average Stock Cover Days across warehouses"
    )
    total_stock_qty: int = Field(
        ..., description="Total stock quantity across all warehouses"
    )
    total_warehouses: int = Field(
        ..., description="Number of warehouses with stock for this item"
    )
    warehouses_low_coverage: int = Field(
        ..., description="Number of warehouses with DoC < 7 (need reorder)"
    )
    warehouses_high_coverage: int = Field(
        ..., description="Number of warehouses with DoC > 90 (excess stock)"
    )
    warehouses_need_reorder: int = Field(
        ...,
        description="Count of warehouses needing reorder (alias for warehouses_low_coverage)",
    )


class StockCoverageOutput(MCPToolOutputSchema):
    """Schema for analyze_stock_coverage tool output."""

    items: list[StockCoverageItem] | None = None
    summary: StockCoverageSummary | None = None
    filters_applied: StockCoverageFilters | None = None


# Tool 6: get_sales_order_stats
class SalesOrderStatsItem(BaseModel):
    """Schema for individual period in get_sales_order_stats output."""

    period: str = Field(
        ...,
        description="Time period (format depends on frequency: YYYY-MM-DD, YYYY-W##, YYYY-MM, or YYYY)",
    )
    total_orders: int = Field(..., description="Total number of orders in this period")
    total_revenue: float = Field(
        ..., description="Total revenue (grand_total) in this period"
    )
    avg_order_value: float = Field(
        ..., description="Average order value (total_revenue / total_orders)"
    )


class SalesOrderStatsFilters(BaseModel):
    """Schema for filters_applied in get_sales_order_stats."""

    from_date: str = Field(..., description="Start date for analysis (YYYY-MM-DD)")
    to_date: str = Field(..., description="End date for analysis (YYYY-MM-DD)")
    frequency: str = Field(
        ..., description="Time grouping: daily, weekly, monthly, yearly"
    )
    status: str | None = Field(
        None, description="Sales Order status filter (if applied)"
    )


class SalesOrderStatsSummary(BaseModel):
    """Schema for summary in get_sales_order_stats."""

    total_orders: int = Field(
        ..., description="Total number of orders across all periods"
    )
    total_revenue: float = Field(..., description="Total revenue across all periods")
    avg_orders_per_period: float = Field(..., description="Average orders per period")
    avg_revenue_per_period: float = Field(..., description="Average revenue per period")
    period_count: int = Field(..., description="Number of time periods in the analysis")
    avg_order_value: float = Field(
        ..., description="Average order value (total_revenue / total_orders)"
    )
    peak_period: str = Field(..., description="Period with highest revenue")
    peak_revenue: float = Field(..., description="Revenue in peak period")
    lowest_period: str = Field(..., description="Period with lowest revenue")
    lowest_revenue: float = Field(..., description="Revenue in lowest period")


class SalesOrderStatsOutput(MCPToolOutputSchema):
    """Schema for get_sales_order_stats tool output."""

    items: list[SalesOrderStatsItem] | None = None
    summary: SalesOrderStatsSummary | None = None
    filters_applied: SalesOrderStatsFilters | None = None
