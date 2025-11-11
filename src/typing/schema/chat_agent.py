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
    - Section headings (## Main Heading, ### Subheading)
    - Executive summaries and key insights
    - Metrics and KPIs (**Total Value**: $52,887.72)
    - Lists and bullet points
    - Horizontal separators (---)

    Format: {"field_type": "markdown", "content": "## Heading\\n\\n**Bold text**"}
    """

    field_type: Literal["markdown"] = Field(
        default="markdown", description="Must be exactly 'markdown'"
    )
    content: str = Field(
        ...,
        description=(
            "REQUIRED: Markdown-formatted text content.\n\n"
            "Supported formatting:\n"
            "- Headings: ## Main Heading, ### Subheading\n"
            "- Emphasis: **bold**, *italic*\n"
            "- Lists: - item, 1. numbered\n"
            "- Separators: ---\n"
            "- Code: `inline code`, ```block```\n\n"
            "Include business context, professional language, and actionable insights.\n"
            "Match the user's query language (Vietnamese → Vietnamese content, English → English content)."
        ),
    )


class ChartDataSource(BaseModel):
    """
    Specification for extracting chart data from context. This tells the system WHERE to find data
    and HOW to map it to chart axes.

    CRITICAL: You MUST identify exact field names from the available data context.

    Example for product inventory:
    {
        "agent_type": "inventory_agent",
        "tool_name": "check_stock",
        "label_field": "product_name",    # X-axis/categories
        "value_field": "quantity",         # Y-axis/values
        "data_path": "data"                # Path to array
    }
    """

    agent_type: str = Field(
        ...,
        description=(
            "REQUIRED: Which agent provides the data. Must match exact agent name from context.\n"
            "Examples: 'inventory_agent', 'sales_agent', 'finance_agent'\n"
            "Look at the AVAILABLE DATA section to find the correct agent_type."
        ),
    )
    tool_name: str = Field(
        ...,
        description=(
            "REQUIRED: Which tool result to use from the agent. Must match exact tool name from context.\n"
            "Examples: 'check_stock', 'get_history', 'search_products'\n"
            "Look at the agent's tools in AVAILABLE DATA to find the correct tool_name."
        ),
    )
    label_field: str = Field(
        ...,
        description=(
            "REQUIRED: Field name for chart labels/X-axis/categories. Must be exact field name from data.\n"
            "Examples: 'product_name', 'date', 'category', 'region', 'month'\n"
            "This field should contain categorical or sequential values that will appear on the X-axis."
        ),
    )
    value_field: str = Field(
        ...,
        description=(
            "REQUIRED: Field name for chart values/Y-axis/metrics. Must be exact field name from data.\n"
            "Examples: 'quantity', 'amount', 'revenue', 'count', 'percentage'\n"
            "This field should contain numeric values that will be visualized."
        ),
    )
    data_path: Optional[str] = Field(
        default="data",
        description=(
            "Optional: Path to the array in tool result. Default is 'data'.\n"
            "Use dot notation for nested paths: 'results.items', 'summary.records'\n"
            "If the array is at the top level of tool result, use 'data'."
        ),
    )


class LLMGraphField(LLMLayoutField):
    """
    Chart/graph visualization field with data source specification.

    CRITICAL RULES:
    1. You MUST specify data_source with exact field names from the context
    2. Set data=null (backend auto-fills from data_source)
    3. Choose graph_type based on data structure, NOT domain knowledge

    Chart Type Selection (based on data structure):
    - piechart: Distribution/proportions (label=categories, value=numeric) - max 8 items
    - barchart: Comparison across categories (label=categories, value=numeric) - max 15 items
    - linechart: Trends/progression (label=sequential, value=numeric) - max 50 points

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
    graph_type: Literal["piechart", "barchart", "linechart"] = Field(
        ...,
        description=(
            "REQUIRED: Chart type based on data structure (NOT domain):\n\n"
            "- 'piechart': Show proportions/distribution\n"
            "  When: Have categories + numeric values representing parts of whole\n"
            "  Example: Product distribution, category breakdown, status counts\n"
            "  Max: 8 items recommended\n\n"
            "- 'barchart': Compare values across categories\n"
            "  When: Have categories + numeric values to compare side-by-side\n"
            "  Example: Stock levels by product, sales by region, counts by type\n"
            "  Max: 15 items recommended\n\n"
            "- 'linechart': Show progression/trends over sequence\n"
            "  When: Have ordered/sequential labels + numeric values\n"
            "  Example: Time series, historical trends, sequential measurements\n"
            "  Max: 50 points recommended\n\n"
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
    data_source: ChartDataSource = Field(
        ...,
        description=(
            "REQUIRED: Specification of WHERE and HOW to extract chart data from context.\n\n"
            "You MUST:\n"
            "1. Look at AVAILABLE DATA section to identify correct agent_type and tool_name\n"
            "2. Examine the tool result structure to identify exact field names\n"
            "3. Specify label_field (X-axis) and value_field (Y-axis) using EXACT field names\n"
            "4. Set data_path if array is nested (default 'data' works for most cases)\n\n"
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

    Use tables when:
    - Need to show multiple attributes per item (product details, transaction records)
    - Stakeholders need specific detailed information
    - Data doesn't fit visualization format well

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
    data: dict = Field(
        ...,
        description=(
            "REQUIRED: Table data structure.\n\n"
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
