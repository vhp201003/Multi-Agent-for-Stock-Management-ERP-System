import logging
from typing import Any, Dict, List, Optional, Tuple

from src.typing.schema import ChartDataSource

logger = logging.getLogger(__name__)

# Security limits
MAX_DATA_POINTS = 100
MAX_FIELD_NAME_LEN = 100


class ChartDataMapper:
    @staticmethod
    def extract_chart_data(
        full_data: Dict[str, Any],
        data_source: ChartDataSource,
        graph_type: str,
    ) -> Optional[Dict[str, Any]]:
        try:
            ChartDataMapper._validate_data_source(data_source)

            tool_result = ChartDataMapper._locate_tool_result(
                full_data, data_source.agent_type, data_source.tool_name
            )
            if not tool_result:
                logger.warning(
                    f"Tool not found: {data_source.agent_type}.{data_source.tool_name}"
                )
                return None

            data_array = ChartDataMapper._find_data_array(tool_result)
            if not data_array:
                logger.warning(f"No chartable array in {data_source.tool_name}")
                return None

            labels, values = ChartDataMapper._extract_fields(
                data_array, data_source.label_field, data_source.value_field
            )
            if not labels:
                logger.warning(
                    f"No data extracted from fields: {data_source.label_field}, {data_source.value_field}"
                )
                return None

            max_points = ChartDataMapper._get_limit_for_chart_type(graph_type)
            labels = labels[:max_points]
            values = values[:max_points]

            return {
                "labels": labels,
                "datasets": [
                    {
                        "label": data_source.value_field.replace("_", " ").title(),
                        "data": values,
                        "fill": graph_type == "linechart",
                    }
                ],
            }

        except Exception as e:
            logger.error(f"Chart extraction failed: {e}", exc_info=True)
            return None

    @staticmethod
    def _validate_data_source(data_source: ChartDataSource) -> None:
        """Validate data_source fields for security."""
        for field_name in [data_source.label_field, data_source.value_field]:
            if len(field_name) > MAX_FIELD_NAME_LEN:
                raise ValueError(f"Field name too long: {field_name[:50]}...")

    @staticmethod
    def _locate_tool_result(
        full_data: Dict[str, Any],
        agent_type: str,
        tool_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Navigate to tool result: full_data[agent][tool]"""
        agent_data = full_data.get(agent_type)
        if not isinstance(agent_data, dict):
            return None

        tool_result = agent_data.get(tool_name)
        return tool_result if isinstance(tool_result, dict) else None

    @staticmethod
    def _find_data_array(tool_result: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        """Auto-discover first list of dicts (chartable data array)."""
        for key, value in tool_result.items():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                logger.debug(f"Found data array: '{key}' ({len(value)} items)")
                return value
        return None

    @staticmethod
    def _extract_fields(
        data_array: List[Dict[str, Any]],
        label_field: str,
        value_field: str,
    ) -> Tuple[List[str], List[float]]:
        labels: List[str] = []
        values: List[float] = []

        for item in data_array:
            if not isinstance(item, dict):
                continue

            label_val = item.get(label_field)
            value_val = item.get(value_field)
            if label_val is None or value_val is None:
                continue

            labels.append(str(label_val) if label_val else "<unknown>")

            try:
                values.append(float(value_val))
            except (ValueError, TypeError):
                values.append(0.0)

        return labels, values

    @staticmethod
    def _get_limit_for_chart_type(graph_type: str) -> int:
        """Get recommended max data points per chart type."""
        limits = {
            "piechart": 8,
            "barchart": 15,
            "linechart": 50,
        }
        return limits.get(graph_type, 20)
