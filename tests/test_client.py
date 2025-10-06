"""Test client for manual testing of InventoryMCPServer functionality."""

import asyncio
from datetime import datetime

from src.mcp.server.inventory_server import InventoryMCPServer, InventoryServerConfig


class InventoryTestClient:
    """Test client for simulating InventoryMCPServer interactions."""

    def __init__(self):
        """Initialize test client."""
        pass

    async def simulate_stock_operations(self, server: InventoryMCPServer):
        """Simulate various stock operations for testing."""

        print("\n🧪 Simulating Stock Operations")
        print("=" * 50)

        # Test 1: Check stock for existing items
        print("\n📦 Test 1: Stock Level Checks")
        test_items = [
            "LAPTOP-001",
            "MOUSE-001",
            "KEYBOARD-001",
            "MONITOR-001",
            "CABLE-001",
        ]

        for product_id in test_items:
            if product_id in server._mock_inventory_data:
                item_data = server._mock_inventory_data[product_id]
                available_stock = (
                    item_data["current_stock"] - item_data["reserved_stock"]
                )
                status = server._determine_stock_status(
                    item_data["current_stock"], item_data["reserved_stock"]
                )

                print(f"  📦 {product_id}: {item_data['name']}")
                print(
                    f"     Current: {item_data['current_stock']} | Reserved: {item_data['reserved_stock']} | Available: {available_stock}"
                )
                print(
                    f"     Status: {status} | Reorder Level: {item_data['reorder_level']}"
                )
                print(
                    f"     Unit Cost: ${item_data['unit_cost']} | Total Value: ${item_data['current_stock'] * item_data['unit_cost']:,.2f}"
                )

        # Test 2: Stock History Analysis
        print("\n📊 Test 2: Stock History Analysis")
        history_data = server._mock_history_data

        # Movement type summary
        movement_summary = {}
        for record in history_data:
            movement_type = record["movement_type"]
            movement_summary[movement_type] = movement_summary.get(movement_type, 0) + 1

        print(f"  📈 Total History Records: {len(history_data)}")
        for movement_type, count in movement_summary.items():
            print(f"     {movement_type}: {count} movements")

        # Recent movements (last 7 days)
        recent_cutoff = datetime.now().timestamp() - (7 * 24 * 3600)
        recent_movements = [
            r
            for r in history_data
            if datetime.fromisoformat(r["posting_date"]).timestamp() > recent_cutoff
        ]
        print(f"  📅 Recent Movements (7 days): {len(recent_movements)}")

        # Test 3: Inventory Analytics
        print("\n🔍 Test 3: Inventory Analytics")
        mock_data = server._mock_inventory_data

        # Category analysis
        category_stats = {}
        total_value = 0

        for item_data in mock_data.values():
            category = item_data["category"]
            if category not in category_stats:
                category_stats[category] = {
                    "count": 0,
                    "total_stock": 0,
                    "total_value": 0,
                }

            category_stats[category]["count"] += 1
            category_stats[category]["total_stock"] += item_data["current_stock"]
            item_value = item_data["current_stock"] * item_data["unit_cost"]
            category_stats[category]["total_value"] += item_value
            total_value += item_value

        print(f"  📊 Total Inventory Value: ${total_value:,.2f}")
        print("  📊 Category Breakdown:")

        for category, stats in category_stats.items():
            print(
                f"     {category}: {stats['count']} items, {stats['total_stock']} units, ${stats['total_value']:,.2f}"
            )

        # Test 4: Alert Generation
        print("\n⚠️ Test 4: Stock Alerts")

        alerts = []
        for product_id, item_data in mock_data.items():
            available_stock = item_data["current_stock"] - item_data["reserved_stock"]
            status = server._determine_stock_status(
                item_data["current_stock"], item_data["reserved_stock"]
            )

            if status in ["out_of_stock", "critical", "low"]:
                alerts.append(
                    {
                        "product_id": product_id,
                        "name": item_data["name"],
                        "status": status,
                        "available_stock": available_stock,
                        "reorder_level": item_data["reorder_level"],
                    }
                )

        if alerts:
            print(f"  🚨 Total Alerts: {len(alerts)}")
            for alert in alerts:
                print(
                    f"     {alert['status'].upper()}: {alert['product_id']} - {alert['name']}"
                )
                print(
                    f"       Available: {alert['available_stock']}, Reorder Level: {alert['reorder_level']}"
                )
        else:
            print("  ✅ No stock alerts - all items adequately stocked")

        # Test 5: Input Validation
        print("\n🔒 Test 5: Input Validation & Security")

        test_cases = [
            ("LAPTOP-001", True, "Valid product ID"),
            ("laptop-001", True, "Lowercase converted to uppercase"),
            ("ITEM.WITH.DOTS", True, "Product ID with dots"),
            ("ITEM-WITH-DASHES", True, "Product ID with dashes"),
            ("'; DROP TABLE items; --", False, "SQL injection attempt"),
            ("<script>alert('xss')</script>", False, "XSS attempt"),
            ("", False, "Empty string"),
            ("A" * 100, False, "Oversized input"),
            ("ITEM WITH SPACES", True, "Spaces should be removed"),
        ]

        for test_input, should_pass, description in test_cases:
            try:
                result = server._validate_product_id(test_input)
                if should_pass:
                    print(f"  ✅ {description}: '{test_input}' → '{result}'")
                else:
                    print(f"  ❌ {description}: Should have failed but got '{result}'")
            except ValueError as e:
                if not should_pass:
                    print(f"  ✅ {description}: Correctly rejected - {e}")
                else:
                    print(f"  ❌ {description}: Unexpected rejection - {e}")

        print("\n🎉 Stock Operations Simulation Completed!")


