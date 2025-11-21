from pydantic import BaseModel, Field

from src.typing.mcp.base import MCPToolOutputSchema


# AnalyticsAgent Schemas
# Tool 1: analyze_top_performers
class TopPerformersItem(BaseModel):
    """Schema for individual item in analyze_top_performers output."""

    rank: int = Field(..., ge=1, description="Rank position")
    item_code: str = Field(..., description="ERPNext item code")
    item_name: str = Field(..., description="Item name")
    qty: float = Field(..., ge=0, description="Sold quantity")
    revenue: float = Field(..., ge=0, description="Revenue")
    share_pct: float = Field(
        ..., ge=0, le=1, description="Percentage of total metric (qty or revenue)"
    )
    sparkline_qty: list[float] = Field(
        ..., description="Daily sales trend for short-term analysis"
    )


class TopPerformersFilters(BaseModel):
    """Schema for filters_applied in analyze_top_performers."""

    from_date: str = Field(..., description="Start date for sales data (YYYY-MM-DD)")
    to_date: str = Field(..., description="End date for sales data (YYYY-MM-DD)")
    metric: str = Field(..., description="Ranking metric: qty or revenue")
    top_n: int = Field(..., ge=1, description="Number of top items to return")
    warehouses: list[str] = Field(..., description="List of warehouse names")
    channels: list[str] = Field(..., description="Sales channels: POS, Online, etc.")
    exclude_returns: bool = Field(
        ..., description="Whether to exclude return transactions"
    )
    merge_variants: bool = Field(..., description="Whether to group by item template")


class TopPerformersSummary(BaseModel):
    """Schema for summary in analyze_top_performers."""

    total_qty: float = Field(..., ge=0, description="Total sold quantity")
    total_revenue: float = Field(..., ge=0, description="Total revenue")
    total_sku_sold: int = Field(..., ge=0, description="Number of unique SKUs sold")


class TopPerformersOutput(MCPToolOutputSchema):
    """Schema for analyze_top_performers tool output."""

    ranking: list[TopPerformersItem] = Field(
        ..., description="Chartable list of top-performing items"
    )
    summary: TopPerformersSummary
    filters_applied: TopPerformersFilters


# Tool 2: analyze_slow_movers
class SlowMoversSuggestion(BaseModel):
    """Schema for action suggestions in analyze_slow_movers."""

    action: str = Field(..., description="Suggested action: markdown, bundle")
    discount_pct: float | None = Field(
        None, ge=0, description="Discount percentage for markdown"
    )
    bundle_with: list[str] | None = Field(None, description="Item codes to bundle with")


class SlowMoversItem(BaseModel):
    """Schema for individual item in analyze_slow_movers output."""

    item_code: str = Field(..., description="ERPNext item code")
    item_name: str = Field(..., description="Item name")
    sell_through_rate: float = Field(
        ..., ge=0, le=1, description="Sold qty / (opening stock + incoming)"
    )
    gmroi: float = Field(..., description="Gross Margin Return on Investment")
    stock_balance: float = Field(..., ge=0, description="Current stock balance")
    days_without_sale: int = Field(..., ge=0, description="Days without sales")
    suggestion: SlowMoversSuggestion | None = Field(
        None, description="Suggested action"
    )


class SlowMoversFilters(BaseModel):
    """Schema for filters_applied in analyze_slow_movers."""

    from_date: str = Field(..., description="Start date for sales data (YYYY-MM-DD)")
    to_date: str = Field(..., description="End date for sales data (YYYY-MM-DD)")
    top_n: int = Field(..., ge=1, description="Number of slow-moving items to return")
    min_days_on_sale: int = Field(
        ..., ge=0, description="Minimum days on sale to consider"
    )
    warehouses: list[str] = Field(..., description="List of warehouse names")
    min_stock_balance: float = Field(
        ..., ge=0, description="Minimum stock balance to consider"
    )


class SlowMoversSummary(BaseModel):
    """Schema for summary in analyze_slow_movers."""

    total_stock_balance: float = Field(
        ..., ge=0, description="Total stock balance of slow movers"
    )
    avg_sell_through_rate: float = Field(
        ..., ge=0, description="Average sell-through rate"
    )
    avg_gmroi: float = Field(..., description="Average GMROI")


class SlowMoversOutput(MCPToolOutputSchema):
    """Schema for analyze_slow_movers tool output."""

    slow_movers: list[SlowMoversItem] = Field(
        ..., description="Chartable list of slow-moving items"
    )
    summary: SlowMoversSummary
    filters_applied: SlowMoversFilters


# Tool 3: track_movers_shakers
class MoversShakersItem(BaseModel):
    """Schema for individual item in track_movers_shakers output."""

    item_code: str = Field(..., description="ERPNext item code")
    item_name: str = Field(..., description="Item name")
    growth_pct: float = Field(
        ..., description="Percentage growth compared to previous period"
    )
    qty_current: float = Field(..., ge=0, description="Quantity in current period")
    qty_prev: float = Field(..., ge=0, description="Quantity in previous period")
    revenue_current: float = Field(..., ge=0, description="Revenue in current period")
    revenue_prev: float = Field(..., ge=0, description="Revenue in previous period")


