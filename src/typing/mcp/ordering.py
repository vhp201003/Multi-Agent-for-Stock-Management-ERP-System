from pydantic import BaseModel, Field

from src.typing.mcp.base import MCPToolOutputSchema


# ============================== Tool 1: check_replenishment_needs ============================== #
class ReplenishmentNeedItem(BaseModel):
    """Schema for individual item in check_replenishment_needs output."""

    item_code: str = Field(..., description="ERPNext item code")
    item_name: str = Field(..., description="Item name")
    warehouse: str = Field(..., description="Warehouse name")
    current_stock: float = Field(..., description="Current stock quantity")
    min_qty: float = Field(
        ..., description="Minimum quantity threshold (reorder level)"
    )
    max_qty: float = Field(..., description="Maximum quantity threshold")
    avg_daily_consumption: float = Field(
        ..., description="Average daily consumption based on historical data"
    )
    doc_days: float = Field(
        ..., description="Days of Cover = current_stock / avg_daily_consumption"
    )
    shortage_qty: float = Field(
        ..., description="Quantity below min level (0 if above min)"
    )
    recommended_qty: float = Field(..., description="Recommended quantity to order")
    urgency: str = Field(..., description="Urgency level: critical, high, medium, low")


class ReplenishmentNeedsFilters(BaseModel):
    """Schema for filters_applied in check_replenishment_needs."""

    warehouses: list[str] = Field(..., description="List of warehouse names analyzed")
    use_forecast: bool = Field(
        ..., description="Whether forecast was used for calculation"
    )
    lookback_days: int = Field(..., description="Days used for consumption calculation")
    include_zero_stock: bool = Field(
        ..., description="Whether items with zero stock are included"
    )


class ReplenishmentNeedsSummary(BaseModel):
    """Schema for summary in check_replenishment_needs."""

    total_items_need_replenishment: int = Field(
        ..., description="Total items needing replenishment"
    )
    critical_items: int = Field(
        ..., description="Items with critical urgency (stock < 3 days)"
    )
    high_items: int = Field(..., description="Items with high urgency (stock < 7 days)")
    medium_items: int = Field(
        ..., description="Items with medium urgency (stock < 14 days)"
    )
    total_shortage_value: float = Field(
        ..., description="Estimated total value of shortage"
    )


class ReplenishmentNeedsOutput(MCPToolOutputSchema):
    """Schema for check_replenishment_needs tool output."""

    items: list[ReplenishmentNeedItem] = Field(
        ..., description="List of items needing replenishment"
    )
    summary: ReplenishmentNeedsSummary
    filters_applied: ReplenishmentNeedsFilters


# ============================== Tool 2: calculate_optimal_quantity ============================== #
class OptimalQuantityBreakdown(BaseModel):
    """Schema for breakdown of optimal quantity calculation."""

    base_demand: float = Field(..., description="Base demand from historical average")
    safety_stock: float = Field(..., description="Safety stock quantity")
    lead_time_demand: float = Field(..., description="Demand during lead time")
    forecast_adjustment: float = Field(
        ..., description="Adjustment based on forecast/trend"
    )
    moq_adjustment: float = Field(..., description="Adjustment to meet MOQ")


class OptimalQuantityItem(BaseModel):
    """Schema for calculate_optimal_quantity output."""

    item_code: str = Field(..., description="ERPNext item code")
    item_name: str = Field(..., description="Item name")
    warehouse: str = Field(..., description="Warehouse name")
    current_stock: float = Field(..., description="Current stock quantity")
    recommended_qty: float = Field(..., description="Optimal quantity to order")
    moq: float = Field(..., description="Minimum Order Quantity from supplier")
    lead_time_days: int = Field(..., description="Lead time in days")
    reorder_level: float = Field(..., description="Reorder level (min_qty)")
    breakdown: OptimalQuantityBreakdown = Field(
        ..., description="Breakdown of calculation"
    )
    calculation_method: str = Field(
        ..., description="Method used: mean, median, mode, forecast"
    )


class OptimalQuantityFilters(BaseModel):
    """Schema for filters_applied in calculate_optimal_quantity."""

    item_code: str = Field(..., description="Item code analyzed")
    warehouse: str = Field(..., description="Warehouse analyzed")
    horizon_days: int = Field(..., description="Forecast horizon in days")
    lookback_days: int = Field(..., description="Historical data lookback period")
    calculation_method: str = Field(..., description="Calculation method used")


class OptimalQuantitySummary(BaseModel):
    """Schema for summary in calculate_optimal_quantity."""

    total_recommended_qty: float = Field(..., description="Total recommended quantity")
    total_estimated_cost: float = Field(
        ..., description="Estimated cost based on last purchase price"
    )
    avg_daily_consumption: float = Field(..., description="Average daily consumption")
    projected_doc_days: float = Field(
        ..., description="Projected Days of Cover after ordering"
    )


