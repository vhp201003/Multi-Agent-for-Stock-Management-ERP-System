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
                return ChartDataMapper.extract_horizontal_bar(full_data, data_source)

            elif isinstance(data_source, BarChartDataSource):
                return ChartDataMapper.extract_vertical_bar(full_data, data_source)

            elif isinstance(data_source, LineChartDataSource):
                return ChartDataMapper.extract_line(full_data, data_source)

            elif isinstance(data_source, PieChartDataSource):
                return ChartDataMapper.extract_pie(full_data, data_source)

            elif isinstance(data_source, ScatterPlotDataSource):
                return ChartDataMapper.extract_scatter(full_data, data_source)

            else:
                logger.warning(f"Unknown data source type: {type(data_source)}")
                return None

        except Exception as e:
            logger.error(f"Chart extraction failed: {e}", exc_info=True)
            return None

    @staticmethod
    def extract_generic(
        full_data: Dict[str, Any],
        source: ChartDataSource,
        field_extractor: callable,
        transformer: callable,
        limit: int,
    ) -> Optional[Dict[str, Any]]:
        """Generic chart data extractor with customizable field extraction and transformation.

        This eliminates code duplication across all 5 chart extraction methods.
        Each chart type provides:
        - field_extractor: fn(item, source) -> tuple of field values or None
        - transformer: fn(extracted_data, source) -> chart format dict
        - limit: max data points for this chart type

        Args:
            full_data: Complete agent results
            source: Data source configuration
            field_extractor: Callable to extract fields from each item
            transformer: Callable to transform extracted data to chart format
            limit: Maximum data points to extract

        Returns:
            Chart data dict or None if extraction fails
        """
        # Step 1: Locate tool result
        tool_result = ChartDataMapper.locate_tool_result(
            full_data, source.agent_type, source.tool_name
        )
        if not tool_result:
            logger.warning(f"Tool not found: {source.agent_type}.{source.tool_name}")
            return None

        # Step 2: Find data array
        data_array = ChartDataMapper.find_data_array(tool_result)
        if not data_array:
            logger.warning(f"No chartable array in {source.tool_name}")
            return None

        # Step 3: Extract fields from each item
        extracted = []
        for item in data_array[:limit]:
            if not isinstance(item, dict):
                continue

            fields = field_extractor(item, source)
            if fields:
                extracted.append(fields)

        # Step 4: Check if we got any data
        if not extracted:
            logger.warning(f"No data extracted from {source.tool_name}")
            return None

        # Step 5: Transform to chart format
        result = transformer(extracted, source)

        logger.info(
            f"Extracted {len(extracted)} points from {source.tool_name} "
            f"(format: {result.get('layout', 'legacy')})"
        )

        return result

    @staticmethod
    def extract_horizontal_bar(
        full_data: Dict[str, Any],
        source: HorizontalBarChartDataSource,
    ) -> Optional[Dict[str, Any]]:
        """Extract data for horizontal bar chart in Recharts format."""

        def extractor(item, src):
            """Extract category and value fields."""
            cat = item.get(src.category_field)
            val = item.get(src.value_field)
            return (cat, val) if cat is not None and val is not None else None

        def transformer(data, src):
            """Transform to Recharts format."""
            chart_data = []
            for cat, val in data:
                try:
                    chart_data.append({"name": str(cat), "value": float(val)})
                except (ValueError, TypeError):
                    chart_data.append({"name": str(cat), "value": 0.0})

            return {
                "chartData": chart_data,
                "dataKey": "value",
                "nameKey": "name",
                "layout": "horizontal",
            }

        return ChartDataMapper.extract_generic(
            full_data, source, extractor, transformer, limit=20
        )

    @staticmethod
    def extract_vertical_bar(
        full_data: Dict[str, Any],
        source: BarChartDataSource,
    ) -> Optional[Dict[str, Any]]:
        """Extract data for vertical bar chart in legacy format."""

        def extractor(item, src):
            """Extract category and value fields."""
            cat = item.get(src.category_field)
            val = item.get(src.value_field)
            return (cat, val) if cat is not None and val is not None else None

        def transformer(data, src):
            """Transform to legacy format (labels + datasets)."""
            labels, values = [], []
            for cat, val in data:
                labels.append(str(cat))
                try:
                    values.append(float(val))
                except (ValueError, TypeError):
                    values.append(0.0)

            return {
                "labels": labels,
                "datasets": [
                    {
                        "label": src.value_field.replace("_", " ").title(),
                        "data": values,
                        "fill": False,
                    }
                ],
            }

        return ChartDataMapper.extract_generic(
            full_data, source, extractor, transformer, limit=15
        )

    @staticmethod
    def extract_line(
        full_data: Dict[str, Any],
        source: LineChartDataSource,
    ) -> Optional[Dict[str, Any]]:
        """Extract data for line chart in legacy format."""

        def extractor(item, src):
            """Extract x and y fields."""
            x = item.get(src.x_field)
            y = item.get(src.y_field)
            return (x, y) if x is not None and y is not None else None

        def transformer(data, src):
            """Transform to legacy format (labels + datasets)."""
            labels, values = [], []
            for x, y in data:
                labels.append(str(x))
                try:
                    values.append(float(y))
                except (ValueError, TypeError):
                    values.append(0.0)

            return {
                "labels": labels,
                "datasets": [
                    {
                        "label": src.y_field.replace("_", " ").title(),
                        "data": values,
                        "fill": True,
                    }
                ],
            }

        return ChartDataMapper.extract_generic(
            full_data, source, extractor, transformer, limit=50
        )

    @staticmethod
    def extract_pie(
        full_data: Dict[str, Any],
        source: PieChartDataSource,
    ) -> Optional[Dict[str, Any]]:
        """Extract data for pie chart in legacy format."""

        def extractor(item, src):
            """Extract label and value fields."""
            lbl = item.get(src.label_field)
            val = item.get(src.value_field)
            return (lbl, val) if lbl is not None and val is not None else None

        def transformer(data, src):
            """Transform to legacy format (labels + datasets)."""
            labels, values = [], []
            for lbl, val in data:
                labels.append(str(lbl))
                try:
                    values.append(float(val))
                except (ValueError, TypeError):
                    values.append(0.0)

            return {
                "labels": labels,
                "datasets": [
                    {
                        "label": src.value_field.replace("_", " ").title(),
                        "data": values,
                        "fill": False,
                    }
                ],
            }

        return ChartDataMapper.extract_generic(
            full_data, source, extractor, transformer, limit=10
        )

    @staticmethod
    def extract_scatter(
        full_data: Dict[str, Any],
        source: ScatterPlotDataSource,
    ) -> Optional[Dict[str, Any]]:
        """Extract data for scatter plot in Recharts format."""

        def extractor(item, src):
            """Extract x, y, and optional name/group fields."""
            x = item.get(src.x_field)
            y = item.get(src.y_field)
            if x is None or y is None:
                return None

            # Try to convert to float for validation
            try:
                float(x)
                float(y)
            except (ValueError, TypeError):
                return None

            # Extract optional fields
            name = item.get(src.name_field) if src.name_field else None
            group = item.get(src.group_field) if src.group_field else None

            return (x, y, name, group)

        def transformer(data, src):
            """Transform to Recharts scatter format."""
            scatter_data = []
            groups = set()

            for x, y, name, group in data:
                point = {"x": float(x), "y": float(y)}

                if name is not None:
                    point["name"] = str(name) if name else "Unknown"

                if group is not None:
                    group_str = str(group) if group else "Ungrouped"
                    point["group"] = group_str
                    groups.add(group_str)

                scatter_data.append(point)

            # Build result
            result = {"scatterData": scatter_data, "xKey": "x", "yKey": "y"}

            if src.name_field:
                result["nameKey"] = "name"

            if src.group_field:
                result["groupKey"] = "group"
                result["groups"] = sorted(list(groups))

            return result

        return ChartDataMapper.extract_generic(
            full_data, source, extractor, transformer, limit=100
        )

    @staticmethod
    def validate_data_source(data_source: Union[ChartDataSource]) -> None:
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
    def locate_tool_result(
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
    def find_data_array(tool_result: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        for key, value in tool_result.items():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                logger.debug(f"Found data array: '{key}' ({len(value)} items)")
                return value
        return None

    @staticmethod
    def extract_fields(
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
    def get_limit_for_chart_type(graph_type: str) -> int:
        """Reasonable limits to prevent UI lag."""
        limits = {
            "piechart": 10,
            "barchart": 15,
            "horizontalbarchart": 20,
            "linechart": 50,
        }
        return limits.get(graph_type, 20)
