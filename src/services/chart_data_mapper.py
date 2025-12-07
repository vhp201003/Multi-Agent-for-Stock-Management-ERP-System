import logging
from typing import Any, Dict, List, Optional, Union

from src.typing.schema import (
    BarChartDataSource,
    ChartDataSource,
    HorizontalBarChartDataSource,
    LineChartDataSource,
    PieChartDataSource,
    ScatterPlotDataSource,
)

logger = logging.getLogger(__name__)

MAX_DATA_POINTS = 100
MAX_FIELD_NAME_LEN = 100


class ChartDataMapper:
    """
    Type-safe chart data extractor with format routing.

    Philosophy:
    - Each chart type has specific field requirements
    - Horizontal bar returns Recharts format: {chartData, layout}
    - Vertical bar/line/pie return legacy format: {labels, datasets}
    - Type safety via discriminated union
    """

    @staticmethod
    def extract_chart_data(
        full_data: Dict[str, Any],
        data_source: ChartDataSource,
        graph_type: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Main entry point - routes to type-specific extractor.

        Args:
            full_data: Complete agent results
            data_source: Type-safe data source (discriminated union)
            graph_type: Chart type for validation

        Returns:
            Chart data in appropriate format or None
        """
        try:
            # Route based on concrete type
            if isinstance(data_source, HorizontalBarChartDataSource):
                return ChartDataMapper._extract_horizontal_bar(full_data, data_source)

            elif isinstance(data_source, BarChartDataSource):
                return ChartDataMapper._extract_vertical_bar(full_data, data_source)

            elif isinstance(data_source, LineChartDataSource):
                return ChartDataMapper._extract_line(full_data, data_source)

            elif isinstance(data_source, PieChartDataSource):
                return ChartDataMapper._extract_pie(full_data, data_source)

            elif isinstance(data_source, ScatterPlotDataSource):
                return ChartDataMapper._extract_scatter(full_data, data_source)

            else:
                logger.warning(f"Unknown data source type: {type(data_source)}")
                return None

        except Exception as e:
            logger.error(f"Chart extraction failed: {e}", exc_info=True)
            return None

    @staticmethod
    def _extract_horizontal_bar(
        full_data: Dict[str, Any],
        source: HorizontalBarChartDataSource,
    ) -> Optional[Dict[str, Any]]:
        """Extract data for horizontal bar chart in Recharts format."""
        tool_result = ChartDataMapper._locate_tool_result(
            full_data, source.agent_type, source.tool_name
        )
        if not tool_result:
            logger.warning(f"Tool not found: {source.agent_type}.{source.tool_name}")
            return None

        data_array = ChartDataMapper._find_data_array(tool_result)
        if not data_array:
            logger.warning(f"No chartable array in {source.tool_name}")
            return None

        chart_data = []
        for item in data_array[:20]:  # Limit 20 for horizontal bar
            if not isinstance(item, dict):
                continue

            category = item.get(source.category_field)
            value = item.get(source.value_field)

            if category is None or value is None:
                continue

            try:
                chart_data.append(
                    {
                        "name": str(category),
                        "value": float(value),
                    }
                )
            except (ValueError, TypeError):
                chart_data.append(
                    {
                        "name": str(category),
                        "value": 0.0,
                    }
                )

        if not chart_data:
            logger.warning(
                f"No data extracted from {source.category_field}, {source.value_field}"
            )
            return None

        logger.info(
            f"Extracted {len(chart_data)} points (recharts format) from {source.tool_name}"
        )
        return {
            "chartData": chart_data,
            "dataKey": "value",
            "nameKey": "name",
            "layout": "horizontal",
        }

    @staticmethod
    def _extract_vertical_bar(
        full_data: Dict[str, Any],
        source: BarChartDataSource,
    ) -> Optional[Dict[str, Any]]:
        """Extract data for vertical bar chart in legacy format."""
        tool_result = ChartDataMapper._locate_tool_result(
            full_data, source.agent_type, source.tool_name
        )
        if not tool_result:
            logger.warning(f"Tool not found: {source.agent_type}.{source.tool_name}")
            return None

        data_array = ChartDataMapper._find_data_array(tool_result)
        if not data_array:
            logger.warning(f"No chartable array in {source.tool_name}")
            return None

        labels, values = [], []
        for item in data_array[:15]:  # Limit 15 for vertical bar
            if not isinstance(item, dict):
                continue

            category = item.get(source.category_field)
            value = item.get(source.value_field)

            if category is None or value is None:
                continue

            labels.append(str(category))
            try:
                values.append(float(value))
            except (ValueError, TypeError):
                values.append(0.0)

        if not labels:
            logger.warning(
                f"No data extracted from {source.category_field}, {source.value_field}"
            )
            return None

        logger.info(
            f"Extracted {len(labels)} points (legacy format) from {source.tool_name}"
        )
        return {
            "labels": labels,
            "datasets": [
                {
                    "label": source.value_field.replace("_", " ").title(),
                    "data": values,
                    "fill": False,
                }
            ],
        }

    @staticmethod
    def _extract_line(
        full_data: Dict[str, Any],
        source: LineChartDataSource,
    ) -> Optional[Dict[str, Any]]:
        """Extract data for line chart in legacy format."""
        tool_result = ChartDataMapper._locate_tool_result(
            full_data, source.agent_type, source.tool_name
        )
        if not tool_result:
            logger.warning(f"Tool not found: {source.agent_type}.{source.tool_name}")
            return None

        data_array = ChartDataMapper._find_data_array(tool_result)
        if not data_array:
            logger.warning(f"No chartable array in {source.tool_name}")
            return None

        labels, values = [], []
        for item in data_array[:50]:  # Limit 50 for line chart
            if not isinstance(item, dict):
                continue

            x_val = item.get(source.x_field)
            y_val = item.get(source.y_field)

            if x_val is None or y_val is None:
                continue

            labels.append(str(x_val))
            try:
                values.append(float(y_val))
            except (ValueError, TypeError):
                values.append(0.0)

        if not labels:
            logger.warning(f"No data extracted from {source.x_field}, {source.y_field}")
            return None

        logger.info(
            f"Extracted {len(labels)} points (legacy format) from {source.tool_name}"
        )
        return {
            "labels": labels,
            "datasets": [
                {
                    "label": source.y_field.replace("_", " ").title(),
                    "data": values,
                    "fill": True,
                }
            ],
        }

    @staticmethod
    def _extract_pie(
        full_data: Dict[str, Any],
        source: PieChartDataSource,
    ) -> Optional[Dict[str, Any]]:
        """Extract data for pie chart in legacy format."""
        tool_result = ChartDataMapper._locate_tool_result(
            full_data, source.agent_type, source.tool_name
        )
        if not tool_result:
            logger.warning(f"Tool not found: {source.agent_type}.{source.tool_name}")
            return None

        data_array = ChartDataMapper._find_data_array(tool_result)
        if not data_array:
            logger.warning(f"No chartable array in {source.tool_name}")
            return None

        labels, values = [], []
        for item in data_array[:10]:  # Limit 10 for pie chart
            if not isinstance(item, dict):
                continue

            label = item.get(source.label_field)
            value = item.get(source.value_field)

            if label is None or value is None:
                continue

            labels.append(str(label))
            try:
                values.append(float(value))
            except (ValueError, TypeError):
                values.append(0.0)

        if not labels:
            logger.warning(
                f"No data extracted from {source.label_field}, {source.value_field}"
            )
            return None

        logger.info(
            f"Extracted {len(labels)} points (legacy format) from {source.tool_name}"
        )
        return {
            "labels": labels,
            "datasets": [
                {
                    "label": source.value_field.replace("_", " ").title(),
                    "data": values,
                    "fill": False,
                }
            ],
        }

    @staticmethod
    def _extract_scatter(
        full_data: Dict[str, Any],
        source: ScatterPlotDataSource,
    ) -> Optional[Dict[str, Any]]:
        """Extract data for scatter plot in Recharts format."""
        tool_result = ChartDataMapper._locate_tool_result(
            full_data, source.agent_type, source.tool_name
        )
        if not tool_result:
            logger.warning(f"Tool not found: {source.agent_type}.{source.tool_name}")
            return None

        data_array = ChartDataMapper._find_data_array(tool_result)
        if not data_array:
            logger.warning(f"No chartable array in {source.tool_name}")
            return None

        scatter_data = []
        groups = set()  # Track unique groups for legend

        for item in data_array[:100]:  # Limit 100 for scatter
            if not isinstance(item, dict):
                continue

            x_val = item.get(source.x_field)
            y_val = item.get(source.y_field)

            if x_val is None or y_val is None:
                continue

            try:
                point = {
                    "x": float(x_val),
                    "y": float(y_val),
                }
            except (ValueError, TypeError):
                continue

            # Optional: Add name for tooltip
            if source.name_field:
                name_val = item.get(source.name_field)
                point["name"] = str(name_val) if name_val else "Unknown"

            # Optional: Add group for coloring
            if source.group_field:
                group_val = item.get(source.group_field)
                group = str(group_val) if group_val else "Ungrouped"
                point["group"] = group
                groups.add(group)

            scatter_data.append(point)

        if not scatter_data:
            logger.warning(f"No data extracted from {source.x_field}, {source.y_field}")
            return None

        # Build result in Recharts format
        result = {
            "scatterData": scatter_data,
            "xKey": "x",
            "yKey": "y",
        }

        if source.name_field:
            result["nameKey"] = "name"

        if source.group_field:
            result["groupKey"] = "group"
            result["groups"] = sorted(list(groups))  # For legend

        logger.info(
            f"Extracted {len(scatter_data)} points (scatter format) from {source.tool_name}"
        )
        return result

    @staticmethod
    def _validate_data_source(data_source: Union[ChartDataSource]) -> None:
        """Basic validation to prevent injection/crashes."""
        # Get field names based on type
        field_names = []
        if isinstance(
            data_source,
            (BarChartDataSource, HorizontalBarChartDataSource, PieChartDataSource),
        ):
            # These have category_field/value_field or label_field/value_field
            if hasattr(data_source, "category_field"):
                field_names = [data_source.category_field, data_source.value_field]
            else:
                field_names = [data_source.label_field, data_source.value_field]
        elif isinstance(data_source, LineChartDataSource):
            field_names = [data_source.x_field, data_source.y_field]
        elif isinstance(data_source, ScatterPlotDataSource):
            field_names = [data_source.x_field, data_source.y_field]
            if data_source.name_field:
                field_names.append(data_source.name_field)
            if data_source.group_field:
                field_names.append(data_source.group_field)

        for field_name in field_names:
            if len(field_name) > MAX_FIELD_NAME_LEN:
                raise ValueError(f"Field name too long: {field_name[:50]}...")

    @staticmethod
    def _locate_tool_result(
        full_data: Dict[str, Any],
        agent_type: str,
        tool_name: str,
    ) -> Optional[Dict[str, Any]]:
        agent_data = full_data.get(agent_type)
        if not isinstance(agent_data, dict):
            return None

        tool_result = agent_data.get(tool_name)
        return tool_result if isinstance(tool_result, dict) else None

    @staticmethod
    def _find_data_array(tool_result: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
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
    ) -> tuple[List[str], List[float]]:
        """Legacy method for backward compatibility."""
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
        """Reasonable limits to prevent UI lag."""
        limits = {
            "piechart": 10,
            "barchart": 15,
            "horizontalbarchart": 20,
            "linechart": 50,
        }
        return limits.get(graph_type, 20)
