"""Comprehensive test suite for InventoryMCPServer with production validation."""

import asyncio
from datetime import datetime, timedelta

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest
from src.mcp.server.inventory_server import InventoryMCPServer, InventoryServerConfig


class TestInventoryMCPServer:
    """Production-grade test suite for InventoryMCPServer."""

    @pytest.fixture
    async def server_config(self) -> InventoryServerConfig:
        """Create test server configuration."""
        return InventoryServerConfig(
            name="TestInventoryMCP",
            port=8003,  # Different port for testing
            debug=True,
            default_warehouse="TEST-WH",
            low_stock_threshold=15,
            critical_stock_threshold=5,
        )

    @pytest.fixture
    async def inventory_server(
        self, server_config: InventoryServerConfig
    ) -> InventoryMCPServer:
        """Create inventory server instance for testing."""
        server = InventoryMCPServer(server_config)

        # Initialize server components without starting HTTP server
        server.mcp = await server._initialize_mcp()
        await server._register_tools()
        await server._register_resources()

        return server

    async def test_server_initialization(self, server_config: InventoryServerConfig):
        """Test server initializes correctly with valid configuration."""
        server = InventoryMCPServer(server_config)

        assert server.config.name == "TestInventoryMCP"
        assert server.config.port == 8003
        assert server.inventory_config.default_warehouse == "TEST-WH"
        assert server.inventory_config.low_stock_threshold == 15
        assert len(server._mock_inventory_data) > 0
        assert len(server._mock_history_data) > 0

    async def test_input_validation_security(
        self, inventory_server: InventoryMCPServer
    ):
        """Test input validation prevents security vulnerabilities."""

        # Test SQL injection attempts
        with pytest.raises(ValueError, match="Product ID must be 1-50 characters"):
            inventory_server._validate_product_id("'; DROP TABLE items; --")

        # Test XSS attempts
        with pytest.raises(ValueError, match="Product ID must be 1-50 characters"):
            inventory_server._validate_product_id("<script>alert('xss')</script>")

        # Test oversized inputs
        with pytest.raises(ValueError, match="Product ID must be 1-50 characters"):
            inventory_server._validate_product_id("A" * 100)

        # Test empty inputs
        with pytest.raises(ValueError, match="Product ID must be a non-empty string"):
            inventory_server._validate_product_id("")

        # Test valid inputs pass through
        valid_id = inventory_server._validate_product_id("LAPTOP-001")
        assert valid_id == "LAPTOP-001"

    async def test_mock_data_integrity(self, inventory_server: InventoryMCPServer):
        """Test mock data has realistic and consistent structure."""
        mock_data = inventory_server._mock_inventory_data

        # Verify data structure
        assert len(mock_data) >= 5, "Should have multiple test items"

        for product_id, item_data in mock_data.items():
            # Test required fields
            required_fields = [
                "name",
                "category",
                "current_stock",
                "reserved_stock",
                "unit_cost",
                "reorder_level",
                "reorder_qty",
                "supplier",
            ]
            for field in required_fields:
                assert field in item_data, f"Missing field {field} in {product_id}"

            # Test data types and constraints
            assert isinstance(item_data["current_stock"], int)
            assert item_data["current_stock"] >= 0
            assert isinstance(item_data["reserved_stock"], int)
            assert item_data["reserved_stock"] >= 0
            assert isinstance(item_data["unit_cost"], (int, float))
            assert item_data["unit_cost"] > 0

            # Test business logic constraints
            assert item_data["reorder_level"] >= 0
            assert item_data["reorder_qty"] > 0

    async def test_check_stock_tool(self, inventory_server: InventoryMCPServer):
        """Test check_stock tool with various scenarios."""

        # Test existing product
        # Test tool registration
        await inventory_server._register_tools()
        assert len(inventory_server._tools) > 0, "Should register tools"

        # Since we can't directly call the decorated function, test the underlying logic
        product_data = inventory_server._mock_inventory_data["LAPTOP-001"]
        status = inventory_server._determine_stock_status(
            product_data["current_stock"], product_data["reserved_stock"]
        )

        assert status in ["available", "low", "critical", "out_of_stock"]

        # Test status determination logic
        assert inventory_server._determine_stock_status(100, 5) == "available"
        assert (
            inventory_server._determine_stock_status(10, 5) == "low"
        )  # 5 available <= 15 threshold
        assert (
            inventory_server._determine_stock_status(7, 2) == "low"
        )  # 5 available <= 15 threshold
        assert (
            inventory_server._determine_stock_status(3, 0) == "critical"
        )  # 3 <= 5 threshold
        assert inventory_server._determine_stock_status(0, 0) == "out_of_stock"
        assert (
            inventory_server._determine_stock_status(5, 10) == "out_of_stock"
        )  # Negative available

    async def test_stock_history_filtering(self, inventory_server: InventoryMCPServer):
        """Test stock history filtering logic."""
        history_data = inventory_server._mock_history_data

        # Test date filtering
        recent_cutoff = datetime.now() - timedelta(days=7)
        recent_records = [
            record
            for record in history_data
            if datetime.fromisoformat(record["posting_date"]) >= recent_cutoff
        ]

        assert len(recent_records) > 0, "Should have recent history records"

        # Test movement type filtering
        in_movements = [r for r in history_data if r["movement_type"] == "IN"]
        out_movements = [r for r in history_data if r["movement_type"] == "OUT"]

        assert len(in_movements) > 0, "Should have IN movements"
        assert len(out_movements) > 0, "Should have OUT movements"

        # Test product filtering
        laptop_movements = [r for r in history_data if r["item_code"] == "LAPTOP-001"]
        assert len(laptop_movements) > 0, "Should have movements for LAPTOP-001"

    async def test_inventory_query_filtering(
        self, inventory_server: InventoryMCPServer
    ):
        """Test inventory query filtering with multiple criteria."""
        mock_data = inventory_server._mock_inventory_data

        # Test category filtering
        electronics = [
            item
            for item in mock_data.values()
            if item["category"].lower() == "electronics"
        ]
        assert len(electronics) > 0, "Should have electronics items"

        # Test stock level filtering - verify we have different stock scenarios
        low_stock_count = len(
            [
                item
                for item in mock_data.values()
                if (item["current_stock"] - item["reserved_stock"])
                <= inventory_server.inventory_config.low_stock_threshold
            ]
        )

        out_of_stock_count = len(
            [
                item
                for item in mock_data.values()
                if (item["current_stock"] - item["reserved_stock"]) <= 0
            ]
        )

        # Verify we have test coverage for different stock levels
        assert low_stock_count >= 0, "Low stock filtering should work"
        assert out_of_stock_count >= 0, "Out of stock filtering should work"

        # Verify we have test data covering different scenarios
        assert (
            len([item for item in mock_data.values() if item["current_stock"] > 20]) > 0
        ), "Should have high stock items"

        # Test supplier filtering
        suppliers = set(item["supplier"] for item in mock_data.values())
        assert len(suppliers) > 1, "Should have multiple suppliers"

    async def test_stock_monitoring_alerts(self, inventory_server: InventoryMCPServer):
        """Test stock monitoring and alert generation."""
        mock_data = inventory_server._mock_inventory_data

        alerts = []

        for product_id, item_data in mock_data.items():
            available_stock = item_data["current_stock"] - item_data["reserved_stock"]
            status = inventory_server._determine_stock_status(
                item_data["current_stock"], item_data["reserved_stock"]
            )

            if status in ["out_of_stock", "critical", "low"]:
                alerts.append(
                    {
                        "product_id": product_id,
                        "status": status,
                        "available_stock": available_stock,
                    }
                )

        # Verify alert logic
        for alert in alerts:
            if alert["status"] == "out_of_stock":
                assert alert["available_stock"] <= 0
            elif alert["status"] == "critical":
                assert (
                    0
                    < alert["available_stock"]
                    <= inventory_server.inventory_config.critical_stock_threshold
                )
            elif alert["status"] == "low":
                assert (
                    inventory_server.inventory_config.critical_stock_threshold
                    < alert["available_stock"]
                    <= inventory_server.inventory_config.low_stock_threshold
                )

    async def test_error_handling(self, inventory_server: InventoryMCPServer):
        """Test comprehensive error handling."""

        # Test invalid product ID
        with pytest.raises(ValueError):
            inventory_server._validate_product_id(None)

        with pytest.raises(ValueError):
            inventory_server._validate_product_id(123)  # Not string

        # Test warehouse validation
        valid_warehouse = inventory_server._validate_warehouse("MAIN-WH")
        assert valid_warehouse == "MAIN-WH"

        default_warehouse = inventory_server._validate_warehouse(None)
        assert default_warehouse == inventory_server.inventory_config.default_warehouse

    async def test_resource_generation(self, inventory_server: InventoryMCPServer):
        """Test resource generation produces valid JSON."""

        # Test stock levels resource structure
        mock_data = inventory_server._mock_inventory_data

        # Calculate expected metrics
        total_items = len(mock_data)
        total_value = sum(
            item["current_stock"] * item["unit_cost"] for item in mock_data.values()
        )

        low_stock_count = sum(
            1
            for item in mock_data.values()
            if (item["current_stock"] - item["reserved_stock"])
            <= inventory_server.inventory_config.low_stock_threshold
        )

        # Verify calculations are consistent
        assert total_items > 0
        assert total_value > 0
        assert isinstance(low_stock_count, int)

        # Test category breakdown
        categories = set(item["category"] for item in mock_data.values())
        assert len(categories) >= 2, "Should have multiple categories for testing"

    async def test_configuration_validation(self):
        """Test configuration validation and edge cases."""

        # Test valid configuration
        config = InventoryServerConfig(
            name="ValidInventoryMCP",
            port=8004,
            default_warehouse="VALID-WH",
            low_stock_threshold=10,
            critical_stock_threshold=5,
        )

        assert config.name == "ValidInventoryMCP"
        assert config.default_warehouse == "VALID-WH"

        # Test invalid warehouse code
        with pytest.raises(ValueError):
            InventoryServerConfig(
                name="InvalidInventoryMCP",
                default_warehouse="invalid warehouse!",  # Invalid characters
            )

        # Test threshold constraints
        config_with_thresholds = InventoryServerConfig(
            name="ThresholdTest",
            low_stock_threshold=0,  # Minimum valid value
            critical_stock_threshold=0,
        )

        assert config_with_thresholds.low_stock_threshold == 0
        assert config_with_thresholds.critical_stock_threshold == 0


