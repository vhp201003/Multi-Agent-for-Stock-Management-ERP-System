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
    transfer_quantity: float = Field(..., description="Proposed transfer quantity")
    available_quantity: float = Field(
        ..., description="Available quantity in source warehouse"
    )


class ProposeTransferFilters(BaseModel):
    item_code: str | None = Field(None, description="Item code searched")
    item_name: str | None = Field(None, description="Item name pattern for LIKE search")


class ProposeTransferSummary(BaseModel):
    total_quantity: float = Field(..., description="Total proposed transfer quantity")
    median_quantity: float = Field(..., description="Median proposed transfer quantity")
    max_quantity: float = Field(..., description="Maximum proposed transfer quantity")
    min_quantity: float = Field(..., description="Minimum proposed transfer quantity")


class ProposeTransferOutput(MCPToolOutputSchema):
    items: list[ProposeTransferItem]
    summary: ProposeTransferSummary
    filters_applied: ProposeTransferFilters


# ------------------------------- Create Stock Transfer ------------------------------- #
class StockTransferItemResult(BaseModel):
    item_code: str = Field(..., description="ERPNext item code")
    item_name: str = Field(..., description="Item name")
    qty: float = Field(..., description="Transferred quantity")
    from_warehouse: str = Field(..., description="Source warehouse")
    to_warehouse: str = Field(..., description="Target warehouse")
    valuation_rate: float = Field(0.0, description="Valuation rate at transfer")
    amount: float = Field(0.0, description="Total value transferred")


class StockTransferFilters(BaseModel):
    item_code: str | None = Field(None, description="Item code for exact search")
    item_name: str | None = Field(None, description="Item name pattern for LIKE search")
    from_warehouse: str = ""
    to_warehouse: str = ""
    qty: float | None = Field(None, description="Exact quantity transferred")
    auto_submit: bool = Field(
        False, description="Whether the stock entry was auto-submitted"
    )
    remarks: str | None = Field(None, description="Remarks pattern for LIKE search")


class StockTransferSummary(BaseModel):
    stock_entry_name: str = Field(..., description="Created Stock Entry document name")
    status: str = Field(..., description="Document status (Draft/Submitted)")
    total_qty: float = Field(..., description="Total quantity transferred")
    total_value: float = Field(..., description="Total value of transfer")
    posting_date: str = Field(..., description="Posting date of the transfer")


class StockTransferOutput(MCPToolOutputSchema):
    items: list[StockTransferItemResult]
    summary: StockTransferSummary
    filters_applied: StockTransferFilters
