import logging

from pydantic import Field

from src.mcp.server.base_server import BaseMCPServer, ServerConfig
from src.mcp.server.forecasting_server.forecast_api_v2 import predict_sales_forecast_v2
from src.typing.mcp.forecasting import ForecastFilters, ForecastOutput

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
