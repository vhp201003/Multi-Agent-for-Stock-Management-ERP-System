"""
ChatAgent Layout Response Schemas

Defines structured layout schemas for professional UI rendering,
inspired by Frappe's column/section break system.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class FieldType(str, Enum):
    """Supported field types for layout rendering."""

    TEXT = "text"
    HTML = "html"
    MARKDOWN = "markdown"
    GRAPH = "graph"
    TABLE = "table"
    METRIC = "metric"
    ALERT = "alert"
    DIVIDER = "divider"
    COLUMN_BREAK = "column_break"
    SECTION_BREAK = "section_break"


class GraphType(str, Enum):
    """Supported graph types for data visualization."""

    PIECHART = "piechart"
    BARCHART = "barchart"
    LINECHART = "linechart"
    AREACHART = "areachart"
    SCATTERCHART = "scatterchart"
    DONUTCHART = "donutchart"
    HISTOGRAM = "histogram"
    HEATMAP = "heatmap"


class AlertType(str, Enum):
    """Alert severity levels."""

    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class MetricData(BaseModel):
    """Metric display data."""

    value: Union[int, float, str]
    label: str
    unit: Optional[str] = None
    change: Optional[float] = None  # Percentage change
    trend: Optional[str] = Field(None, pattern="^(up|down|stable)$")
    color: Optional[str] = None


class GraphData(BaseModel):
    """Graph visualization data."""

    labels: List[str]
    datasets: List[Dict[str, Any]]
    options: Optional[Dict[str, Any]] = None


class TableData(BaseModel):
    """Table display data."""

    headers: List[str]
    rows: List[List[Any]]
    footer: Optional[List[str]] = None


class LayoutField(BaseModel):
    """Base layout field with type."""

    field_type: FieldType


class TextLayoutField(LayoutField):
    """Text content field."""

    field_type: FieldType = FieldType.TEXT
    content: str


class HTMLLayoutField(LayoutField):
    """HTML content field."""

    field_type: FieldType = FieldType.HTML
    content: str


class MarkdownLayoutField(LayoutField):
    """Markdown content field."""

    field_type: FieldType = FieldType.MARKDOWN
    content: str


class GraphLayoutField(LayoutField):
    """Graph visualization field."""

    field_type: FieldType = FieldType.GRAPH
    graph_type: GraphType
    title: Optional[str] = None
    data: GraphData


class TableLayoutField(LayoutField):
    """Table display field."""

    field_type: FieldType = FieldType.TABLE
    title: Optional[str] = None
    data: TableData


class MetricLayoutField(LayoutField):
    """Metric display field."""

    field_type: FieldType = FieldType.METRIC
    data: MetricData


class AlertLayoutField(LayoutField):
    """Alert message field."""

    field_type: FieldType = FieldType.ALERT
    alert_type: AlertType
    title: Optional[str] = None
    message: str


class DividerLayoutField(LayoutField):
    """Visual divider/separator."""

    field_type: FieldType = FieldType.DIVIDER


class ColumnBreakLayoutField(LayoutField):
    """Column break for layout control."""

    field_type: FieldType = FieldType.COLUMN_BREAK


class SectionBreakLayoutField(LayoutField):
    """Section break with optional title."""

    field_type: FieldType = FieldType.SECTION_BREAK
    title: Optional[str] = None
    description: Optional[str] = None


class ChatResponse(BaseModel):
    """Structured chat response with layout fields."""

    layout: List[
        Union[
            TextLayoutField,
            HTMLLayoutField,
            MarkdownLayoutField,
            GraphLayoutField,
            TableLayoutField,
            MetricLayoutField,
            AlertLayoutField,
            DividerLayoutField,
            ColumnBreakLayoutField,
            SectionBreakLayoutField,
        ]
    ]
    metadata: Optional[Dict[str, Any]] = None


class ChatRequest(BaseModel):
    """Chat request structure."""

    query: str
    context: Optional[Dict[str, Any]] = None
    format_preference: Optional[str] = "auto"  # auto, text, visual, detailed
    include_charts: bool = True
    include_tables: bool = True
    max_fields: int = Field(20, ge=1, le=50)
