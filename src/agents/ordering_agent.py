import logging

from .worker_agent import WorkerAgent

logger = logging.getLogger(__name__)

AGENT_TYPE = "ordering"
AGENT_DESCRIPTION = """Manages purchase orders, supplier selection, and replenishment optimization. 
Specializes in identifying items needing replenishment, calculating optimal order quantities, 
proposing internal transfers before external purchases, selecting best suppliers based on 
price/lead-time/performance, creating consolidated purchase orders, and monitoring price variance."""

TOOLS_EXAMPLE = """
## Few-shot Examples:

Query: "Kiểm tra các item cần bổ sung trong kho Stores - HP"
→ {"tool_calls": [{"tool_name": "check_replenishment_needs", "parameters": {"warehouses": "Stores - HP", "use_forecast": true, "lookback_days": 30}}]}

Query: "Quét tất cả kho tìm item sắp hết hàng"
→ {"tool_calls": [{"tool_name": "check_replenishment_needs", "parameters": {"warehouses": "", "include_zero_stock": true}}]}

Query: "Tính số lượng đặt tối ưu cho TEE-0014 tại Stores - HP trong 90 ngày tới"
→ {"tool_calls": [{"tool_name": "calculate_optimal_quantity", "parameters": {"item_code": "TEE-0014", "warehouse": "Stores - HP", "horizon_days": 90, "calculation_method": "mean"}}]}

Query: "Check xem có thể chuyển nội bộ 100 cái SHUT-0100 về Stores - HCM không"
→ {"tool_calls": [{"tool_name": "propose_internal_transfer_first", "parameters": {"item_code": "SHUT-0100", "target_warehouse": "Stores - HCM", "needed_qty": 100}}]}

Query: "Tìm nhà cung cấp tốt nhất cho 500 cái ITEM-001"
→ {"tool_calls": [{"tool_name": "select_best_supplier", "parameters": {"item_code": "ITEM-001", "required_qty": 500}}]}

Query: "Chọn NCC cho ITEM-001, cần 200 cái trước ngày 15/2/2025, ưu tiên NCC 001"
→ {"tool_calls": [{"tool_name": "select_best_supplier", "parameters": {"item_code": "ITEM-001", "required_qty": 200, "need_by_date": "2025-02-15", "preferred_suppliers": "NCC 001"}}]}

Query: "Tạo PO cho NCC 001 với 100 TEE-0014 và 50 SHUT-0100 về Stores - HP"
→ {"tool_calls": [{"tool_name": "create_consolidated_po", "parameters": {"supplier": "NCC 001", "items": "[{\\"item_code\\": \\"TEE-0014\\", \\"qty\\": 100, \\"warehouse\\": \\"Stores - HP\\"}, {\\"item_code\\": \\"SHUT-0100\\", \\"qty\\": 50, \\"warehouse\\": \\"Stores - HP\\"}]", "auto_submit": false}}]}

Query: "Kiểm tra giá 120k cho ITEM-001 có hợp lý không"
→ {"tool_calls": [{"tool_name": "monitor_price_variance", "parameters": {"item_code": "ITEM-001", "current_price": 120000, "lookback_days": 90}}]}

Query: "So sánh giá 50k cho TEE-0014 từ NCC 001 với lịch sử 60 ngày"
→ {"tool_calls": [{"tool_name": "monitor_price_variance", "parameters": {"item_code": "TEE-0014", "current_price": 50000, "supplier": "NCC 001", "lookback_days": 60}}]}

Query: "Kiểm tra replenishment rồi đề xuất chuyển nội bộ cho các item thiếu"
→ {"tool_calls": [{"tool_name": "check_replenishment_needs", "parameters": {"warehouses": "", "use_forecast": true}}, {"tool_name": "propose_internal_transfer_first", "parameters": {"item_code": "<from_replenishment_result>", "target_warehouse": "<target>", "needed_qty": "<from_replenishment_result>"}}]}
"""


class OrderingAgent(WorkerAgent):
    def __init__(self, **kwargs):
        super().__init__(
            agent_type=AGENT_TYPE,
            agent_description=AGENT_DESCRIPTION,
            examples=TOOLS_EXAMPLE,
            **kwargs,
        )
