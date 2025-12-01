import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

from src.mcp.server.forecasting_server.server import (
    ForecastingMCPServer,
    ForecastingServerConfig,
)

# Mock ERPNext connection
mock_erpnext = AsyncMock()
mock_erpnext.get_list.side_effect = [
    [
        {"item_code": "ACC-0001", "item_name": "Accounting Software License"},
        {"item_code": "RCK-0128", "item_name": "Rocking Chair"},
    ],  # Items
    [{"name": "Kho Hà Nội - HP"}, {"name": "Kho Hồ Chí Minh"}],  # Warehouses
]

# Patch get_erpnext_connection
import src.mcp.server.forecasting_server.server

src.mcp.server.forecasting_server.server.get_erpnext_connection = MagicMock(
    return_value=mock_erpnext
)


async def test_fuzzy_search():
    server = ForecastingMCPServer(ForecastingServerConfig(name="forecasting"))

    print("Testing Item Fuzzy Search...")
    # Test exact match
    match = await server._fuzzy_match_item("ACC-0001")
    print(f"Input: 'ACC-0001' -> Match: '{match}' (Expected: 'ACC-0001')")

    # Test fuzzy match on code
    match = await server._fuzzy_match_item("acc 0001")
    print(f"Input: 'acc 0001' -> Match: '{match}' (Expected: 'ACC-0001')")

    # Test fuzzy match on name
    match = await server._fuzzy_match_item("accounting soft")
    print(f"Input: 'accounting soft' -> Match: '{match}' (Expected: 'ACC-0001')")

    match = await server._fuzzy_match_item("rocking chair")
    print(f"Input: 'rocking chair' -> Match: '{match}' (Expected: 'RCK-0128')")

    print("\nTesting Warehouse Fuzzy Search...")
    # Test exact match
    match = await server._fuzzy_match_warehouse("Kho Hà Nội - HP")
    print(f"Input: 'Kho Hà Nội - HP' -> Match: '{match}' (Expected: 'Kho Hà Nội - HP')")

    # Test fuzzy match
    match = await server._fuzzy_match_warehouse("kho ha noi")
    print(f"Input: 'kho ha noi' -> Match: '{match}' (Expected: 'Kho Hà Nội - HP')")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(test_fuzzy_search())
