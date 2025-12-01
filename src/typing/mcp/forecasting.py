from pydantic import BaseModel, Field

from src.typing.mcp.base import MCPToolOutputSchema

# ======================================= Sales Forecast =======================================


class ForecastItem(BaseModel):
    month: int = Field(..., description="Month number (1, 2, ...)")
    month_year: str = Field(..., description="Month and Year (e.g., '12/2025')")
    predicted_qty: int = Field(..., description="Predicted quantity")
    confidence_lower: float = Field(
        ..., description="Lower bound of confidence interval"
    )
    confidence_upper: float = Field(
        ..., description="Upper bound of confidence interval"
    )
    std_dev: float = Field(..., description="Standard deviation of the prediction")
    demand_level: str = Field(
        ..., description="Demand level (e.g., 'HIGH', 'MEDIUM', 'LOW')"
    )


class ForecastFilters(BaseModel):
    item_code: str = Field(..., description="Item code used for prediction")
    months: int = Field(..., description="Number of months requested")


class ForecastSummary(BaseModel):
    total_months: int = Field(..., description="Total number of months predicted")
    total_qty: int = Field(..., description="Total predicted quantity")
    avg_per_month: int = Field(..., description="Average predicted quantity per month")
    trend: str = Field(
        ..., description="Trend direction (e.g., 'GROWING', 'DECLINING', 'STABLE')"
    )
    trend_pct: float = Field(..., description="Trend percentage")
    vs_historical: str = Field(..., description="Comparison vs historical average")
    vs_historical_pct: float = Field(
        ..., description="Percentage difference vs historical average"
    )
    historical_avg: float = Field(..., description="Historical average quantity")
    accuracy: str = Field(..., description="Model accuracy rating")
    model_version: str = Field(..., description="Model version used")


class ForecastOutput(MCPToolOutputSchema):
    items: list[ForecastItem] | None = None
    summary: ForecastSummary | None = None
    filters_applied: ForecastFilters | None = None


# ======================================= Inventory Forecast =======================================
class InventoryForecastItem(BaseModel):
    item: str = Field(..., description="Item code")
    warehouse: str = Field(..., description="Warehouse name")
    month: int = Field(..., description="Month number")
    month_year: str = Field(..., description="Month and Year")
    predicted_qty: int = Field(..., description="Predicted quantity")
    confidence_lower: float = Field(..., description="Lower bound")
    confidence_upper: float = Field(..., description="Upper bound")
    std_dev: float = Field(..., description="Standard deviation")


class InventoryForecastFilters(BaseModel):
    item_code: str = Field(..., description="Item code used for prediction")
    warehouse: str = Field(..., description="Warehouse name")
    months: int = Field(..., description="Number of months requested")


class InventoryForecastOutput(MCPToolOutputSchema):
    items: list[InventoryForecastItem] | None = None
    summary: ForecastSummary | None = None
    filters_applied: InventoryForecastFilters | None = None
