import logging

from pydantic import Field

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

logger = logging.getLogger(__name__)


class ForecastingServerConfig(ServerConfig):
    pass


class ForecastingMCPServer(BaseMCPServer):
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

    async def predict_sales_forecast(
        self,
        item_code: str = Field(
            ..., description="Item code to predict (e.g., 'RCK-0128')"
        ),
        months: int = Field(
            default=2, description="Number of months to predict (1, 2, or 3)"
        ),
    ) -> ForecastOutput | dict:
        """
        Predict next N months sales for a specific item using V2 model.
        """
        try:
            result = predict_sales_forecast_v2(item_code, months)
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

            result = predict_inventory_v3(
                item_code=item_code, warehouse=warehouse, months=months
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
