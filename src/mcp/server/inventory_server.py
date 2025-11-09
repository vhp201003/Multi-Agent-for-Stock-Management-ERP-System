import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from pydantic import Field, validator
from src.typing.mcp import CheckStockOutput, StockLevelsOutput

from .base_server import BaseMCPServer, ServerConfig

logger = logging.getLogger(__name__)


class InventoryServerConfig(ServerConfig):
    default_warehouse: str = Field(
        default="MAIN-WH", description="Default warehouse code"
    )
    low_stock_threshold: int = Field(
        default=10, ge=0, description="Low stock alert threshold"
    )
    critical_stock_threshold: int = Field(
        default=5, ge=0, description="Critical stock threshold"
    )

    @validator("name", pre=True, always=True)
    def set_default_name(cls, v):
        return v or "InventoryMCP"

    @validator("default_warehouse")
    def validate_warehouse_code(cls, v):
        if not re.match(r"^[A-Z0-9_-]+$", v):
            raise ValueError(
                "Warehouse code must be uppercase alphanumeric with underscores/hyphens"
            )
        return v


class InventoryMCPServer(BaseMCPServer):
    """Production-grade MCP Server for InventoryAgent.

    Capabilities:
    - Stock level checking with validation
    - Stock history retrieval with time ranges
    - Inventory data querying with filters
    - Stock availability monitoring with alerts

    Example:
        config = InventoryServerConfig(port=8002, default_warehouse="MAIN-WH")
        server = InventoryMCPServer(config)
        server.run()
    """

    def __init__(self, config: InventoryServerConfig):
        """Initialize with validated configuration."""
        super().__init__(config)
        self.inventory_config = config

        # Mock data for testing - replace with ERPNext integration
        self._mock_inventory_data = self._generate_mock_data()
        self._mock_history_data = self._generate_mock_history()

    def _generate_mock_data(self) -> Dict[str, Dict[str, Any]]:
        """Generate realistic mock inventory data for testing."""
        return {
            "LAPTOP-001": {
                "name": "Dell Latitude 5520",
                "category": "Electronics",
                "current_stock": 45,
                "reserved_stock": 5,
                "unit_cost": 899.99,
                "reorder_level": 10,
                "reorder_qty": 20,
                "supplier": "Dell Inc",
                "last_updated": datetime.now().isoformat(),
            },
            "MOUSE-001": {
                "name": "Logitech MX Master 3",
                "category": "Accessories",
                "current_stock": 8,
                "reserved_stock": 2,
                "unit_cost": 79.99,
                "reorder_level": 15,
                "reorder_qty": 25,
                "supplier": "Logitech",
                "last_updated": datetime.now().isoformat(),
            },
            "KEYBOARD-001": {
                "name": "Mechanical Keyboard RGB",
                "category": "Accessories",
                "current_stock": 0,
                "reserved_stock": 0,
                "unit_cost": 129.99,
                "reorder_level": 5,
                "reorder_qty": 15,
                "supplier": "Razer",
                "last_updated": datetime.now().isoformat(),
            },
            "MONITOR-001": {
                "name": 'Samsung 27" 4K Monitor',
                "category": "Electronics",
                "current_stock": 25,
                "reserved_stock": 3,
                "unit_cost": 349.99,
                "reorder_level": 8,
                "reorder_qty": 12,
                "supplier": "Samsung",
                "last_updated": datetime.now().isoformat(),
            },
            "CABLE-001": {
                "name": "USB-C to HDMI Cable",
                "category": "Cables",
                "current_stock": 150,
                "reserved_stock": 10,
                "unit_cost": 19.99,
                "reorder_level": 50,
                "reorder_qty": 100,
                "supplier": "Anker",
                "last_updated": datetime.now().isoformat(),
            },
        }

    def _generate_mock_history(self) -> List[Dict[str, Any]]:
        """Generate mock stock movement history for testing."""
        base_date = datetime.now() - timedelta(days=30)
        history = []

        items = list(self._mock_inventory_data.keys())
        movement_types = ["IN", "OUT", "TRANSFER", "ADJUSTMENT"]

        for i in range(50):  # Generate 50 historical movements
            item = items[i % len(items)]
            movement_date = base_date + timedelta(days=i % 30, hours=i % 24)

            history.append(
                {
                    "id": f"MOV-{1000 + i}",
                    "item_code": item,
                    "item_name": self._mock_inventory_data[item]["name"],
                    "movement_type": movement_types[i % len(movement_types)],
                    "quantity": (i % 10) + 1 if i % 2 == 0 else -((i % 8) + 1),
                    "warehouse": self.inventory_config.default_warehouse,
                    "reference": f"REF-{2000 + i}",
                    "posting_date": movement_date.isoformat(),
                    "voucher_type": "Stock Entry",
                    "batch_no": f"BATCH-{i % 5 + 1}" if i % 3 == 0 else None,
                    "valuation_rate": self._mock_inventory_data[item]["unit_cost"],
                    "stock_value_difference": (i % 10 + 1)
                    * self._mock_inventory_data[item]["unit_cost"],
                }
            )

        return sorted(history, key=lambda x: x["posting_date"], reverse=True)

    def _validate_product_id(self, product_id: str) -> str:
        """Validate and sanitize product ID with enhanced security."""
        if not product_id or not isinstance(product_id, str):
            raise ValueError("Product ID must be a non-empty string")

        # Check for SQL injection patterns
        dangerous_patterns = [
            "drop",
            "delete",
            "truncate",
            "insert",
            "update",
            "alter",
            "select",
            "union",
            "exec",
            "execute",
            ";",
            "--",
            "/*",
            "*/",
            "script",
            "alert",
            "javascript:",
            "vbscript:",
            "onload",
            "onerror",
            "onclick",
            "<",
            ">",
            "&",
            '"',
            "'",
        ]

        lower_input = product_id.lower()
        for pattern in dangerous_patterns:
            if pattern in lower_input:
                raise ValueError(
                    "Invalid characters or patterns detected in product ID"
                )

        # Only allow alphanumeric, dots, and hyphens
        sanitized = re.sub(r"[^\w\-.]", "", product_id.strip().upper())

        if len(sanitized) == 0 or len(sanitized) > 50:
            raise ValueError("Product ID must be 1-50 characters")

        # Ensure it starts with alphanumeric
        if not sanitized[0].isalnum():
            raise ValueError("Product ID must start with alphanumeric character")

        return sanitized

    def _validate_warehouse(self, warehouse: Optional[str]) -> str:
        """Validate warehouse identifier."""
        if not warehouse:
            return self.inventory_config.default_warehouse

        sanitized = re.sub(r"[^\w\-]", "", warehouse.strip().upper())

        if len(sanitized) == 0 or len(sanitized) > 30:
            raise ValueError("Warehouse code must be 1-30 characters")

        return sanitized

    def _determine_stock_status(
        self, current_stock: int, reserved_stock: int = 0
    ) -> str:
        """Determine stock status based on thresholds."""
        available_stock = current_stock - reserved_stock

        if available_stock <= 0:
            return "out_of_stock"
        elif available_stock <= self.inventory_config.critical_stock_threshold:
            return "critical"
        elif available_stock <= self.inventory_config.low_stock_threshold:
            return "low"
        else:
            return "available"

    def setup(self) -> None:
        """Setup inventory tools and resources leveraging FastMCP."""
        # Register all tools - FastMCP extracts parameters from signatures
        self.add_tool(self.check_stock, description="Check product stock levels")
        self.add_tool(
            self.retrieve_stock_history,
            description="Retrieve stock movement history with filters",
        )
        self.add_tool(
            self.query_inventory_data,
            description="Query inventory with multiple filter criteria",
        )
        self.add_tool(
            self.monitor_stock_availability,
            description="Monitor stock levels and generate availability alerts",
        )

        # Register all resources - FastMCP handles URI templates
        self.add_resource("stock://levels", self.get_stock_levels)
        self.add_resource("stock://alerts", self.get_stock_alerts)

    # ============= Tool Handlers =============

    async def check_stock(
        self,
        product_id: str = Field(..., description="Product identifier"),
        warehouse: Optional[str] = Field(default=None, description="Warehouse code"),
    ) -> CheckStockOutput:
        """Enhanced stock check with complete product information."""
        try:
            validated_product_id = self._validate_product_id(product_id)
            validated_warehouse = self._validate_warehouse(warehouse)

            if validated_product_id not in self._mock_inventory_data:
                raise ValueError(f"Product {validated_product_id} not found")

            item_data = self._mock_inventory_data[validated_product_id]
            status = self._determine_stock_status(
                item_data["current_stock"], item_data["reserved_stock"]
            )

            return CheckStockOutput(
                product_id=validated_product_id,
                stock_level=item_data["current_stock"],
                warehouse=validated_warehouse,
                status=status,
                reserved_qty=item_data["reserved_stock"],
                available_qty=item_data["current_stock"] - item_data["reserved_stock"],
                timestamp=datetime.now().isoformat(),
                product_name=item_data["name"],
                supplier=item_data["supplier"],
                category=item_data["category"],
                unit_cost=item_data["unit_cost"],
                reorder_level=item_data["reorder_level"],
                metadata={
                    "product_name": item_data["name"],
                    "supplier": item_data["supplier"],
                    "category": item_data["category"],
                    "reorder_level": item_data["reorder_level"],
                    "reorder_qty": item_data["reorder_qty"],
                    "unit_cost": item_data["unit_cost"],
                    "last_updated": item_data["last_updated"],
                },
            )

        except ValueError as e:
            self.logger.warning(f"Invalid stock check request: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Stock check failed: {e}")
            raise RuntimeError(f"Stock check operation failed: {str(e)}")

    async def retrieve_stock_history(
        self,
        product_id: Optional[str] = Field(
            default=None, description="Product ID filter (optional)"
        ),
        days_back: int = Field(
            default=30, ge=1, le=365, description="Number of days to look back"
        ),
        movement_type: Optional[str] = Field(
            default=None,
            description="Movement type filter: IN, OUT, TRANSFER, ADJUSTMENT",
        ),
    ) -> Dict[str, Any]:
        """Retrieve filtered stock movement history with validation."""
        try:
            self.logger.info(
                f"History query: {product_id}, {days_back} days, type: {movement_type}"
            )

            # Input validation
            validated_product_id = None
            if product_id:
                validated_product_id = self._validate_product_id(product_id)

            if movement_type and movement_type not in [
                "IN",
                "OUT",
                "TRANSFER",
                "ADJUSTMENT",
            ]:
                raise ValueError(
                    "Invalid movement type. Use: IN, OUT, TRANSFER, ADJUSTMENT"
                )

            # Filter mock history data
            cutoff_date = datetime.now() - timedelta(days=days_back)
            filtered_history = []

            for record in self._mock_history_data:
                record_date = datetime.fromisoformat(record["posting_date"])

                # Date filter
                if record_date < cutoff_date:
                    continue

                # Product filter
                if validated_product_id and record["item_code"] != validated_product_id:
                    continue

                # Movement type filter
                if movement_type and record["movement_type"] != movement_type:
                    continue

                filtered_history.append(record)

            # Calculate summary statistics
            total_movements = len(filtered_history)
            total_in = sum(1 for r in filtered_history if r["movement_type"] == "IN")
            total_out = sum(1 for r in filtered_history if r["movement_type"] == "OUT")
            total_value = sum(
                abs(r["stock_value_difference"]) for r in filtered_history
            )

            return {
                "movements": filtered_history[:100],  # Limit to 100 records
                "summary": {
                    "total_movements": total_movements,
                    "inbound_movements": total_in,
                    "outbound_movements": total_out,
                    "total_value": round(total_value, 2),
                    "date_range": {
                        "from": cutoff_date.isoformat(),
                        "to": datetime.now().isoformat(),
                    },
                },
                "filters_applied": {
                    "product_id": validated_product_id,
                    "days_back": days_back,
                    "movement_type": movement_type,
                },
            }

        except ValueError as e:
            self.logger.warning(f"Invalid history request: {e}")
            raise
        except Exception as e:
            self.logger.error(f"History retrieval failed: {e}")
            raise RuntimeError(f"History retrieval failed: {str(e)}")

    async def query_inventory_data(
        self,
        category: Optional[str] = Field(
            default=None, description="Product category filter"
        ),
        min_stock: Optional[int] = Field(
            default=None, ge=0, description="Minimum stock level filter"
        ),
        max_stock: Optional[int] = Field(
            default=None, ge=0, description="Maximum stock level filter"
        ),
        supplier: Optional[str] = Field(
            default=None, description="Supplier name filter"
        ),
        limit: int = Field(
            default=50, ge=1, le=200, description="Maximum results to return"
        ),
    ) -> Dict[str, Any]:
        """Query inventory with multiple filter criteria."""
        try:
            self.logger.info(
                f"Inventory query: category={category}, stock range=[{min_stock}, {max_stock}]"
            )

            # Validate stock range
            if (
                min_stock is not None
                and max_stock is not None
                and min_stock > max_stock
            ):
                raise ValueError("min_stock cannot be greater than max_stock")

            filtered_items = []

            for product_id, item_data in self._mock_inventory_data.items():
                # Category filter
                if category and item_data["category"].lower() != category.lower():
                    continue

                # Stock level filters
                current_stock = item_data["current_stock"]
                if min_stock is not None and current_stock < min_stock:
                    continue
                if max_stock is not None and current_stock > max_stock:
                    continue

                # Supplier filter
                if supplier and supplier.lower() not in item_data["supplier"].lower():
                    continue

                # Add to results with calculated fields
                available_stock = current_stock - item_data["reserved_stock"]
                status = self._determine_stock_status(
                    current_stock, item_data["reserved_stock"]
                )

                filtered_items.append(
                    {
                        "product_id": product_id,
                        "name": item_data["name"],
                        "category": item_data["category"],
                        "current_stock": current_stock,
                        "available_stock": available_stock,
                        "reserved_stock": item_data["reserved_stock"],
                        "status": status,
                        "unit_cost": item_data["unit_cost"],
                        "stock_value": current_stock * item_data["unit_cost"],
                        "reorder_level": item_data["reorder_level"],
                        "supplier": item_data["supplier"],
                        "needs_reorder": available_stock <= item_data["reorder_level"],
                    }
                )

            # Sort by stock level (ascending) and limit results
            filtered_items.sort(key=lambda x: x["current_stock"])
            limited_items = filtered_items[:limit]

            # Calculate summary statistics
            total_items = len(limited_items)
            total_value = sum(item["stock_value"] for item in limited_items)
            low_stock_count = sum(
                1 for item in limited_items if item["status"] in ["low", "critical"]
            )
            out_of_stock_count = sum(
                1 for item in limited_items if item["status"] == "out_of_stock"
            )
            reorder_needed = sum(1 for item in limited_items if item["needs_reorder"])

            return {
                "items": limited_items,
                "summary": {
                    "total_items": total_items,
                    "total_value": round(total_value, 2),
                    "low_stock_items": low_stock_count,
                    "out_of_stock_items": out_of_stock_count,
                    "reorder_needed": reorder_needed,
                },
                "filters_applied": {
                    "category": category,
                    "min_stock": min_stock,
                    "max_stock": max_stock,
                    "supplier": supplier,
                    "limit": limit,
                },
            }

        except ValueError as e:
            self.logger.warning(f"Invalid query parameters: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Inventory query failed: {e}")
            raise RuntimeError(f"Inventory query failed: {str(e)}")

    async def monitor_stock_availability(
        self,
        alert_level: str = Field(
            default="all",
            description="Alert level filter: all, critical, low, reorder",
        ),
        warehouse: Optional[str] = Field(
            default=None, description="Warehouse filter (optional)"
        ),
    ) -> Dict[str, Any]:
        """Monitor stock levels and generate availability alerts."""
        try:
            validated_warehouse = self._validate_warehouse(warehouse)

            if alert_level not in ["all", "critical", "low", "reorder"]:
                raise ValueError("Alert level must be: all, critical, low, reorder")

            self.logger.info(
                f"Stock monitoring: {alert_level} alerts for {validated_warehouse}"
            )

            alerts = []

            for product_id, item_data in self._mock_inventory_data.items():
                current_stock = item_data["current_stock"]
                available_stock = current_stock - item_data["reserved_stock"]
                status = self._determine_stock_status(
                    current_stock, item_data["reserved_stock"]
                )
                needs_reorder = available_stock <= item_data["reorder_level"]

                # Determine alert type
                alert_types = []
                if status == "out_of_stock":
                    alert_types.append("OUT_OF_STOCK")
                elif status == "critical":
                    alert_types.append("CRITICAL_STOCK")
                elif status == "low":
                    alert_types.append("LOW_STOCK")

                if needs_reorder:
                    alert_types.append("REORDER_NEEDED")

                # Filter by alert level
                if alert_level != "all":
                    if (
                        alert_level == "critical"
                        and "CRITICAL_STOCK" not in alert_types
                        and "OUT_OF_STOCK" not in alert_types
                    ):
                        continue
                    elif alert_level == "low" and "LOW_STOCK" not in alert_types:
                        continue
                    elif (
                        alert_level == "reorder" and "REORDER_NEEDED" not in alert_types
                    ):
                        continue

                if alert_types:  # Only include items with alerts
                    days_out_of_stock = 0
                    if status == "out_of_stock":
                        # Mock calculation - in reality, query stock ledger
                        days_out_of_stock = 3

                    alerts.append(
                        {
                            "product_id": product_id,
                            "product_name": item_data["name"],
                            "category": item_data["category"],
                            "current_stock": current_stock,
                            "available_stock": available_stock,
                            "reserved_stock": item_data["reserved_stock"],
                            "status": status,
                            "alert_types": alert_types,
                            "reorder_level": item_data["reorder_level"],
                            "reorder_qty": item_data["reorder_qty"],
                            "supplier": item_data["supplier"],
                            "unit_cost": item_data["unit_cost"],
                            "days_out_of_stock": days_out_of_stock,
                            "estimated_stockout_date": None
                            if available_stock > 0
                            else datetime.now().isoformat(),
                            "warehouse": validated_warehouse,
                        }
                    )

            # Sort by priority: out of stock first, then critical, then low
            priority_order = {
                "out_of_stock": 0,
                "critical": 1,
                "low": 2,
                "available": 3,
            }
            alerts.sort(
                key=lambda x: (
                    priority_order.get(x["status"], 99),
                    x["available_stock"],
                )
            )

            # Calculate summary statistics
            summary = {
                "total_alerts": len(alerts),
                "out_of_stock": len(
                    [a for a in alerts if "OUT_OF_STOCK" in a["alert_types"]]
                ),
                "critical_stock": len(
                    [a for a in alerts if "CRITICAL_STOCK" in a["alert_types"]]
                ),
                "low_stock": len(
                    [a for a in alerts if "LOW_STOCK" in a["alert_types"]]
                ),
                "reorder_needed": len(
                    [a for a in alerts if "REORDER_NEEDED" in a["alert_types"]]
                ),
                "total_value_at_risk": round(
                    sum(a["current_stock"] * a["unit_cost"] for a in alerts), 2
                ),
                "checked_at": datetime.now().isoformat(),
                "warehouse": validated_warehouse,
            }

            return {
                "alerts": alerts,
                "summary": summary,
                "filters_applied": {
                    "alert_level": alert_level,
                    "warehouse": validated_warehouse,
                },
            }

        except ValueError as e:
            self.logger.warning(f"Invalid monitoring parameters: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Stock monitoring failed: {e}")
            raise RuntimeError(f"Stock monitoring failed: {str(e)}")

    # ============= Resource Handlers =============

    async def get_stock_levels(self) -> str:
        """Return comprehensive stock levels dashboard."""
        try:
            self.logger.info("Generating stock levels dashboard")

            # Calculate comprehensive metrics
            total_items = len(self._mock_inventory_data)
            total_value = sum(
                item["current_stock"] * item["unit_cost"]
                for item in self._mock_inventory_data.values()
            )

            low_stock_items = sum(
                1
                for item in self._mock_inventory_data.values()
                if (item["current_stock"] - item["reserved_stock"])
                <= self.inventory_config.low_stock_threshold
            )

            out_of_stock_items = sum(
                1
                for item in self._mock_inventory_data.values()
                if (item["current_stock"] - item["reserved_stock"]) <= 0
            )

            # Category breakdown
            category_stats = {}
            for item in self._mock_inventory_data.values():
                category = item["category"]
                if category not in category_stats:
                    category_stats[category] = {"count": 0, "value": 0}
                category_stats[category]["count"] += 1
                category_stats[category]["value"] += (
                    item["current_stock"] * item["unit_cost"]
                )

            output = StockLevelsOutput(
                levels={
                    item_id: item_data["current_stock"]
                    for item_id, item_data in self._mock_inventory_data.items()
                },
                timestamp=datetime.now().isoformat(),
                warehouse=self.inventory_config.default_warehouse,
                metadata={
                    "total_items": total_items,
                    "total_value": round(total_value, 2),
                    "low_stock_items": low_stock_items,
                    "out_of_stock_items": out_of_stock_items,
                    "categories": category_stats,
                    "thresholds": {
                        "low_stock": self.inventory_config.low_stock_threshold,
                        "critical_stock": self.inventory_config.critical_stock_threshold,
                    },
                },
            )

            return output.model_dump_json()

        except Exception as e:
            self.logger.error(f"Dashboard generation failed: {e}")
            raise RuntimeError(f"Unable to generate stock levels dashboard: {str(e)}")

    async def get_stock_alerts(self) -> str:
        """Return critical stock alerts requiring immediate attention."""
        try:
            self.logger.info("Generating stock alerts feed")

            critical_alerts = []

            for product_id, item_data in self._mock_inventory_data.items():
                available_stock = (
                    item_data["current_stock"] - item_data["reserved_stock"]
                )

                if available_stock <= 0:
                    critical_alerts.append(
                        {
                            "type": "OUT_OF_STOCK",
                            "severity": "critical",
                            "product_id": product_id,
                            "product_name": item_data["name"],
                            "message": f"{item_data['name']} is out of stock",
                            "available_stock": available_stock,
                            "action_required": "Immediate restocking required",
                        }
                    )
                elif available_stock <= self.inventory_config.critical_stock_threshold:
                    critical_alerts.append(
                        {
                            "type": "CRITICAL_STOCK",
                            "severity": "high",
                            "product_id": product_id,
                            "product_name": item_data["name"],
                            "message": f"{item_data['name']} has critically low stock ({available_stock} units)",
                            "available_stock": available_stock,
                            "action_required": "Urgent reorder recommended",
                        }
                    )
                elif available_stock <= item_data["reorder_level"]:
                    critical_alerts.append(
                        {
                            "type": "REORDER_NEEDED",
                            "severity": "medium",
                            "product_id": product_id,
                            "product_name": item_data["name"],
                            "message": f"{item_data['name']} below reorder level ({available_stock}/{item_data['reorder_level']})",
                            "available_stock": available_stock,
                            "action_required": f"Reorder {item_data['reorder_qty']} units",
                        }
                    )

            # Sort by severity
            severity_order = {"critical": 0, "high": 1, "medium": 2}
            critical_alerts.sort(key=lambda x: severity_order.get(x["severity"], 99))

            return json.dumps(
                {
                    "alerts": critical_alerts,
                    "summary": {
                        "total_alerts": len(critical_alerts),
                        "critical": len(
                            [a for a in critical_alerts if a["severity"] == "critical"]
                        ),
                        "high": len(
                            [a for a in critical_alerts if a["severity"] == "high"]
                        ),
                        "medium": len(
                            [a for a in critical_alerts if a["severity"] == "medium"]
                        ),
                        "generated_at": datetime.now().isoformat(),
                    },
                }
            )

        except Exception as e:
            self.logger.error(f"Alerts generation failed: {e}")
            raise RuntimeError(f"Unable to generate stock alerts: {str(e)}")

    async def cleanup(self) -> None:
        """Cleanup inventory-specific resources."""
        self.logger.info("Inventory server cleanup completed")
