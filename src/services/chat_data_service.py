import logging
from typing import Any, Dict

from src.typing.redis import SharedData

logger = logging.getLogger(__name__)


def reconstruct_full_data(shared_data: SharedData) -> Dict[str, Any]:
    full_data: Dict[str, Any] = {}

    if not shared_data or not shared_data.result_references:
        return full_data

    try:
        for result_id, ref_data in shared_data.result_references.items():
            agent_type = ref_data.get("agent_type")
            tool_name = ref_data.get("tool_name")
            tool_result = ref_data.get("data")

            if not agent_type or not tool_name:
                continue

            if agent_type not in full_data:
                full_data[agent_type] = {}

            full_data[agent_type][tool_name] = tool_result

        logger.debug(
            f"Reconstructed full_data: {len(shared_data.result_references)} refs "
            f"-> {len(full_data)} agents"
        )

    except Exception as e:
        logger.warning(f"Failed to reconstruct full_data: {e}")

    return full_data
