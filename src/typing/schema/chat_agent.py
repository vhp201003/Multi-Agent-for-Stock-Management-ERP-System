from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from .base_schema import BaseSchema


class LLMLayoutField(BaseModel):
    """
    Base class for all layout fields. Every field in the layout array MUST be a complete object
    with field_type and its specific properties.

    CRITICAL: Do NOT return string representations or incomplete objects.
    Each array element must be a valid JSON object like: {"field_type": "markdown", "content": "..."}
    """

    field_type: Literal[
        "markdown",
        "graph",
        "table",
    ] = Field(
        ...,
        description="REQUIRED: Type of layout field. Must be exactly one of: 'markdown', 'graph', or 'table'",
    )


class LLMMarkdownField(LLMLayoutField):
    """
    Markdown text field for headings, summaries, metrics, and formatted content.

    Use this for:
    - Section headings to introduce charts (## Main Heading, ### Subheading)
    - Executive summaries highlighting key insights
    - Contextual information before visualizations
    - Brief metrics and KPIs (**Total Value**: $52,887.72)
    - Actionable insights and recommendations

    **BEST PRACTICE**: Combine markdown with charts
    - Start with markdown for context/summary
    - Follow with graph for visual representation
    - This provides both insight and visualization

    Format: {"field_type": "markdown", "content": "## Heading\\n\\n**Bold text**"}
    """

    field_type: Literal["markdown"] = Field(
        default="markdown", description="Must be exactly 'markdown'"
    )
    content: Optional[str] = Field(
        default="",
        description="REQUIRED: Markdown-formatted text content. Use this to introduce charts or summarize insights.",
    )


# ============ BASE CLASS ============
class BaseChartDataSource(BaseModel):
    """Base class for all chart data sources."""

    agent_type: Optional[str] = Field(
        default=None,
        description="Agent that provides the data (e.g., 'analytics_agent', 'inventory_agent')",
    )
    tool_name: Optional[str] = Field(
        default=None,
        description="Tool that generated the data (e.g., 'analyze_top_performers', 'check_stock')",
    )


class TableDataSource(BaseChartDataSource):
    columns: List[str] = Field(
        ...,
        description="List of EXACT field names (keys) to extract from data rows for columns.",
    )
    headers: Optional[List[str]] = Field(
        None,
        description="Optional list of human-readable headers. If not provided, uses column names.",
    )


# ============ SPECIFIC CHART SCHEMAS ============
class BarChartDataSource(BaseChartDataSource):
    chart_type: Literal["barchart"] = "barchart"
    category_field: Optional[str] = Field(
        default=None,
        description="Field for X-axis categories (e.g., 'item_name', 'warehouse')",
    )
    value_field: Optional[str] = Field(
        default=None,
        description="Field for Y-axis values (e.g., 'revenue', 'stock_qty')",
    )


class HorizontalBarChartDataSource(BaseChartDataSource):
    chart_type: Literal["horizontalbarchart"] = "horizontalbarchart"
    category_field: Optional[str] = Field(
        default=None,
        description="Field for Y-axis categories (e.g., 'item_name', 'product_name')",
    )
    value_field: Optional[str] = Field(
        default=None, description="Field for X-axis values (e.g., 'revenue', 'qty')"
    )


class LineChartDataSource(BaseChartDataSource):
    chart_type: Literal["linechart"] = "linechart"
    x_field: Optional[str] = Field(
        default=None,
        description="Field for X-axis, usually date/time (e.g., 'posting_date', 'date')",
    )
    y_field: Optional[str] = Field(
        default=None,
        description="Field for Y-axis metric (e.g., 'stock_qty', 'amount')",
    )


class PieChartDataSource(BaseChartDataSource):
    chart_type: Literal["piechart"] = "piechart"
    label_field: Optional[str] = Field(
        default=None,
        description="Field for slice labels (e.g., 'category', 'item_group')",
    )
    value_field: Optional[str] = Field(
        default=None, description="Field for slice sizes (e.g., 'total_sales', 'count')"
    )


class ScatterPlotDataSource(BaseChartDataSource):
    chart_type: Literal["scatterplot"] = "scatterplot"
    x_field: Optional[str] = Field(
        default=None,
        description="Field for X-axis values (e.g., 'price', 'quantity', 'weight')",
    )
    y_field: Optional[str] = Field(
        default=None,
        description="Field for Y-axis values (e.g., 'sales', 'profit', 'revenue')",
    )
    name_field: Optional[str] = Field(
        None,
        description="Optional field for point labels/tooltips (e.g., 'item_name', 'product_code')",
    )
    group_field: Optional[str] = Field(
        None,
        description="Optional field for grouping/coloring points (e.g., 'category', 'warehouse', 'region')",
    )


