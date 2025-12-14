import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ========== Global storage - 1 dict đơn giản ==========
_REGISTERED_AGENTS: Dict[str, Dict[str, Any]] = {}


def register_agent(
    agent_type: str,
    description: str,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """
    Đăng ký agent với tools của nó.

    Args:
        agent_type: Tên agent (inventory, analytics, ...)
        description: Mô tả agent làm gì
        tools: List tools từ MCP server [{name, description, inputSchema}, ...]
    """
    parsed_tools = []
    if tools:
        for t in tools:
            parsed_tools.append(
                {
                    "name": t.get("name", ""),
                    "description": t.get("description", ""),
                }
            )

    _REGISTERED_AGENTS[agent_type] = {
        "description": description,
        "tools": parsed_tools,
    }

    logger.info(
        f"Registered '{agent_type}' with {len(parsed_tools)} tools: "
        f"{[t['name'] for t in parsed_tools]}"
    )


def unregister_agent(agent_type: str) -> None:
    """Xóa agent khỏi registry (khi shutdown)."""
    if agent_type in _REGISTERED_AGENTS:
        del _REGISTERED_AGENTS[agent_type]
        logger.info(f"Unregistered '{agent_type}'")


def get_agent(agent_type: str) -> Optional[Dict[str, Any]]:
    """Lấy info của 1 agent."""
    return _REGISTERED_AGENTS.get(agent_type)


def get_all_agents() -> Dict[str, Dict[str, Any]]:
    """Lấy tất cả agents đã đăng ký (format giống agents.json cũ)."""
    return dict(_REGISTERED_AGENTS)


def get_agent_types() -> List[str]:
    """Lấy danh sách tên các agents."""
    return list(_REGISTERED_AGENTS.keys())


def is_registered(agent_type: str) -> bool:
    """Check agent đã đăng ký chưa."""
    return agent_type in _REGISTERED_AGENTS


def clear_registry() -> None:
    """Xóa hết (dùng cho testing)."""
    _REGISTERED_AGENTS.clear()
    logger.info("Registry cleared")