class MoversShakersFilters(BaseModel):
    """Schema for filters_applied in track_movers_shakers."""

    period_current: dict[str, str] = Field(
        ..., description="Current period: {from: YYYY-MM-DD, to: YYYY-MM-DD}"
    )
    period_prev: dict[str, str] = Field(
        ..., description="Previous period: {from: YYYY-MM-DD, to: YYYY-MM-DD}"
    )
    metric: str = Field(..., description="Comparison metric: qty or revenue")
    top_n: int = Field(..., ge=1, description="Number of movers to return")


class MoversShakersSummary(BaseModel):
    """Schema for summary in track_movers_shakers."""

    total_movers_up: int = Field(
        ..., ge=0, description="Number of items with positive growth"
    )
    total_movers_down: int = Field(
        ..., ge=0, description="Number of items with negative growth"
    )
    avg_growth_pct: float = Field(..., description="Average growth percentage")


class MoversShakersOutput(MCPToolOutputSchema):
    """Schema for track_movers_shakers tool output."""

    movers: list[MoversShakersItem] = Field(
        ..., description="Chartable list of movers and shakers"
    )
    summary: MoversShakersSummary
    filters_applied: MoversShakersFilters


# Tool 4: perform_pareto_analysis
class ParetoAnalysisItem(BaseModel):
    """Schema for individual item in perform_pareto_analysis output."""

    item_code: str = Field(..., description="ERPNext item code")
    item_name: str = Field(..., description="Item name")
    revenue: float = Field(..., ge=0, description="Revenue contribution")
    cum_share: float = Field(
        ..., ge=0, le=1, description="Cumulative share of total metric"
    )


class ParetoAnalysisFilters(BaseModel):
    """Schema for filters_applied in perform_pareto_analysis."""

    from_date: str = Field(..., description="Start date for sales data (YYYY-MM-DD)")
    to_date: str = Field(..., description="End date for sales data (YYYY-MM-DD)")
    metric: str = Field(..., description="Metric for analysis: revenue")


class ParetoAnalysisSummary(BaseModel):
    """Schema for summary in perform_pareto_analysis."""

    cutoff_pct: float = Field(
        ..., ge=0, le=1, description="Pareto cutoff percentage, e.g., 0.8"
    )
    count_to_80pct: int = Field(
        ..., ge=0, description="Number of items reaching 80% of total"
    )
    total_revenue: float = Field(..., ge=0, description="Total revenue")


class ParetoAnalysisOutput(MCPToolOutputSchema):
    """Schema for perform_pareto_analysis tool output."""

    pareto: list[ParetoAnalysisItem] = Field(
        ..., description="Chartable Pareto analysis data"
    )
    summary: ParetoAnalysisSummary
    filters_applied: ParetoAnalysisFilters


# Tool 5: analyze_stock_coverage
class StockCoverageRecommendation(BaseModel):
    """Schema for action recommendations in analyze_stock_coverage."""

    action: str = Field(
        ..., description="Recommended action: monitor, order, markdown, bundle"
    )
    note: str | None = Field(None, description="Additional note for the recommendation")
    discount_pct: float | None = Field(
        None, ge=0, description="Discount percentage for markdown"
    )
    order_qty: float | None = Field(None, ge=0, description="Suggested order quantity")


class StockCoverageItem(BaseModel):
    """Schema for individual item in analyze_stock_coverage output."""

    item_code: str = Field(..., description="ERPNext item code")
    item_name: str = Field(..., description="Item name")
    warehouse: str = Field(..., description="Warehouse name")
    stock_qty: float = Field(..., ge=0, description="Current stock quantity")
    avg_daily_sales: float = Field(
        ..., ge=0, description="Average daily sales over lookback period"
    )
    doc_days: float = Field(
        ..., ge=0, description="Stock Cover Days (stock_qty / avg_daily_sales)"
    )
    recommendation: StockCoverageRecommendation | None = Field(
        None, description="Recommended action"
    )


class StockCoverageFilters(BaseModel):
    """Schema for filters_applied in analyze_stock_coverage."""

    warehouses: list[str] = Field(..., description="List of warehouse names")
    item_groups: list[str] | None = Field(None, description="List of item groups")
    items: list[str] | None = Field(None, description="List of specific item codes")
    lookback_days: int = Field(
        ..., ge=1, description="Days to calculate avg daily sales"
    )
    min_doc_days: float | None = Field(
        None, ge=0, description="Minimum Stock Cover Days filter"
    )
    max_doc_days: float | None = Field(
        None, ge=0, description="Maximum Stock Cover Days filter"
    )
    top_n: int | None = Field(
        None, ge=1, description="Limit to top N items by stock_qty"
    )


class StockCoverageSummary(BaseModel):
    """Schema for summary in analyze_stock_coverage."""

    avg_doc_days: float = Field(
        ..., ge=0, description="Average Stock Cover Days across items"
    )
    items_low_coverage: int = Field(
        ..., ge=0, description="Number of items with low DoC"
    )
    items_high_coverage: int = Field(
        ..., ge=0, description="Number of items with high DoC"
    )


class StockCoverageOutput(MCPToolOutputSchema):
    """Schema for analyze_stock_coverage tool output."""

    stock_coverage: list[StockCoverageItem] = Field(
        ..., description="Chartable stock coverage data"
    )
    summary: StockCoverageSummary
    filters_applied: StockCoverageFilters
