from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from src.typing.mcp.base import MCPToolOutputSchema


# ------------------------------- Check Stock Typing ------------------------------- #
class CheckStockItem(BaseModel):
    item_code: str = Field(..., description="ERPNext item code")
    warehouse: str = Field(..., description="Warehouse name")
    quantity: float = Field(..., description="Current stock quantity")


class CheckStockFilters(BaseModel):
    item_code: str | None = None
    item_name: str | None = Field(None, description="Item name pattern for LIKE search")
    warehouses: str | list | None = Field(
        None, description="Warehouse name or list of warehouse names"
    )
    quantity_type: Literal[
        "actual_quantity", "reserved_quantity", "projected_quantity"
    ] = "actual_quantity"


class CheckStockSummary(BaseModel):
    max_quantity: float = Field(..., description="Maximum stock quantity among results")
    min_quantity: float = Field(..., description="Minimum stock quantity among results")
    total_warehouse_for_item: int = Field(
        ..., description="Total number of warehouses for the items queried"
    )
    avg_quantity: float = Field(..., description="Average stock quantity among results")
    median_quantity: float = Field(
        ..., description="Median stock quantity among results"
    )


class CheckStockOutput(MCPToolOutputSchema):
    items: list[CheckStockItem]
    summary: CheckStockSummary
    filters_applied: CheckStockFilters


# ------------------------------- Retrieve Stock History ------------------------------- #
class StockHistoryItem(BaseModel):
    posting_date: str | date = Field(
        ..., description="Date of stock movement (ISO format or date object)"
    )
    item_code: str = Field(..., description="ERPNext item code")
    quantity: float = Field(
        ..., description="Quantity change (positive for IN, negative for OUT)"
    )
    warehouse: str = Field(..., description="Warehouse name")


class StockHistoryFilters(BaseModel):
    item_code: str = ""
    item_name: str | None = None
    warehouse: str | None = None
    days_back: int = Field(30, ge=1, le=365)


class StockHistorySummary(BaseModel):
    inbound_quantity: float = Field(..., description="Total inbound quantity")
    outbound_quantity: float = Field(..., description="Total outbound quantity")


class StockHistoryOutput(MCPToolOutputSchema):
    items: list[StockHistoryItem] = Field(..., description="Chartable stock movements")
    summary: StockHistorySummary
    filters_applied: StockHistoryFilters


# ------------------------------- Propose Transfer ------------------------------- #
class ProposeTransferItem(BaseModel):
    item_code: str = Field(..., description="ERPNext item code")
    from_warehouse: str = Field(..., description="Source warehouse")
    to_warehouse: str = Field(..., description="Target warehouse")
    transfer_quantity: float = Field(
        ..., description="Proposed transfer quantity"
    )
    available_quantity: float = Field(
        ..., description="Available quantity in source warehouse"
    )


class ProposeTransferFilters(BaseModel):
    item_code: str = ""
    item_name: str | None = Field(None, description="Item name pattern for LIKE search")
    to_warehouse: str = ""
    from_warehouses: str | None = None


class ProposeTransferSummary(BaseModel):
    total_quantity: float = Field(
        ..., description="Total proposed transfer quantity"
    )
    median_quantity: float = Field(
        ..., description="Median proposed transfer quantity"
    )
    max_quantity: float = Field(
        ..., description="Maximum proposed transfer quantity"
    )
    min_quantity: float = Field(
        ..., description="Minimum proposed transfer quantity"
    )


class ProposeTransferOutput(MCPToolOutputSchema):
    items: list[ProposeTransferItem]
    summary: ProposeTransferSummary
    filters_applied: ProposeTransferFilters


# ------------------------------- Inventory Health ------------------------------- #
class InventoryHealthItem(BaseModel):
    item_group: str = Field(..., description="Item group name")
    stock_quantity: float = Field(..., description="Total stock quantity")
    stock_value: float = Field(..., description="Total stock value")
    avg_doc_days: float = Field(..., description="Average Days of Cover")


class InventoryHealthFilters(BaseModel):
    warehouses: list[str] = []
    item_groups: list[str] | None = None
    horizon_days: int = Field(30, ge=1, le=365)


class InventoryHealthSummary(BaseModel):
    total_stock_value: float = Field(
        ..., description="Total stock value across all groups"
    )
    items_under_min: int = Field(
        ..., description="Number of items below min_quantity"
    )
    avg_doc_days: float = Field(
        ..., description="Average Days of Cover across all groups"
    )


class InventoryHealthOutput(MCPToolOutputSchema):
    items: list[InventoryHealthItem]
    summary: InventoryHealthSummary
    filters_applied: InventoryHealthFilters