class OptimalQuantityOutput(MCPToolOutputSchema):
    """Schema for calculate_optimal_quantity tool output."""

    item: OptimalQuantityItem = Field(
        ..., description="Optimal quantity calculation result"
    )
    summary: OptimalQuantitySummary
    filters_applied: OptimalQuantityFilters


# ============================== Tool 3: propose_internal_transfer_first ============================== #
class InternalTransferSource(BaseModel):
    """Schema for transfer source warehouse."""

    from_warehouse: str = Field(..., description="Source warehouse name")
    available_qty: float = Field(..., description="Available quantity for transfer")
    transfer_qty: float = Field(..., description="Recommended transfer quantity")
    doc_days_after: float = Field(..., description="DoC at source after transfer")


class InternalTransferItem(BaseModel):
    """Schema for individual item in propose_internal_transfer_first output."""

    item_code: str = Field(..., description="ERPNext item code")
    item_name: str = Field(..., description="Item name")
    target_warehouse: str = Field(..., description="Target warehouse needing stock")
    needed_qty: float = Field(..., description="Quantity needed at target")
    total_transferable: float = Field(
        ..., description="Total quantity that can be transferred"
    )
    remaining_to_purchase: float = Field(
        ..., description="Quantity still needed after transfer"
    )
    sources: list[InternalTransferSource] = Field(
        ..., description="List of source warehouses"
    )
    can_fulfill_internally: bool = Field(
        ..., description="Whether need can be fully met internally"
    )


class InternalTransferFilters(BaseModel):
    """Schema for filters_applied in propose_internal_transfer_first."""

    item_code: str = Field(..., description="Item code analyzed")
    target_warehouse: str = Field(..., description="Target warehouse")
    needed_qty: float = Field(..., description="Quantity needed")
    min_source_doc_days: float = Field(..., description="Minimum DoC to keep at source")


class InternalTransferSummary(BaseModel):
    """Schema for summary in propose_internal_transfer_first."""

    total_transferable: float = Field(
        ..., description="Total quantity that can be transferred"
    )
    total_sources: int = Field(..., description="Number of source warehouses available")
    savings_estimate: float = Field(
        ..., description="Estimated savings vs purchasing new"
    )
    fulfillment_pct: float = Field(
        ..., description="Percentage of need that can be fulfilled internally"
    )


class InternalTransferOutput(MCPToolOutputSchema):
    """Schema for propose_internal_transfer_first tool output."""

    transfer_proposal: InternalTransferItem = Field(
        ..., description="Transfer proposal details"
    )
    summary: InternalTransferSummary
    filters_applied: InternalTransferFilters


# ============================== Tool 4: select_best_supplier ============================== #
class SupplierScore(BaseModel):
    """Schema for supplier scoring breakdown."""

    price_score: float = Field(..., description="Price competitiveness score (0-100)")
    lead_time_score: float = Field(..., description="Lead time score (0-100)")
    otif_score: float = Field(..., description="On-Time In-Full delivery score (0-100)")
    quality_score: float = Field(..., description="Quality/return rate score (0-100)")
    overall_score: float = Field(..., description="Weighted overall score (0-100)")


class SupplierOption(BaseModel):
    """Schema for individual supplier option."""

    supplier: str = Field(..., description="Supplier ID/name")
    supplier_name: str = Field(..., description="Supplier display name")
    unit_price: float = Field(..., description="Unit price for this quantity")
    total_price: float = Field(..., description="Total price for required quantity")
    lead_time_days: int = Field(..., description="Lead time in days")
    moq: float = Field(..., description="Minimum Order Quantity")
    last_purchase_date: str | None = Field(
        None, description="Date of last purchase from this supplier"
    )
    discount_pct: float = Field(0.0, description="Applicable discount percentage")
    scores: SupplierScore = Field(..., description="Scoring breakdown")
    is_recommended: bool = Field(
        ..., description="Whether this is the recommended supplier"
    )
    notes: str | None = Field(None, description="Additional notes or warnings")


class BestSupplierFilters(BaseModel):
    """Schema for filters_applied in select_best_supplier."""

    item_code: str = Field(..., description="Item code to purchase")
    required_qty: float = Field(..., description="Quantity required")
    need_by_date: str | None = Field(None, description="Date by which item is needed")
    preferred_suppliers: list[str] | None = Field(
        None, description="List of preferred suppliers"
    )


class BestSupplierSummary(BaseModel):
    """Schema for summary in select_best_supplier."""

    total_suppliers_evaluated: int = Field(
        ..., description="Number of suppliers evaluated"
    )
    best_price: float = Field(..., description="Best available price")
    fastest_lead_time: int = Field(..., description="Fastest lead time in days")
    price_range_pct: float = Field(
        ..., description="Price range as percentage (max-min)/min"
    )


class BestSupplierOutput(MCPToolOutputSchema):
    """Schema for select_best_supplier tool output."""

    suppliers: list[SupplierOption] = Field(
        ..., description="List of supplier options ranked"
    )
    recommended: SupplierOption | None = Field(None, description="Recommended supplier")
    summary: BestSupplierSummary
    filters_applied: BestSupplierFilters


