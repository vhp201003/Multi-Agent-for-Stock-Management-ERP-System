import logging

from pydantic import Field

from src.communication.erpnext import get_erpnext_connection
from src.mcp.server.base_server import BaseMCPServer, ServerConfig
from src.mcp.server.forecasting_server.forecast_api_v2 import predict_sales_forecast_v2
from src.mcp.server.forecasting_server.inventory_forecast_api_v3 import (
    predict_inventory_v3,
)
from src.typing.mcp.forecasting import (
    ForecastFilters,
    ForecastOutput,
    InventoryForecastFilters,
    InventoryForecastOutput,
)
from src.utils.fuzzy_search import fuzzy_search_best_match

logger = logging.getLogger(__name__)


class ForecastingServerConfig(ServerConfig):
    pass


class ForecastingMCPServer(BaseMCPServer):
    def __init__(self, config: ForecastingServerConfig):
        super().__init__(config)
        self.items_cache = []  # List of item codes
        self.item_names_map = {}  # Map item_name -> item_code
        self.warehouses_cache = []
        self.erpnext = get_erpnext_connection()

    async def _ensure_master_data(self):
        """Fetch master data if caches are empty"""
        if not self.items_cache:
            try:
                items = await self.erpnext.get_list(
                    "Item", fields=["item_code", "item_name"]
                )
                self.items_cache = [i["item_code"] for i in items]
                self.item_names_map = {
                    i["item_name"]: i["item_code"] for i in items if i.get("item_name")
                }
                logger.info(
                    f"Cached {len(self.items_cache)} items and {len(self.item_names_map)} names for fuzzy search"
                )
            except Exception as e:
                logger.error(f"Failed to fetch items for fuzzy search: {e}")

        if not self.warehouses_cache:
            try:
                warehouses = await self.erpnext.get_list("Warehouse", fields=["name"])
                self.warehouses_cache = [w["name"] for w in warehouses]
                logger.info(
                    f"Cached {len(self.warehouses_cache)} warehouses for fuzzy search"
                )
            except Exception as e:
                logger.error(f"Failed to fetch warehouses for fuzzy search: {e}")

    async def _fuzzy_match_item(self, item_code: str) -> str:
        if not item_code or item_code.upper() == "ALL":
            return item_code

        await self._ensure_master_data()

        # 1. Try exact match on item_code (case-insensitive)
        for item in self.items_cache:
            if item.lower() == item_code.lower():
                return item

        # 2. Try fuzzy match on item_code
        match_code = fuzzy_search_best_match(
            item_code, self.items_cache, threshold=0.8
        )  # Higher threshold for codes
        if match_code:
            logger.info(f"Fuzzy matched item code '{item_code}' to '{match_code}'")
            return match_code

        # 3. Try fuzzy match on item_name
        item_names = list(self.item_names_map.keys())
        match_name = fuzzy_search_best_match(item_code, item_names, threshold=0.6)
        if match_name:
            resolved_code = self.item_names_map[match_name]
            logger.info(
                f"Fuzzy matched item name '{item_code}' to '{match_name}' ({resolved_code})"
            )
            return resolved_code

        return item_code

    async def _fuzzy_match_warehouse(self, warehouse: str) -> str:
        if not warehouse or warehouse.upper() == "ALL":
            return warehouse

        await self._ensure_master_data()

        # Try exact match first (case-insensitive)
        for wh in self.warehouses_cache:
            if wh.lower() == warehouse.lower():
                return wh

        # Try fuzzy match
        match = fuzzy_search_best_match(warehouse, self.warehouses_cache, threshold=0.5)
        if match:
            logger.info(f"Fuzzy matched warehouse '{warehouse}' to '{match}'")
            return match

        return warehouse

    def setup(self) -> None:
        self.add_tool(
            self.predict_sales_forecast,
            name="predict_sales_forecast",
            description="Predict sales forecast for a specific item using V2 model",
        )
        self.add_tool(
            self.predict_inventory_forecast,
            name="predict_inventory_forecast",
            description="Predict inventory levels for specific items and warehouses using V3 model",
        )

    async def _resolve_item_identifier(
        self, item_code: str | None, item_name: str | None
    ) -> str | None:
        """
        Resolve item identifier from code or name.
        Prioritizes item_name if provided, otherwise checks item_code.
        """
        # If we have a specific item name, try to match it first
        if item_name:
            matched = await self._fuzzy_match_item(item_name)
            if matched and matched != item_name:
                return matched
            # If fuzzy match returned same string (no match found in cache),
            # but we have item_code, we might fall back to item_code.
            # But _fuzzy_match_item returns the input if no match.
            # So if it returned item_name, it means no match.

        # If we have item_code (which might be a name), try to match it
        if item_code:
            return await self._fuzzy_match_item(item_code)

        return None

    async def predict_sales_forecast(
        self,
        item_code: str = Field(
            ..., description="Item code to predict (e.g., 'RCK-0128')"
        ),
        item_name: str | None = Field(
            default=None, description="Item name to predict (e.g., 'Rocking Chair')"
        ),
        months: int = Field(
            default=2, description="Number of months to predict (1, 2, or 3)"
        ),
    ) -> ForecastOutput | dict:
        """
        Predict next N months sales for a specific item using V2 model.
        """
        try:
            # Resolve item
            matched_item = await self._resolve_item_identifier(item_code, item_name)

            # If resolution failed (returned None) but we have item_code, use it as is
            final_item = matched_item if matched_item else item_code

            result = predict_sales_forecast_v2(final_item, months)
            return result
        except Exception as e:
            logger.error(f"Error in predict_sales_forecast: {e}")
            return ForecastOutput(
                success=False,
                error=str(e),
                filters_applied=ForecastFilters(item_code=item_code, months=months),
            )

    async def predict_inventory_forecast(
        self,
        item_code: str | None = Field(
            default=None,
            description="Item code to predict (e.g., 'ACC-0001'). If None or 'ALL', predicts for top 10 items.",
        ),
        item_name: str | None = Field(
            default=None,
            description="Item name to predict (e.g., 'Accounting Software License'). If None or 'ALL', predicts for top 10 items.",
        ),
        warehouse: str = Field(
            default="ALL",
            description="Warehouse name (e.g., 'Kho Hà Nội - HP') or 'ALL'",
        ),
        months: int = Field(
            default=2, description="Number of months to predict (1, 2, or 3)"
        ),
    ) -> InventoryForecastOutput | dict:
        """
        Predict next N months inventory for item-warehouse combinations.
        """
        try:
            # Map "ALL" item_code to None if passed as string "ALL"
            if item_code and item_code.upper() == "ALL":
                item_code = None
            if item_name and item_name.upper() == "ALL":
                item_name = None

            # Resolve item
            matched_item = await self._resolve_item_identifier(item_code, item_name)

            # Resolve warehouse
            matched_warehouse = await self._fuzzy_match_warehouse(warehouse)

            result = predict_inventory_v3(
                item_code=matched_item, warehouse=matched_warehouse, months=months
            )
            return result
        except Exception as e:
            logger.error(f"Error in predict_inventory_forecast: {e}")
            return InventoryForecastOutput(
                success=False,
                error=str(e),
                filters_applied=InventoryForecastFilters(
                    item_code=item_code if item_code else "ALL",
                    warehouse=warehouse,
                    months=months,
                ),
            )