# ============ UNION TYPE ============
ChartDataSource = Union[
    BarChartDataSource,
    HorizontalBarChartDataSource,
    LineChartDataSource,
    PieChartDataSource,
    ScatterPlotDataSource,
]


class LLMGraphField(LLMLayoutField):
    """
    Chart/graph visualization field with data source specification.

    **PREFERRED FIELD TYPE**: Use this whenever you have numeric data! Charts are more engaging and easier to understand than tables.

    CRITICAL RULES:
    1. You MUST specify data_source with exact field names from the context
    2. Set data=null (backend auto-fills from data_source)
    3. Choose graph_type based on data structure, NOT domain knowledge

    Chart Type Selection (based on data structure):
    - piechart: Distribution/proportions (label=categories, value=numeric) - max 8 items
    - barchart: Comparison across categories (label=categories, value=numeric) - max 15 items
    - linechart: Trends/progression (label=sequential, value=numeric) - max 50 points

    **USE CHARTS FOR:**
    - Stock levels by product → barchart
    - Movement over time → linechart
    - Category distribution → piechart
    - Any numeric comparison → barchart or linechart

    Example:
    {
        "field_type": "graph",
        "graph_type": "barchart",
        "title": "Product Stock Levels",
        "description": "Current inventory by product",
        "data_source": {
            "agent_type": "inventory_agent",
            "tool_name": "check_stock",
            "label_field": "product_name",
            "value_field": "quantity",
            "data_path": "data"
        },
        "data": null
    }
    """

    field_type: Literal["graph"] = Field(
        default="graph", description="Must be exactly 'graph'"
    )
    graph_type: Literal[
        "piechart", "barchart", "horizontalbarchart", "linechart", "scatterplot"
    ] = Field(
        ...,
        description="REQUIRED: Chart type based on data structure. Must be one of: 'piechart', 'barchart', 'horizontalbarchart', 'linechart', 'scatterplot'",
    )
    title: Optional[str] = Field(
        None,
        description=(
            "Optional: Chart title describing what the chart shows.\n"
            "Use the same language as the user's query.\n"
            "Examples: 'Product Stock Levels', 'Mức Tồn Kho Sản Phẩm'"
        ),
    )
    description: Optional[str] = Field(
        None,
        description=(
            "Optional: Brief explanation of what the chart represents.\n"
            "Use the same language as the user's query.\n"
            "Provide business context if relevant."
        ),
    )
    data_source: Optional[Union[ChartDataSource, Dict[str, Any]]] = Field(
        default=None,
        description="REQUIRED: Type-safe data source specification. Must include 'chart_type' field matching graph_type.",
    )


class LLMTableField(LLMLayoutField):
    """
    Tabular data field for displaying structured records.
    Use when exact details, text attributes, or mixed data types are needed.
    """

    field_type: Literal["table"] = Field(
        default="table", description="Must be exactly 'table'"
    )
    title: Optional[str] = Field(
        None,
        description=(
            "Optional: Table title/caption.\n"
            "Use the same language as the user's query.\n"
            "Examples: 'Product Details', 'Chi Tiết Sản Phẩm'"
        ),
    )
    data_source: Optional[TableDataSource] = Field(
        default=None,
        description="REQUIRED: Type-safe data source specification. Must include 'columns' to extract.",
    )


class ChatAgentSchema(BaseSchema):
    layout: List[
        Union[
            LLMMarkdownField,
            LLMGraphField,
            LLMTableField,
        ]
    ] = Field(
        ...,
        description=(
            "REQUIRED: Array of layout field objects. Each element MUST be a complete object with field_type and its properties.\n\n"
            "Available field types:\n"
            "- markdown: Text content with formatting (headings, bold, lists, metrics)\n"
            "- graph: Data visualization (piechart/barchart/linechart) with data_source specification\n"
            "- table: Tabular data with columns and rows\n\n"
            "YOU decide which fields to include based on the query and available data.\n"
            'Example: [{"field_type": "markdown", "content": "## Heading\\n\\n**Metric**: value"}, '
            '{"field_type": "graph", "graph_type": "barchart", "title": "Chart Title", "data_source": {...}, "data": null}]'
        ),
    )
    full_data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="DO NOT INCLUDE THIS FIELD. Auto-populated by backend only. Leave unset.",
    )
