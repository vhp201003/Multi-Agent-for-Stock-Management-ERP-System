"""
LLM Response Schema Classes

Detailed schema classes with descriptions for LLM to understand and generate proper responses.
Separate from actual data models used in application logic.
"""

from typing import List, Literal, Optional, Union

from pydantic import BaseModel, Field


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
    """Section break field for creating new sections with titles."""

    field_type: Literal["section_break"] = Field(
        default="section_break", description="Must be 'section_break'"
    )
    title: str = Field(..., description="Title of the section (required)")
    description: Optional[str] = Field(
        None, description="Optional description for the section"
    )


class LLMMarkdownField(LLMLayoutField):
    """Markdown field for all text content, metrics, and formatted text."""

    field_type: Literal["markdown"] = Field(default="markdown", description="Must be 'markdown'")
    content: str = Field(
        ...,
        description="Markdown content with formatting. Use **bold**, *italic*, ## headers, - lists. Include metrics like **Revenue**: $150K (+15%)",
    )


class LLMGraphField(LLMLayoutField):
    """Graph field for data visualization when charts help understanding."""

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
    """Table field for structured data when comparison is needed."""

    field_type: Literal["table"] = Field(default="table", description="Must be 'table'")
    title: Optional[str] = Field(None, description="Optional title for the table")
    data: dict = Field(
        ..., description="Table data with 'headers' array and 'rows' array of arrays"
    )


class LLMColumnBreakField(LLMLayoutField):
    """Column break field for organizing layout into columns."""

    field_type: Literal["column_break"] = Field(
        default="column_break", description="Must be 'column_break'"
    )


class ChatAgentSchema(BaseModel):
    """Complete chat response schema for LLM with detailed field descriptions."""

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
