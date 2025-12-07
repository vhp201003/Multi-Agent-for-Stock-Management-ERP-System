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
        description=(
            "REQUIRED: Markdown-formatted text content.\n\n"
            "Supported formatting:\n"
            "- Headings: ## Main Heading, ### Subheading\n"
            "- Emphasis: **bold**, *italic*\n"
            "- Lists: - item, 1. numbered\n"
            "- Separators: ---\n"
            "- Code: `inline code`, ```block```\n\n"
            "Include business context, professional language, and actionable insights.\n"
            "Match the user's query language (Vietnamese → Vietnamese content, English → English content).\n\n"
            "**TIP**: Use this to introduce charts - provide context before visualization."
        ),
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


# ============ SPECIFIC CHART SCHEMAS ============
class BarChartDataSource(BaseChartDataSource):
    """Vertical bar chart: categories on X-axis, values on Y-axis."""

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
    """Horizontal bar chart: categories on Y-axis, values on X-axis. Better for many items with long names."""

    chart_type: Literal["horizontalbarchart"] = "horizontalbarchart"
    category_field: Optional[str] = Field(
        default=None,
        description="Field for Y-axis categories (e.g., 'item_name', 'product_name')",
    )
    value_field: Optional[str] = Field(
        default=None, description="Field for X-axis values (e.g., 'revenue', 'qty')"
    )


class LineChartDataSource(BaseChartDataSource):
    """Line chart: X-axis (usually time/sequence), Y-axis (metric)."""

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
    """Pie chart: labels and their proportions."""

    chart_type: Literal["piechart"] = "piechart"
    label_field: Optional[str] = Field(
        default=None,
        description="Field for slice labels (e.g., 'category', 'item_group')",
    )
    value_field: Optional[str] = Field(
        default=None, description="Field for slice sizes (e.g., 'total_sales', 'count')"
    )


class ScatterPlotDataSource(BaseChartDataSource):
    """Scatter plot: X-Y correlation with optional grouping and labeling."""

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
        description=(
            "REQUIRED: Chart type based on data structure (NOT domain):\n\n"
            "- 'piechart': Show proportions/distribution\n"
            "  When: Have categories + numeric values representing parts of whole\n"
            "  Example: Product distribution, category breakdown, status counts\n"
            "  Max: 8 items recommended\n\n"
            "- 'barchart': Compare values across categories (vertical)\n"
            "  When: Have categories + numeric values to compare side-by-side\n"
            "  Example: Stock levels by product, sales by region, counts by type\n"
            "  Max: 15 items recommended\n\n"
            "- 'horizontalbarchart': Compare values across categories (horizontal)\n"
            "  When: Have many categories (>5) with long names + numeric values\n"
            "  Example: Product comparison, multi-item inventory levels, top performers\n"
            "  Max: 20 items recommended (better for long labels)\n\n"
            "- 'linechart': Show progression/trends over sequence\n"
            "  When: Have ordered/sequential labels + numeric values\n"
            "  Example: Time series, historical trends, sequential measurements\n"
            "  Max: 50 points recommended\n\n"
            "- 'scatterplot': Show correlation/relationship between two numeric variables\n"
            "  When: Have two numeric fields to compare (X vs Y)\n"
            "  Example: Price vs Sales, Quantity vs Revenue, Weight vs Cost\n"
            "  Max: 100 points recommended\n"
            "  Optional: Add group_field for colored clusters, name_field for tooltips\n\n"
            "Select based on what insights the data provides, not what domain it's from."
        ),
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
        description=(
            "REQUIRED: Type-safe data source specification. MUST include 'chart_type' field matching graph_type.\n\n"
            "CRITICAL: Always set 'chart_type' field first!\n\n"
            "Schema by chart type:\n"
            '- barchart: {"chart_type": "barchart", "agent_type": "...", "tool_name": "...", "category_field": "...", "value_field": "..."}\n'
            '- horizontalbarchart: {"chart_type": "horizontalbarchart", "agent_type": "...", "tool_name": "...", "category_field": "...", "value_field": "..."}\n'
            '- linechart: {"chart_type": "linechart", "agent_type": "...", "tool_name": "...", "x_field": "...", "y_field": "..."}\n'
            '- piechart: {"chart_type": "piechart", "agent_type": "...", "tool_name": "...", "label_field": "...", "value_field": "..."}\n'
            '- scatterplot: {"chart_type": "scatterplot", "agent_type": "...", "tool_name": "...", "x_field": "...", "y_field": "...", "name_field": "...", "group_field": "..."}\n\n'
            "Steps:\n"
            "1. Set chart_type to EXACTLY match graph_type\n"
            "2. Identify agent_type and tool_name from AVAILABLE DATA section\n"
            "3. Examine tool result structure for exact field names\n"
            "4. Use correct field names for the chart type (see schemas above)\n\n"
            "Example for scatterplot:\n"
            "{\n"
            '  "chart_type": "scatterplot",\n'
            '  "agent_type": "analytics",\n'
            '  "tool_name": "analyze_price_performance",\n'
            '  "x_field": "standard_rate",\n'
            '  "y_field": "total_qty_sold",\n'
            '  "name_field": "item_name",\n'
            '  "group_field": "item_group"\n'
            "}\n\n"
            "DO NOT guess field names - they must match exactly what's in the data."
        ),
    )
    data: Optional[dict] = Field(
        default=None,
        description=(
            "DO NOT SET THIS FIELD. Always use null/None.\n"
            "Backend automatically fills this from data_source specification.\n"
            "Format after auto-fill: {labels: [...], datasets: [{label, data}]}"
        ),
    )


class LLMTableField(LLMLayoutField):
    """
    Tabular data field for displaying structured records with multiple attributes.

    **USE SPARINGLY**: Tables should be your LAST RESORT. Prefer charts/graphs for numeric data.

    Use tables ONLY when:
    - Data is primarily text-based (names, descriptions, IDs)
    - Multiple diverse attributes per item that don't fit chart format
    - Charts cannot effectively convey the information
    - User explicitly asks for detailed tabular view

    **AVOID tables for:**
    - Numeric comparisons (use barchart instead)
    - Time series data (use linechart instead)
    - Distribution data (use piechart instead)

    Format:
    {
        "field_type": "table",
        "title": "Product Details",
        "data": {
            "headers": ["Product", "SKU", "Stock", "Status"],
            "rows": [
                ["Laptop", "LT-001", "45", "In Stock"],
                ["Mouse", "MS-002", "120", "In Stock"]
            ]
        }
    }
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
    data: Optional[dict] = Field(
        default=None,
        description=(
            "Table data structure.\n\n"
            "Must be object with:\n"
            "- 'headers': Array of column header strings\n"
            "- 'rows': Array of arrays (each inner array is one row)\n\n"
            "Example:\n"
            "{\n"
            '  "headers": ["Name", "Quantity", "Status"],\n'
            '  "rows": [\n'
            '    ["Product A", "50", "Active"],\n'
            '    ["Product B", "30", "Low Stock"]\n'
            "  ]\n"
            "}\n\n"
            "Use the same language as user's query for headers and values."
        ),
    )


class ChatAgentSchema(BaseSchema):
    """
    CRITICAL: This schema defines the ONLY valid JSON structure for responses.
    You MUST return EXACTLY: {"layout": [...]}

    DO NOT add any extra fields like "summary", "metadata", "thinking", etc.
    DO NOT return just an array - must be object with "layout" key.
    """

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
