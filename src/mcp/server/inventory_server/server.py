import logging
from typing import Dict, List, Literal, Optional

import httpx
from pydantic import Field

from src.mcp.server.base_server import BaseMCPServer, ServerConfig
from src.typing.mcp.inventory import (
    CheckStockOutput,
    InventoryHealthOutput,
    ProposeTransferOutput,
    StockHistoryOutput,
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
        self.http_client: Optional[httpx.AsyncClient] = None
        self.logger.info(
            f"Inventory server initialized with ERPNext URL: {config.erpnext_url}"
        )

    def setup(self) -> None:
        self.logger.info("Setting up Inventory MCP Server tools...")

        self.http_client = httpx.AsyncClient(timeout=30.0)

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
            self.inventory_health,
            name="inventory_health",
            description="Analyze inventory health metrics including stock value and Days of Cover",
            structured_output=True,
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
        item_code: str = Field(..., description="ERPNext item code (required)"),
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
        item_code: str = Field(..., description="ERPNext item code (required)"),
        to_warehouse: str = Field(..., description="Target warehouse for transfer"),
        from_warehouses: Optional[str] = Field(
            None, description="Source warehouses (comma-separated)"
        ),
        item_name: Optional[str] = Field(
            None, description="Item name (alternative to item_code)"
        ),
    ) -> ProposeTransferOutput:
        try:
            response = await self._calculate_transfers(
                item_code, item_name, to_warehouse, from_warehouses
            )

            return ProposeTransferOutput(**response)

        except Exception as e:
            self.logger.error(f"Error in propose_transfer: {e}", exc_info=True)
            raise

    async def inventory_health(
        self,
        warehouses: List[str] = Field(
            ..., min_items=1, description="List of warehouse names to analyze"
        ),
        item_groups: Optional[List[str]] = Field(
            None, description="Optional list of item groups to filter by"
        ),
        horizon_days: int = Field(
            default=30,
            ge=1,
            le=365,
            description="Horizon for Days of Cover calculation (1-365)",
        ),
    ) -> InventoryHealthOutput:
        try:
            warehouses_str = ",".join(warehouses) if warehouses else ""
            item_groups_str = ",".join(item_groups) if item_groups else None

            response = await self._analyze_health(
                warehouses_str, item_groups_str, horizon_days
            )

            return InventoryHealthOutput(**response)

        except Exception as e:
            self.logger.error(f"Error in inventory_health: {e}", exc_info=True)
            raise

    # ======================== HELPER METHODS ========================

    def _get_auth_headers(self) -> Dict[str, str]:
        if (
            not self.inventory_config.erpnext_api_key
            or not self.inventory_config.erpnext_api_secret
        ):
            raise ValueError("ERPNext API credentials not configured")

        return {
            "Authorization": f"token {self.inventory_config.erpnext_api_key}:{self.inventory_config.erpnext_api_secret}",
            "Content-Type": "application/json",
        }

    def _convert_dates_to_strings(self, obj) -> any:
        from datetime import date

        if isinstance(obj, dict):
            return {k: self._convert_dates_to_strings(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._convert_dates_to_strings(item) for item in obj]
        elif isinstance(obj, date):
            return obj.isoformat()
        else:
            return obj

    async def _fetch_stock_levels(
        self,
        item_code: Optional[str],
        item_name: Optional[str],
        warehouses: Optional[str],
        quantity_type: str,
    ) -> dict:
        if not self.http_client:
            raise RuntimeError("HTTP client not initialized")

        params = {
            "item_code": item_code,
            "item_name": item_name,
            "warehouses": warehouses,
            "quantity_type": quantity_type,
        }
        params = {k: v for k, v in params.items() if v is not None}

        url = f"{self.inventory_config.erpnext_url}/api/method/agent_stock_system.controller.inventory.retrieve_stock_levels"
        try:
            response = await self.http_client.get(
                url,
                headers=self._get_auth_headers(),
                params=params,
            )
            response.raise_for_status()
            result = response.json()

            data = result.get("message", result)

            if isinstance(data, dict) and data.get("success") is False:
                error_msg = data.get("error", "Unknown backend error")
                self.logger.error(
                    f"Backend returned error: {error_msg} | params: {params}"
                )
                raise ValueError(f"Backend error: {error_msg}")

            required_keys = {"items", "summary", "filters_applied"}
            if not all(key in data for key in required_keys):
                missing = required_keys - set(data.keys())
                self.logger.error(
                    f"Backend response missing keys: {missing} | full_response: {data}"
                )
                raise ValueError(f"Backend response missing required keys: {missing}")

            return data
        except Exception as e:
            self.logger.error(
                f"Error calling retrieve_stock_levels | url: {url} | params: {params} | error: {str(e)}",
                exc_info=True,
            )
            raise

    async def _fetch_stock_history(
        self,
        item_code: str,
        item_name: Optional[str],
        warehouse: Optional[str],
        days_back: int,
    ) -> dict:
        """Call backend retrieve_stock_history endpoint."""
        if not self.http_client:
            raise RuntimeError("HTTP client not initialized")

        params = {
            "item_code": item_code,
            "item_name": item_name,
            "warehouse": warehouse,
            "days_back": days_back,
        }
        params = {k: v for k, v in params.items() if v is not None}

        url = f"{self.inventory_config.erpnext_url}/api/method/agent_stock_system.controller.inventory.retrieve_stock_history"
        try:
            response = await self.http_client.get(
                url,
                headers=self._get_auth_headers(),
                params=params,
            )
            response.raise_for_status()
            result = response.json()

            data = result.get("message", result)

            if isinstance(data, dict) and data.get("success") is False:
                error_msg = data.get("error", "Unknown backend error")
                self.logger.error(
                    f"Backend returned error: {error_msg} | params: {params}"
                )
                raise ValueError(f"Backend error: {error_msg}")

            data = self._convert_dates_to_strings(data)

            required_keys = {"items", "summary", "filters_applied"}
            if not all(key in data for key in required_keys):
                missing = required_keys - set(data.keys())
                self.logger.error(
                    f"Backend response missing keys: {missing} | full_response: {data}"
                )
                raise ValueError(f"Backend response missing required keys: {missing}")

            return data
        except Exception as e:
            self.logger.error(
                f"Error calling retrieve_stock_history | url: {url} | params: {params} | error: {str(e)}",
                exc_info=True,
            )
            raise

    async def _calculate_transfers(
        self,
        item_code: str,
        item_name: Optional[str],
        to_warehouse: str,
        from_warehouses: Optional[str],
    ) -> dict:
        if not self.http_client:
            raise RuntimeError("HTTP client not initialized")

        params = {
            "item_code": item_code,
            "item_name": item_name,
            "to_warehouse": to_warehouse,
            "from_warehouses": from_warehouses,
        }
        params = {k: v for k, v in params.items() if v is not None}

        url = f"{self.inventory_config.erpnext_url}/api/method/agent_stock_system.controller.inventory.propose_stock_transfer"
        try:
            response = await self.http_client.get(
                url,
                headers=self._get_auth_headers(),
                params=params,
            )
            response.raise_for_status()
            result = response.json()

            data = result.get("message", result)

            if isinstance(data, dict) and data.get("success") is False:
                error_msg = data.get("error", "Unknown backend error")
                self.logger.error(
                    f"Backend returned error: {error_msg} | params: {params}"
                )
                raise ValueError(f"Backend error: {error_msg}")

            required_keys = {"items", "summary", "filters_applied"}
            if not all(key in data for key in required_keys):
                missing = required_keys - set(data.keys())
                self.logger.error(
                    f"Backend response missing keys: {missing} | full_response: {data}"
                )
                raise ValueError(f"Backend response missing required keys: {missing}")

            return data
        except Exception as e:
            self.logger.error(
                f"Error calling propose_stock_transfer | url: {url} | params: {params} | error: {str(e)}",
                exc_info=True,
            )
            raise

    async def _analyze_health(
        self,
        warehouses: str,
        item_groups: Optional[str],
        horizon_days: int,
    ) -> dict:
        if not self.http_client:
            raise RuntimeError("HTTP client not initialized")

        params = {
            "warehouses": warehouses,
            "item_groups": item_groups,
            "horizon_days": horizon_days,
        }
        params = {k: v for k, v in params.items() if v is not None}

        url = f"{self.inventory_config.erpnext_url}/api/method/agent_stock_system.controller.inventory.analyze_inventory_health"
        try:
            response = await self.http_client.get(
                url,
                headers=self._get_auth_headers(),
                params=params,
            )
            response.raise_for_status()
            result = response.json()

            data = result.get("message", result)

            if isinstance(data, dict) and data.get("success") is False:
                error_msg = data.get("error", "Unknown backend error")
                self.logger.error(
                    f"Backend returned error: {error_msg} | params: {params}"
                )
                raise ValueError(f"Backend error: {error_msg}")

            required_keys = {"items", "summary", "filters_applied"}
            if not all(key in data for key in required_keys):
                missing = required_keys - set(data.keys())
                self.logger.error(
                    f"Backend response missing keys: {missing} | full_response: {data}"
                )
                raise ValueError(f"Backend response missing required keys: {missing}")

            return data
        except Exception as e:
            self.logger.error(
                f"Error calling analyze_inventory_health | url: {url} | params: {params} | error: {str(e)}",
                exc_info=True,
            )
            raise

    async def cleanup(self) -> None:
        if self.http_client:
            await self.http_client.aclose()