async def run_comprehensive_test():
    """Run comprehensive test suite with server and client."""

    print("🚀 Starting Comprehensive Inventory Server Test")
    print("=" * 60)

    # Server configuration
    config = InventoryServerConfig(
        name="ComprehensiveTestMCP",
        port=8006,
        debug=True,
        default_warehouse="COMP-TEST-WH",
        low_stock_threshold=12,
        critical_stock_threshold=3,
    )

    # Initialize server
    server = InventoryMCPServer(config)
    client = InventoryTestClient()

    try:
        # Test server initialization
        print("\n📋 Server Configuration:")
        print(f"   Name: {config.name}")
        print(f"   Port: {config.port}")
        print(f"   Warehouse: {config.default_warehouse}")
        print(f"   Low Stock Threshold: {config.low_stock_threshold}")
        print(f"   Critical Threshold: {config.critical_stock_threshold}")

        # Initialize server components
        async with server._server_lifecycle():
            print("\n✅ Server initialized successfully")
            print(f"📦 Mock inventory items: {len(server._mock_inventory_data)}")
            print(f"📊 Mock history records: {len(server._mock_history_data)}")

            # Run simulation tests
            await client.simulate_stock_operations(server)

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        raise

    print("\n✅ All tests completed successfully!")


async def run_quick_test():
    """Quick test for immediate validation."""

    print("⚡ Quick Inventory Server Test")
    print("=" * 40)

    config = InventoryServerConfig(name="QuickTestMCP", port=8007, debug=True)

    server = InventoryMCPServer(config)

    print(f"✅ Server created: {server.config.name}")
    print(f"📦 Mock data loaded: {len(server._mock_inventory_data)} items")

    # Test a few key operations
    laptop_data = server._mock_inventory_data.get("LAPTOP-001")
    if laptop_data:
        status = server._determine_stock_status(
            laptop_data["current_stock"], laptop_data["reserved_stock"]
        )
        print(f"📦 LAPTOP-001: {laptop_data['name']} - Status: {status}")

    # Test validation
    try:
        valid_id = server._validate_product_id("TEST-ITEM")
        print(f"✅ Validation works: {valid_id}")
    except Exception as e:
        print(f"❌ Validation failed: {e}")

    print("⚡ Quick test completed!")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "quick":
        asyncio.run(run_quick_test())
    else:
        asyncio.run(run_comprehensive_test())
