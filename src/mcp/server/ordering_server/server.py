import logging
from typing import Literal, Optional

from pydantic import Field

from src.communication import get_erpnext_connection
from src.mcp.server.base_server import BaseMCPServer, ServerConfig
from src.typing.mcp.base import ApprovalLevel, HITLMetadata
from src.typing.mcp.ordering import (
    BestSupplierOutput,
    ConsolidatedPOOutput,
    InternalTransferOutput,
    OptimalQuantityOutput,
    PriceVarianceOutput,
    ReplenishmentNeedsOutput,
)

logger = logging.getLogger(__name__)


class OrderingServerConfig(ServerConfig):
    erpnext_url: str = Field(
        default="http://localhost:8001", description="ERPNext base URL"
    )
    erpnext_api_key: Optional[str] = Field(default=None, description="ERPNext API key")
    erpnext_api_secret: Optional[str] = Field(
        default=None, description="ERPNext API secret"
    )
    default_lookback_days: int = Field(
        default=30, ge=1, le=365, description="Default lookback period for analysis"
    )
    default_horizon_days: int = Field(
        default=90, ge=1, le=365, description="Default forecast horizon"
    )
    auto_submit_threshold: float = Field(
        default=100000.0, ge=0, description="Threshold for auto-submit PO"
    )