# ============================== Tool 5: create_consolidated_po ============================== #
class POLineItem(BaseModel):
    """Schema for individual line item in PO."""

    item_code: str = Field(..., description="ERPNext item code")
    item_name: str = Field(..., description="Item name")
    qty: float = Field(..., description="Quantity ordered")
    rate: float = Field(..., description="Unit rate")
    amount: float = Field(..., description="Line total amount")
    warehouse: str = Field(..., description="Target warehouse")


class CreatedPO(BaseModel):
    """Schema for created Purchase Order."""

    po_name: str = Field(..., description="Purchase Order ID (e.g., PO-2025-00123)")
    supplier: str = Field(..., description="Supplier ID")
    supplier_name: str = Field(..., description="Supplier display name")
    status: str = Field(..., description="PO status: Draft, Submitted")
    total_qty: float = Field(..., description="Total quantity across all items")
    total_amount: float = Field(..., description="Total PO amount")
    items_count: int = Field(..., description="Number of line items")
    items: list[POLineItem] = Field(..., description="List of line items")
    auto_submitted: bool = Field(..., description="Whether PO was auto-submitted")


class POItemInput(BaseModel):
    """Schema for input item when creating PO."""

    item_code: str = Field(..., description="ERPNext item code")
    qty: float = Field(..., description="Quantity to order")
    warehouse: str = Field(..., description="Target warehouse")
    rate: float | None = Field(None, description="Optional rate override")


class ConsolidatedPOFilters(BaseModel):
    """Schema for filters_applied in create_consolidated_po."""

    supplier: str = Field(..., description="Supplier for the PO")
    items_count: int = Field(..., description="Number of items in request")
    auto_submit: bool = Field(..., description="Whether auto-submit was enabled")
    auto_submit_threshold: float = Field(..., description="Threshold for auto-submit")


class ConsolidatedPOSummary(BaseModel):
    """Schema for summary in create_consolidated_po."""

    total_pos_created: int = Field(..., description="Number of POs created")
    total_amount: float = Field(..., description="Total value of all POs")
    total_items: int = Field(..., description="Total line items across all POs")
    auto_submitted_count: int = Field(..., description="Number of POs auto-submitted")
    draft_count: int = Field(..., description="Number of POs left as Draft")


class ConsolidatedPOOutput(MCPToolOutputSchema):
    """Schema for create_consolidated_po tool output."""

    purchase_orders: list[CreatedPO] = Field(
        ..., description="List of created Purchase Orders"
    )
    summary: ConsolidatedPOSummary
    filters_applied: ConsolidatedPOFilters


# ============================== Tool 6: monitor_price_variance ============================== #
class PriceHistoryPoint(BaseModel):
    """Schema for historical price point."""

    date: str = Field(..., description="Date of purchase (YYYY-MM-DD)")
    rate: float = Field(..., description="Purchase rate")
    qty: float = Field(..., description="Quantity purchased")
    supplier: str = Field(..., description="Supplier name")
    po_name: str = Field(..., description="Purchase Order reference")


class PriceVarianceItem(BaseModel):
    """Schema for individual item in monitor_price_variance output."""

    item_code: str = Field(..., description="ERPNext item code")
    item_name: str = Field(..., description="Item name")
    current_price: float = Field(..., description="Current/proposed price")
    avg_price: float = Field(..., description="Average price over lookback period")
    min_price: float = Field(..., description="Minimum price in lookback period")
    max_price: float = Field(..., description="Maximum price in lookback period")
    median_price: float = Field(..., description="Median price in lookback period")
    delta_pct: float = Field(..., description="Percentage difference from average")
    delta_from_min_pct: float = Field(
        ..., description="Percentage difference from minimum"
    )
    action: str = Field(
        ..., description="Recommended action: accept, negotiate, reject, review"
    )
    price_trend: str = Field(..., description="Price trend: rising, falling, stable")
    history: list[PriceHistoryPoint] = Field(..., description="Recent price history")


class PriceVarianceFilters(BaseModel):
    """Schema for filters_applied in monitor_price_variance."""

    item_code: str = Field(..., description="Item code analyzed")
    supplier: str | None = Field(None, description="Specific supplier analyzed")
    current_price: float = Field(
        ..., description="Current/proposed price being compared"
    )
    lookback_days: int = Field(..., description="Days of history analyzed")


class PriceVarianceSummary(BaseModel):
    """Schema for summary in monitor_price_variance."""

    variance_pct: float = Field(..., description="Overall price variance percentage")
    data_points: int = Field(..., description="Number of historical data points")
    confidence_level: str = Field(
        ..., description="Confidence level: high, medium, low"
    )
    recommendation: str = Field(..., description="Overall recommendation")


class PriceVarianceOutput(MCPToolOutputSchema):
    """Schema for monitor_price_variance tool output."""

    analysis: PriceVarianceItem = Field(..., description="Price variance analysis")
    summary: PriceVarianceSummary
    filters_applied: PriceVarianceFilters
