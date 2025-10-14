from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

class CheckStockParams(BaseModel):
    product_id: str = Field(description="Product ID to check stock level")
    warehouse: str = Field(
        default="default", description="Warehouse name to check stock in"
    )


class CheckStockOutput(BaseModel):
    product_id: str = Field(description="Product ID that was queried")
    stock_level: int = Field(description="Current stock level")
    warehouse: str = Field(description="Warehouse location")
    status: str = Field(description="Stock status (available/low/critical/out_of_stock)")
    
    reserved_qty: int = Field(default=0, description="Reserved quantity")
    available_qty: int = Field(description="Available quantity for use")
    timestamp: str = Field(description="Query timestamp")
    
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Complete product metadata including supplier"
    )
    
    product_name: Optional[str] = Field(None, description="Product display name")
    supplier: Optional[str] = Field(None, description="Supplier name")
    category: Optional[str] = Field(None, description="Product category")
    unit_cost: Optional[float] = Field(None, description="Unit cost")
    reorder_level: Optional[int] = Field(None, description="Reorder threshold")