class OrderingMCPServer(BaseMCPServer):
    def __init__(self, config: OrderingServerConfig):
        super().__init__(config)
        self.ordering_config = config
        self.erpnext = get_erpnext_connection()

    def setup(self) -> None:
        self.logger.info("Setting up Ordering MCP Server tools...")

        # Tool 1: Check replenishment needs
        self.add_tool(
            self.check_replenishment_needs,
            name="check_replenishment_needs",
            description="Scan warehouses to find items needing replenishment based on stock levels and consumption patterns",
            structured_output=True,
        )

        # Tool 2: Calculate optimal quantity
        self.add_tool(
            self.calculate_optimal_quantity,
            name="calculate_optimal_quantity",
            description="Calculate optimal order quantity using statistical methods (mean/median/mode/forecast)",
            structured_output=True,
        )

        # Tool 3: Propose internal transfer first
        self.add_tool(
            self.propose_internal_transfer_first,
            name="propose_internal_transfer_first",
            description="Check if internal warehouse transfer can fulfill needs before purchasing externally",
            structured_output=True,
            hitl=HITLMetadata(
                requires_approval=True,
                approval_level=ApprovalLevel.CONFIRM,
                modifiable_fields=["target_warehouse", "needed_qty"],
                approval_message="Xác nhận đề xuất chuyển kho nội bộ",
                timeout_seconds=120,
            ),
        )

        # Tool 4: Select best supplier
        self.add_tool(
            self.select_best_supplier,
            name="select_best_supplier",
            description="Rank and select best supplier based on price, lead time, OTIF, and quality scores",
            structured_output=True,
        )

        # Tool 5: Create consolidated PO
        self.add_tool(
            self.create_consolidated_po,
            name="create_consolidated_po",
            description="Create consolidated Purchase Order for multiple items from same supplier",
            structured_output=True,
            hitl=HITLMetadata(
                requires_approval=True,
                approval_level=ApprovalLevel.REVIEW,
                modifiable_fields=["supplier", "items", "auto_submit"],
                approval_message="Vui lòng review đơn đặt hàng trước khi tạo",
                timeout_seconds=300,
            ),
        )

        # Tool 6: Monitor price variance
        self.add_tool(
            self.monitor_price_variance,
            name="monitor_price_variance",
            description="Analyze price variance and alert if current price deviates from historical average",
            structured_output=True,
        )

        self.logger.info("✅ All ordering tools registered successfully")

    # ======================== TOOL IMPLEMENTATIONS ========================

    async def check_replenishment_needs(
        self,
        warehouses: Optional[str] = Field(
            None,
            description="Warehouse names (comma-separated or JSON array). Leave empty for all warehouses.",
        ),
        use_forecast: bool = Field(
            default=True,
            description="Use forecast-based calculation instead of simple mean",
        ),
        lookback_days: int = Field(
            default=30,
            ge=1,
            le=365,
            description="Number of historical days for consumption calculation (1-365)",
        ),
        include_zero_stock: bool = Field(
            default=True, description="Include items with zero stock"
        ),
    ) -> ReplenishmentNeedsOutput:
        try:
            response = await self._fetch_replenishment_needs(
                warehouses, use_forecast, lookback_days, include_zero_stock
            )
            return ReplenishmentNeedsOutput(**response)

        except Exception as e:
            self.logger.error(f"Error in check_replenishment_needs: {e}", exc_info=True)
            raise

    async def calculate_optimal_quantity(
        self,
        item_code: Optional[str] = Field(
            None, description="ERPNext item code (required if item_name not provided)"
        ),
        item_name: Optional[str] = Field(
            None, description="Item name for fuzzy search"
        ),
        warehouse: str = Field(..., description="Target warehouse (required)"),
        horizon_days: int = Field(
            default=90,
            ge=1,
            le=365,
            description="Number of days to cover with order (1-365)",
        ),
        lookback_days: int = Field(
            default=30,
            ge=1,
            le=365,
            description="Historical days for consumption analysis (1-365)",
        ),
        calculation_method: Literal["mean", "median", "mode", "forecast"] = Field(
            default="mean",
            description="Statistical method: mean, median, mode, or forecast",
        ),
    ) -> OptimalQuantityOutput:
        try:
            response = await self._calculate_optimal_qty(
                item_code,
                item_name,
                warehouse,
                horizon_days,
                lookback_days,
                calculation_method,
            )
            return OptimalQuantityOutput(**response)

        except Exception as e:
            self.logger.error(
                f"Error in calculate_optimal_quantity: {e}", exc_info=True
            )
            raise

    async def propose_internal_transfer_first(
        self,
        item_code: Optional[str] = Field(
            None, description="ERPNext item code (required if item_name not provided)"
        ),
        item_name: Optional[str] = Field(
            None, description="Item name for fuzzy search"
        ),
        target_warehouse: str = Field(
            ..., description="Warehouse that needs the stock (required)"
        ),
        needed_qty: float = Field(
            ..., gt=0, description="Quantity needed at target warehouse (required, >0)"
        ),
        min_source_doc_days: float = Field(
            default=14.0,
            ge=0,
            description="Minimum Days of Cover to keep at source warehouses",
        ),
    ) -> InternalTransferOutput:
        try:
            response = await self._propose_internal_transfer(
                item_code, item_name, target_warehouse, needed_qty, min_source_doc_days
            )
            return InternalTransferOutput(**response)

        except Exception as e:
            self.logger.error(
                f"Error in propose_internal_transfer_first: {e}", exc_info=True
            )
            raise

    async def select_best_supplier(
        self,
        item_code: Optional[str] = Field(
            None, description="ERPNext item code (required if item_name not provided)"
        ),
        item_name: Optional[str] = Field(
            None, description="Item name for fuzzy search"
        ),
        required_qty: float = Field(
            ..., gt=0, description="Quantity to purchase (required, >0)"
        ),
        need_by_date: Optional[str] = Field(
            None, description="Date by which item is needed (YYYY-MM-DD format)"
        ),
        preferred_suppliers: Optional[str] = Field(
            None,
            description="Comma-separated list of preferred supplier names/codes",
        ),
    ) -> BestSupplierOutput:
        try:
            response = await self._select_best_supplier(
                item_code, item_name, required_qty, need_by_date, preferred_suppliers
            )
            return BestSupplierOutput(**response)

        except Exception as e:
            self.logger.error(f"Error in select_best_supplier: {e}", exc_info=True)
            raise

    async def create_consolidated_po(
        self,
        supplier: str = Field(..., description="Supplier name or code (required)"),
        items: str = Field(
            ...,
            description='JSON array of items: [{"item_code": "...", "qty": 100, "warehouse": "...", "rate": 50.0}]. Rate is optional.',
        ),
        auto_submit: bool = Field(
            default=False, description="Automatically submit PO after creation"
        ),
        auto_submit_threshold: float = Field(
            default=100000.0,
            ge=0,
            description="Only auto-submit if total amount is below this threshold",
        ),
    ) -> ConsolidatedPOOutput:
        try:
            response = await self._create_consolidated_po(
                supplier, items, auto_submit, auto_submit_threshold
            )
            return ConsolidatedPOOutput(**response)

        except Exception as e:
            self.logger.error(f"Error in create_consolidated_po: {e}", exc_info=True)
            raise

    async def monitor_price_variance(
        self,
        item_code: Optional[str] = Field(
            None, description="ERPNext item code (required if item_name not provided)"
        ),
        item_name: Optional[str] = Field(
            None, description="Item name for fuzzy search"
        ),
        current_price: float = Field(
            ..., gt=0, description="Current/proposed price to check (required, >0)"
        ),
        supplier: Optional[str] = Field(
            None, description="Filter history by specific supplier"
        ),
        lookback_days: int = Field(
            default=90,
            ge=1,
            le=365,
            description="Number of historical days to analyze (1-365)",
        ),
    ) -> PriceVarianceOutput:
        try:
            response = await self._monitor_price_variance(
                item_code, item_name, current_price, supplier, lookback_days
            )
            return PriceVarianceOutput(**response)

        except Exception as e:
            self.logger.error(f"Error in monitor_price_variance: {e}", exc_info=True)
            raise

    # ======================== PRIVATE HELPER METHODS ========================

    async def _fetch_replenishment_needs(
        self,
        warehouses: Optional[str],
        use_forecast: bool,
        lookback_days: int,
        include_zero_stock: bool,
    ) -> dict:
        params = {
            "warehouses": warehouses or "",
            "use_forecast": use_forecast,
            "lookback_days": lookback_days,
            "include_zero_stock": include_zero_stock,
        }

        try:
            result = await self.erpnext.call_method(
                "agent_stock_system.controller.ordering.check_replenishment_needs",
                method="GET",
                params=params,
            )

            if isinstance(result, dict) and result.get("success") is False:
                raise ValueError(f"Backend error: {result.get('error')}")

            return result
        except Exception as e:
            self.logger.error(f"Error fetching replenishment needs: {e}")
            raise

    async def _calculate_optimal_qty(
        self,
        item_code: Optional[str],
        item_name: Optional[str],
        warehouse: str,
        horizon_days: int,
        lookback_days: int,
        calculation_method: str,
    ) -> dict:
        params = {
            "warehouse": warehouse,
            "horizon_days": horizon_days,
            "lookback_days": lookback_days,
            "calculation_method": calculation_method,
        }
        if item_code:
            params["item_code"] = item_code
        if item_name:
            params["item_name"] = item_name

        try:
            result = await self.erpnext.call_method(
                "agent_stock_system.controller.ordering.calculate_optimal_quantity",
                method="GET",
                params=params,
            )

            if isinstance(result, dict) and result.get("success") is False:
                raise ValueError(f"Backend error: {result.get('error')}")

            return result
        except Exception as e:
            self.logger.error(f"Error calculating optimal quantity: {e}")
            raise

    async def _propose_internal_transfer(
        self,
        item_code: Optional[str],
        item_name: Optional[str],
        target_warehouse: str,
        needed_qty: float,
        min_source_doc_days: float,
    ) -> dict:
        params = {
            "target_warehouse": target_warehouse,
            "needed_qty": needed_qty,
            "min_source_doc_days": min_source_doc_days,
        }
        if item_code:
            params["item_code"] = item_code
        if item_name:
            params["item_name"] = item_name

        try:
            result = await self.erpnext.call_method(
                "agent_stock_system.controller.ordering.propose_internal_transfer_first",
                method="GET",
                params=params,
            )

            if isinstance(result, dict) and result.get("success") is False:
                raise ValueError(f"Backend error: {result.get('error')}")

            return result
        except Exception as e:
            self.logger.error(f"Error proposing internal transfer: {e}")
            raise

    async def _select_best_supplier(
        self,
        item_code: Optional[str],
        item_name: Optional[str],
        required_qty: float,
        need_by_date: Optional[str],
        preferred_suppliers: Optional[str],
    ) -> dict:
        params = {
            "required_qty": required_qty,
        }
        if item_code:
            params["item_code"] = item_code
        if item_name:
            params["item_name"] = item_name
        if need_by_date:
            params["need_by_date"] = need_by_date
        if preferred_suppliers:
            params["preferred_suppliers"] = preferred_suppliers

        try:
            result = await self.erpnext.call_method(
                "agent_stock_system.controller.ordering.select_best_supplier",
                method="GET",
                params=params,
            )

            if isinstance(result, dict) and result.get("success") is False:
                raise ValueError(f"Backend error: {result.get('error')}")

            return result
        except Exception as e:
            self.logger.error(f"Error selecting best supplier: {e}")
            raise

    async def _create_consolidated_po(
        self,
        supplier: str,
        items: str,
        auto_submit: bool,
        auto_submit_threshold: float,
    ) -> dict:
        params = {
            "supplier": supplier,
            "items": items,
            "auto_submit": auto_submit,
            "auto_submit_threshold": auto_submit_threshold,
        }

        try:
            result = await self.erpnext.call_method(
                "agent_stock_system.controller.ordering.create_consolidated_po",
                method="GET",
                params=params,
            )

            if isinstance(result, dict) and result.get("success") is False:
                raise ValueError(f"Backend error: {result.get('error')}")

            return result
        except Exception as e:
            self.logger.error(f"Error creating consolidated PO: {e}")
            raise

    async def _monitor_price_variance(
        self,
        item_code: Optional[str],
        item_name: Optional[str],
        current_price: float,
        supplier: Optional[str],
        lookback_days: int,
    ) -> dict:
        params = {
            "current_price": current_price,
            "lookback_days": lookback_days,
        }
        if item_code:
            params["item_code"] = item_code
        if item_name:
            params["item_name"] = item_name
        if supplier:
            params["supplier"] = supplier

        try:
            result = await self.erpnext.call_method(
                "agent_stock_system.controller.ordering.monitor_price_variance",
                method="GET",
                params=params,
            )

            if isinstance(result, dict) and result.get("success") is False:
                raise ValueError(f"Backend error: {result.get('error')}")

            return result
        except Exception as e:
            self.logger.error(f"Error monitoring price variance: {e}")
            raise

    async def cleanup(self) -> None:
        await self.erpnext.close()
