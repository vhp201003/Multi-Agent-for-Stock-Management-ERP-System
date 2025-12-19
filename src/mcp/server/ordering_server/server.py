import logging
from typing import Literal, Optional

from pydantic import Field

from src.communication import get_erpnext_connection
from src.mcp.server.base_server import BaseMCPServer, ServerConfig
from src.typing.mcp.base import ApprovalLevel, HITLMetadata
from src.typing.mcp.ordering import (
    BestSupplierOutput,
    ConsolidatedPOOutput,
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
            description="Phân tích nhu cầu bổ sung kho hàng bằng cách quét các kho để tìm các item có mức tồn kho dưới mức tối thiểu, tính toán mức tiêu thụ trung bình hàng ngày, đánh giá mức độ khẩn cấp (critical/high/medium/low) và đề xuất số lượng bổ sung tối ưu",
            structured_output=True,
        )

        # Tool 2: Calculate optimal quantity
        self.add_tool(
            self.calculate_optimal_quantity,
            name="calculate_optimal_quantity",
            description="Tính toán số lượng đặt hàng tối ưu dựa trên các phương pháp thống kê (trung bình/trung vị/mode/dự báo), xem xét nhu cầu cơ bản, hàng dự phòng, nhu cầu trong thời gian chờ hàng, và điều chỉnh tối thiểu số lượng đặt hàng (MOQ)",
            structured_output=True,
        )

        # Tool 3: Select best supplier
        self.add_tool(
            self.select_best_supplier,
            name="select_best_supplier",
            description="Xếp hạng và lựa chọn nhà cung cấp tốt nhất dựa trên các tiêu chí: giá cả, thời gian giao hàng, đánh giá On-Time In-Full (OTIF), chất lượng sản phẩm, với hỗ trợ lọc theo nhà cung cấp ưu tiên và thời gian cần thiết",
            structured_output=True,
        )

        # Tool 4: Create consolidated PO
        self.add_tool(
            self.create_consolidated_po,
            name="create_consolidated_po",
            description="Tạo đơn đặt hàng (PO) hợp nhất cho nhiều item từ cùng một nhà cung cấp, hỗ trợ tự động gửi duyệt nếu tổng giá trị dưới ngưỡng cho phép, với khả năng tìm kiếm mô hồ item và lấy giá từ lịch sử mua hàng",
            structured_output=True,
            hitl=HITLMetadata(
                requires_approval=True,
                approval_level=ApprovalLevel.REVIEW,
                modifiable_fields=["supplier", "items", "auto_submit"],
                approval_message="Vui lòng review đơn đặt hàng trước khi tạo",
                timeout_seconds=300,
            ),
        )

        # Tool 5: Monitor price variance
        self.add_tool(
            self.monitor_price_variance,
            name="monitor_price_variance",
            description="Phân tích sự biến động giá cả bằng cách so sánh giá hiện tại/đề xuất với lịch sử giá trung bình, tìm giá tối thiểu/tối đa, phát hiện xu hướng giá (tăng/giảm/ổn định), và đề xuất hành động (chấp nhận/thương lượng/từ chối/xem xét) dựa trên độ tin cậy của dữ liệu",
            structured_output=True,
        )

        self.logger.info("✅ All ordering tools registered successfully")

    # ======================== TOOL IMPLEMENTATIONS ========================

    async def check_replenishment_needs(
        self,
        item_code: Optional[str] = Field(
            None, description="ERPNext item code (required if item_name not provided)"
        ),
        item_name: Optional[str] = Field(
            None,
            description="Item name for fuzzy search (required if item_code not provided)",
        ),
        lookback_days: int = Field(
            default=30,
            ge=1,
            le=365,
            description="Number of historical days for consumption calculation (1-365)",
        ),
    ) -> ReplenishmentNeedsOutput:
        try:
            response = await self._fetch_replenishment_needs(
                item_code=item_code,
                item_name=item_name,
                lookback_days=lookback_days,
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

    async def select_best_supplier(
        self,
        item_code: Optional[str] = Field(
            None, description="ERPNext item code (required if item_name not provided)"
        ),
        item_name: Optional[str] = Field(
            None, description="Item name for fuzzy search"
        ),
    ) -> BestSupplierOutput:
        try:
            response = await self._select_best_supplier(item_code, item_name)
            return BestSupplierOutput(**response)

        except Exception as e:
            self.logger.error(f"Error in select_best_supplier: {e}", exc_info=True)
            raise

    async def create_consolidated_po(
        self,
        supplier: str = Field(..., description="Supplier name or code (required)"),
        items: str = Field(
            ...,
            description="""
            items: JSON array of items. Each item should contain:
			- item_code (required): ERPNext item code or name for fuzzy search
			- qty (required): Quantity to order
			- warehouse (optional): Target warehouse (uses default if not provided)
			- rate (optional): Unit rate (looks up from supplier history if not provided)

            Example items JSON:
            [
                {"item_code": "ITEM-001", "qty": 10, "warehouse": "WH-01", "rate": 100.0},
                {"item_code": "ITEM-002", "qty": 5}  # warehouse and rate are auto-resolved
            ]
            """,
        ),
        auto_submit: bool = Field(
            default=False,
            description="this field flag to auto submit the po, default is False",
        ),
    ) -> ConsolidatedPOOutput:
        try:
            response = await self._create_consolidated_po(supplier, items, auto_submit)
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
                item_code, item_name, supplier, lookback_days
            )
            return PriceVarianceOutput(**response)

        except Exception as e:
            self.logger.error(f"Error in monitor_price_variance: {e}", exc_info=True)
            raise

    # ======================== PRIVATE HELPER METHODS ========================

    async def _fetch_replenishment_needs(
        self,
        item_code: Optional[str],
        item_name: Optional[str],
        lookback_days: int,
    ) -> dict:
        params = {
            "item_code": item_code or "",
            "item_name": item_name or "",
            "lookback_days": lookback_days,
        }

        try:
            result = await self.erpnext.call_method(
                "agent_stock_system.controller.ordering.check_replenishment_needs",
                method="GET",
                params=params,
            )

            if isinstance(result, dict) and result.get("success") is False:
                raise ValueError(f"Backend error: {result.get('error_message')}")

            return result
        except Exception as e:
            self.logger.error(f"Error fetching replenishment needs: {e}")
            raise

    async def _calculate_optimal_qty(
        self,
        item_code: Optional[str],
        item_name: Optional[str],
        horizon_days: int,
        lookback_days: int,
        calculation_method: str,
    ) -> dict:
        params = {
            "item_code": item_code,
            "item_name": item_name,
            "horizon_days": horizon_days,
            "lookback_days": lookback_days,
            "calculation_method": calculation_method,
        }

        try:
            result = await self.erpnext.call_method(
                "agent_stock_system.controller.ordering.calculate_optimal_quantity",
                method="GET",
                params=params,
            )

            if isinstance(result, dict) and result.get("success") is False:
                raise ValueError(f"Backend error: {result.get('error_message')}")

            return result
        except Exception as e:
            self.logger.error(f"Error calculating optimal quantity: {e}")
            raise

    async def _select_best_supplier(
        self,
        item_code: Optional[str],
        item_name: Optional[str],
    ) -> dict:
        params = {
            "item_code": item_code,
            "item_name": item_name,
        }
        try:
            result = await self.erpnext.call_method(
                "agent_stock_system.controller.ordering.select_best_supplier",
                method="GET",
                params=params,
            )

            if isinstance(result, dict) and result.get("success") is False:
                raise ValueError(f"Backend error: {result.get('error_message')}")

            return result
        except Exception as e:
            self.logger.error(f"Error selecting best supplier: {e}")
            raise

    async def _create_consolidated_po(
        self,
        supplier: str,
        items: str,
        auto_submit: bool,
    ) -> dict:
        params = {
            "supplier": supplier,
            "items": items,
            "auto_submit": auto_submit,
        }

        try:
            result = await self.erpnext.call_method(
                "agent_stock_system.controller.ordering.create_consolidated_po",
                method="GET",
                params=params,
            )

            if isinstance(result, dict) and result.get("success") is False:
                raise ValueError(f"Backend error: {result.get('error_message')}")

            return result
        except Exception as e:
            self.logger.error(f"Error creating consolidated PO: {e}")
            raise

    async def _monitor_price_variance(
        self,
        item_code: Optional[str],
        item_name: Optional[str],
        supplier: Optional[str],
        lookback_days: int,
    ) -> dict:
        params = {
            "item_code": item_code,
            "item_name": item_name,
            "supplier": supplier,
            "lookback_days": lookback_days,
        }

        try:
            result = await self.erpnext.call_method(
                "agent_stock_system.controller.ordering.monitor_price_variance",
                method="GET",
                params=params,
            )

            if isinstance(result, dict) and result.get("success") is False:
                raise ValueError(f"Backend error: {result.get('error_message')}")

            return result
        except Exception as e:
            self.logger.error(f"Error monitoring price variance: {e}")
            raise

    async def cleanup(self) -> None:
        await self.erpnext.close()
