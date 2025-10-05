"""Pydantic models for MCP resource outputs."""

from typing import Dict

from pydantic import BaseModel, Field


class StockLevelsOutput(BaseModel):
    """Output schema for stock://levels resource.

    Provides overview of stock levels across products.
    """

    levels: Dict[str, int] = Field(
        description="Dictionary mapping product IDs to stock levels"
    )
    timestamp: str = Field(description="Timestamp when data was retrieved (ISO format)")
    warehouse: str = Field(
        default="default", description="Warehouse for the stock levels"
    )