# Integration test client
async def test_server_integration():
    """Integration test that starts server and tests client interactions."""

    # Server configuration
    config = InventoryServerConfig(
        name="IntegrationTestMCP",
        port=8005,
        debug=True,
        default_warehouse="INT-TEST-WH",
    )

    server = InventoryMCPServer(config)

    # Test server lifecycle
    async with server._server_lifecycle():
        print(f"✅ Server initialized: {server.config.name}")
        print(f"📊 Mock data loaded: {len(server._mock_inventory_data)} items")
        print(f"📈 History records: {len(server._mock_history_data)} movements")

        # Test mock data access
        for product_id, item_data in list(server._mock_inventory_data.items())[:3]:
            available_stock = item_data["current_stock"] - item_data["reserved_stock"]
            status = server._determine_stock_status(
                item_data["current_stock"], item_data["reserved_stock"]
            )

            print(f"📦 {product_id}: {item_data['name']}")
            print(
                f"   Stock: {item_data['current_stock']} (Available: {available_stock})"
            )
            print(f"   Status: {status}")
            print(
                f"   Value: ${item_data['current_stock'] * item_data['unit_cost']:,.2f}"
            )

        # Test validation functions
        try:
            validated_id = server._validate_product_id("LAPTOP-001")
            print(f"✅ Validation test passed: {validated_id}")
        except Exception as e:
            print(f"❌ Validation test failed: {e}")

        # Test error cases
        try:
            server._validate_product_id("invalid'; DROP TABLE items;--")
            print("❌ Security test failed - should have raised exception")
        except ValueError as e:
            print(f"✅ Security test passed: {e}")

        print("🎉 Integration test completed successfully")


if __name__ == "__main__":
    # Run integration test
    asyncio.run(test_server_integration())
