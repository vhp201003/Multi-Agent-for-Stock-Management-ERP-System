from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from .base_schema import BaseSchema


class LLMLayoutField(BaseModel):
    field_type: Literal[
        "section_break",
        "markdown",
        "graph",
        "table",
        "column_break",
    ] = Field(
        ...,
        description="Type of layout field: 'section_break', 'markdown', 'graph', 'table', or 'column_break'",
    )


class LLMSectionBreakField(LLMLayoutField):
    field_type: Literal["section_break"] = Field(
        default="section_break", description="Must be 'section_break'"
    )
    title: str = Field(..., description="Title of the section (required)")
    description: Optional[str] = Field(
        None, description="Optional description for the section"
    )


class LLMMarkdownField(LLMLayoutField):
    field_type: Literal["markdown"] = Field(
        default="markdown", description="Must be 'markdown'"
    )
    content: str = Field(
        ...,
        description="Markdown content with formatting. Use **bold**, *italic*, ## headers, - lists. Include metrics like **Revenue**: $150K (+15%)",
    )


class LLMGraphField(LLMLayoutField):
    field_type: Literal["graph"] = Field(default="graph", description="Must be 'graph'")
    graph_type: Literal["piechart", "barchart", "linechart"] = Field(
        ...,
        description="Chart type: 'piechart' for percentages, 'barchart' for comparisons, 'linechart' for trends",
    )
    title: Optional[str] = Field(None, description="Optional title for the chart")
    data: dict = Field(
        ...,
        description="Chart data with 'labels' array and 'datasets' array containing data points",
    )


class LLMTableField(LLMLayoutField):
    field_type: Literal["table"] = Field(default="table", description="Must be 'table'")
    title: Optional[str] = Field(None, description="Optional title for the table")
    data: dict = Field(
        ..., description="Table data with 'headers' array and 'rows' array of arrays"
    )


class LLMColumnBreakField(LLMLayoutField):
    field_type: Literal["column_break"] = Field(
        default="column_break", description="Must be 'column_break'"
    )


class ChatAgentSchema(BaseSchema):
    layout: List[
        Union[
            LLMSectionBreakField,
            LLMMarkdownField,
            LLMGraphField,
            LLMTableField,
            LLMColumnBreakField,
        ]
    ] = Field(
        ...,
        description="Array of layout fields. Start with section_break for title, use markdown for content/metrics, add graph/table when data visualization helps, use column_break to organize layout. YOU decide when graphs/tables are needed.",
    )
    full_data: Optional[Dict[str, Any]] = Field(
        None,
        description="Complete unfiltered data from all agents for UI consumption",
    )
