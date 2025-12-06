import logging
from typing import Literal, Optional

from pydantic import Field

from src.communication import get_erpnext_connection
from src.mcp.server.base_server import BaseMCPServer, ServerConfig
from src.typing.mcp.base import ApprovalLevel, HITLMetadata
from src.typing.mcp.inventory import (
    CheckStockOutput,
    ProposeTransferOutput,
    StockHistoryOutput,
    StockTransferOutput,
)

logger = logging.getLogger(__name__)


class InventoryServerConfig(ServerConfig):
    erpnext_url: str = Field(
        default="http://localhost:8001", description="ERPNext base URL"
    )
    erpnext_api_key: Optional[str] = Field(default=None, description="ERPNext API key")
    erpnext_api_secret: Optional[str] = Field(
        default=None, description="ERPNext API secret"
    )
    default_warehouse: str = Field(
        default="Main Warehouse", description="Default warehouse name"
    )
    low_stock_threshold: int = Field(
        default=10, ge=0, description="Low stock threshold"
    )
    critical_stock_threshold: int = Field(
        default=5, ge=0, description="Critical stock threshold"
    )


class InventoryMCPServer(BaseMCPServer):
    def __init__(self, config: InventoryServerConfig):
        super().__init__(config)
        self.inventory_config = config
        self.erpnext = get_erpnext_connection()

    def setup(self) -> None:
        self.logger.info("Setting up Inventory MCP Server tools...")

        self.add_tool(
            self.check_stock,
            name="check_stock",
            description="Check current stock levels across warehouses with filtering options",
            structured_output=True,
        )

        self.add_tool(
            self.retrieve_stock_history,
            name="retrieve_stock_history",
            description="Retrieve historical stock movements for analysis and charting",
            structured_output=True,
        )

        self.add_tool(
            self.propose_transfer,
            name="propose_transfer",
            description="Propose stock transfers between warehouses based on availability",
            structured_output=True,
        )

        self.add_tool(
            self.create_stock_transfer,
            name="create_stock_transfer",
            description="Create and optionally submit stock transfer document(s). RECOMMENDED: Call propose_transfer first to get transfer suggestions before creating",
            structured_output=True,
            hitl=HITLMetadata(
                requires_approval=True,
                approval_level=ApprovalLevel.REVIEW,
                modifiable_fields=[
                    "item_code",
                    "qty",
                    "from_warehouse",
                    "to_warehouse",
                    "remarks",
                ],
                approval_message="Please review the stock transfer details before approval.",
                timeout_seconds=300,
            ),
        )

        self.logger.info("✅ All inventory tools registered successfully")

    # ======================== TOOL IMPLEMENTATIONS ========================

    async def check_stock(
        self,
        item_code: Optional[str] = Field(
            None, description="ERPNext item code to filter by"
        ),
        item_name: Optional[str] = Field(
            None, description="Item name to search for (partial match)"
        ),
        warehouses: Optional[str] = Field(
            None,
            description="Warehouse name or comma-separated list of warehouse names",
        ),
        quantity_type: Literal[
            "actual_quantity", "reserved_quantity", "projected_quantity"
        ] = Field(
            default="actual_quantity",
            description="Type of quantity to retrieve: actual, reserved, or projected",
        ),
    ) -> CheckStockOutput:
        try:
            response = await self._fetch_stock_levels(
                item_code, item_name, warehouses, quantity_type
            )

            return CheckStockOutput(**response)

        except Exception as e:
            self.logger.error(f"Error in check_stock: {e}", exc_info=True)
            raise

    async def retrieve_stock_history(
        self,
        item_code: str = Field(None, description="ERPNext item code"),
        item_name: Optional[str] = Field(None, description="Item name for reference"),
        warehouse: Optional[str] = Field(
            None, description="Filter by specific warehouse"
        ),
        days_back: int = Field(
            default=30, ge=1, le=365, description="Number of days to look back (1-365)"
        ),
    ) -> StockHistoryOutput:
        try:
            response = await self._fetch_stock_history(
                item_code, item_name, warehouse, days_back
            )

            return StockHistoryOutput(**response)

        except Exception as e:
            self.logger.error(f"Error in retrieve_stock_history: {e}", exc_info=True)
            raise

    async def propose_transfer(
        self,
        item_code: Optional[str] = Field(
            None, description="ERPNext item code (required)"
        ),
        item_name: Optional[str] = Field(
            None, description="Item name (alternative to item_code)"
        ),
    ) -> ProposeTransferOutput:
        try:
            response = await self._propose_stock_transfer(item_code, item_name)

            return ProposeTransferOutput(**response)

        except Exception as e:
            self.logger.error(f"Error in propose_transfer: {e}", exc_info=True)
            raise

    async def create_stock_transfer(
        self,
        item_code: str = Field(..., description="ERPNext item code"),
        qty: float = Field(..., description="Quantity to transfer"),
        from_warehouse: str = Field(..., description="Source warehouse"),
        to_warehouse: str = Field(..., description="Target warehouse"),
        remarks: Optional[str] = Field(None, description="Transfer remarks/notes"),
        auto_submit: bool = Field(
            False, description="Auto-submit the stock entry after creation"
        ),
    ) -> StockTransferOutput:
        try:
            response = await self._create_stock_transfer_doc(
                item_code, qty, from_warehouse, to_warehouse, remarks, auto_submit
            )

            return StockTransferOutput(**response)

        except Exception as e:
            self.logger.error(f"Error in create_stock_transfer: {e}", exc_info=True)
            raise

    async def _fetch_stock_levels(
        self,
        item_code: Optional[str],
        item_name: Optional[str],
        warehouses: Optional[str],
        quantity_type: str,
    ) -> dict:
        params = {
            "item_code": item_code,
            "item_name": item_name,
            "warehouses": warehouses,
            "quantity_type": quantity_type,
        }
        params = {k: v for k, v in params.items() if v is not None}

        try:
            result = await self.erpnext.call_method(
                "agent_stock_system.controller.inventory.retrieve_stock_levels",
                method="GET",
                params=params,
            )

            if isinstance(result, dict) and result.get("success") is False:
                raise ValueError(f"Backend error: {result.get('error_message')}")

            return result
        except Exception as e:
            self.logger.error(f"Error in retrieve_stock_levels: {e}")
            raise

    async def _fetch_stock_history(
        self,
        item_code: str,
        item_name: Optional[str],
        warehouse: Optional[str],
        days_back: int,
    ) -> dict:
        params = {
            "item_code": item_code,
            "item_name": item_name,
            "warehouse": warehouse,
            "days_back": days_back,
        }
        params = {k: v for k, v in params.items() if v is not None}

        try:
            result = await self.erpnext.call_method(
                "agent_stock_system.controller.inventory.retrieve_stock_history",
                method="GET",
                params=params,
            )

            if isinstance(result, dict) and result.get("success") is False:
                raise ValueError(f"Backend error: {result.get('error_message')}")

            return result
        except Exception as e:
            self.logger.error(f"Error in retrieve_stock_history: {e}")
            raise

    async def _propose_stock_transfer(
        self,
        item_code: str,
        item_name: Optional[str],
    ) -> dict:
        params = {
            "item_code": item_code,
            "item_name": item_name,
        }
        params = {k: v for k, v in params.items() if v is not None}

        try:
            result = await self.erpnext.call_method(
                "agent_stock_system.controller.inventory.propose_stock_transfer",
                method="GET",
                params=params,
            )

            if isinstance(result, dict) and result.get("success") is False:
                raise ValueError(f"Backend error: {result.get('error_message')}")

            return result
        except Exception as e:
            self.logger.error(f"Error in propose_stock_transfer: {e}")
            raise

    async def _create_stock_transfer_doc(
        self,
        item_code: str,
        qty: float,
        from_warehouse: str,
        to_warehouse: str,
        remarks: Optional[str],
        auto_submit: bool,
    ) -> dict:
        body = {
            "item_code": item_code,
            "qty": qty,
            "from_warehouse": from_warehouse,
            "to_warehouse": to_warehouse,
            "remarks": remarks,
            "auto_submit": auto_submit,
        }
        body = {k: v for k, v in body.items() if v is not None}

        try:
            result = await self.erpnext.call_method(
                "agent_stock_system.controller.inventory.create_stock_transfer",
                method="POST",
                body=body,  # POST cần gửi qua body, không phải params
            )

            if isinstance(result, dict) and result.get("success") is False:
                raise ValueError(f"Backend error: {result.get('error_message')}")

            return result
        except Exception as e:
            self.logger.error(f"Error in create_stock_transfer: {e}")
            raise

    async def cleanup(self) -> None:
        await self.erpnext.close()
