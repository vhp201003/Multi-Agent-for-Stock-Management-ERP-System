from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class FieldType(str, Enum):
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
    PIECHART = "piechart"
    BARCHART = "barchart"
    LINECHART = "linechart"
    AREACHART = "areachart"
    SCATTERCHART = "scatterchart"
    DONUTCHART = "donutchart"
    HISTOGRAM = "histogram"
    HEATMAP = "heatmap"


class AlertType(str, Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class MetricData(BaseModel):
    value: Union[int, float, str]
    label: str
    unit: Optional[str] = None
    change: Optional[float] = None  # Percentage change
    trend: Optional[str] = Field(None, pattern="^(up|down|stable)$")
    color: Optional[str] = None


class GraphData(BaseModel):
    labels: List[str]
    datasets: List[Dict[str, Any]]
    options: Optional[Dict[str, Any]] = None


class TableData(BaseModel):
    headers: List[str]
    rows: List[List[Any]]
    footer: Optional[List[str]] = None


class LayoutField(BaseModel):
    field_type: FieldType


class TextLayoutField(LayoutField):
    field_type: FieldType = FieldType.TEXT
    content: str


class HTMLLayoutField(LayoutField):
    field_type: FieldType = FieldType.HTML
    content: str


class MarkdownLayoutField(LayoutField):
    field_type: FieldType = FieldType.MARKDOWN
    content: str


class GraphLayoutField(LayoutField):
    field_type: FieldType = FieldType.GRAPH
    graph_type: GraphType
    title: Optional[str] = None
    data: GraphData


class TableLayoutField(LayoutField):
    field_type: FieldType = FieldType.TABLE
    title: Optional[str] = None
    data: TableData


class MetricLayoutField(LayoutField):
    field_type: FieldType = FieldType.METRIC
    data: MetricData


class AlertLayoutField(LayoutField):
    field_type: FieldType = FieldType.ALERT
    alert_type: AlertType
    title: Optional[str] = None
    message: str


class DividerLayoutField(LayoutField):
    field_type: FieldType = FieldType.DIVIDER


class ColumnBreakLayoutField(LayoutField):
    field_type: FieldType = FieldType.COLUMN_BREAK


class SectionBreakLayoutField(LayoutField):
    field_type: FieldType = FieldType.SECTION_BREAK
    title: Optional[str] = None
    description: Optional[str] = None


class ChatResponse(BaseModel):
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
    llm_usage: Optional[Dict[str, Any]] = None
    llm_reasoning: Optional[str] = None


class ChatRequest(BaseModel):
    query: str
    context: Optional[Dict[str, Any]] = None
    format_preference: Optional[str] = "auto"  # auto, text, visual, detailed
    include_charts: bool = True
    include_tables: bool = True
    max_fields: int = Field(20, ge=1, le=50)
