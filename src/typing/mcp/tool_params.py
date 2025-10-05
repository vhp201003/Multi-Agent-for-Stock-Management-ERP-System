"""Pydantic models for MCP tool parameters and outputs."""

from pydantic import BaseModel, Field


class CheckStockParams(BaseModel):
    """Parameters for check_stock tool.

    Used to validate input when calling the check_stock tool via MCP.
    """

    product_id: str = Field(description="Product ID to check stock level")
    warehouse: str = Field(
        default="default", description="Warehouse name to check stock in"
    )


class CheckStockOutput(BaseModel):
    """Output schema for check_stock tool.

    Provides structured response with stock information.
    """

    product_id: str = Field(description="Product ID that was queried")
    stock_level: int = Field(description="Current stock level for the product")
    warehouse: str = Field(description="Warehouse where stock was checked")
    status: str = Field(
        default="available", description="Stock status (available/low/out_of_stock)"
    )
