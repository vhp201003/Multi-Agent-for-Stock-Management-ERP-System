/**
 * Chart Data Extractor - Extract chart data from data_source specification
 * 
 * Matches backend logic: Navigate full_data using data_source config
 */

/**
 * Chart Data Source - Matches backend schemas
 *
 * Chart Type Field Mapping:
 * - barchart/horizontalbarchart: category_field (label), value_field (value)
 * - linechart: x_field (label), y_field (value)
 * - piechart: label_field (label), value_field (value)
 * - scatterplot: x_field, y_field, name_field (optional), group_field (optional)
 */
interface ChartDataSource {
  agent_type: string;
  tool_name: string;
  chart_type?: string;
  data_path?: string;

  // Field names (vary by chart type)
  label_field?: string;      // piechart
  value_field?: string;      // piechart, barchart, horizontalbarchart
  category_field?: string;   // barchart, horizontalbarchart
  x_field?: string;          // linechart, scatterplot
  y_field?: string;          // linechart, scatterplot
  name_field?: string;       // scatterplot (point labels/tooltips)
  group_field?: string;      // scatterplot (grouping/coloring)
}

interface TableDataSource {
  agent_type: string;
  tool_name: string;
  columns: string[];
  headers?: string[];
  data_path?: string;
}

interface ChartData {
  labels: string[];
  datasets: Array<{
    label: string;
    data: number[];
    borderColor?: string;
    backgroundColor?: string;
    fill?: boolean;
  }>;
}

/**
 * Navigate nested object using dot notation (e.g., 'data.items')
 */
function navigatePath(obj: unknown, path: string): unknown {
  if (!path) return obj;
  
  const parts = path.split('.');
  let current: unknown = obj;
  
  for (const part of parts) {
    if (current && typeof current === 'object' && part in current) {
      current = (current as Record<string, unknown>)[part];
    } else {
      return null;
    }
  }
  
  return current;
}

/**
 * Extract chart data from full_data using data_source specification
 */
export function extractChartData(
  fullData: unknown,
  dataSource: ChartDataSource,
  graphType: string
): ChartData | null {
  try {
    // Step 1: Locate agent data
    if (!fullData || typeof fullData !== 'object') {
      console.warn('Invalid full_data:', fullData);
      return null;
    }

    const agentData = (fullData as Record<string, unknown>)[dataSource.agent_type];
    if (!agentData || typeof agentData !== 'object') {
      console.warn(`Agent ${dataSource.agent_type} not found in full_data`);
      return null;
    }

    // Step 2: Find tool result
    // Backend structure: {agent_type: {tool_name: result, task_id: {tool_results: [...]}}}
    let toolResult: unknown = null;

    // 1. Try direct access (fast path) - populated by backend extract_tool_results_to_dict
    if (dataSource.tool_name in agentData) {
        toolResult = (agentData as Record<string, unknown>)[dataSource.tool_name];
    }
    
    // 2. Fallback: Search through task results (slow path)
    if (!toolResult) {
      for (const taskId in agentData) {
        const taskData = (agentData as Record<string, unknown>)[taskId];
        
        // Skip consistency checks if we already match the key (unlikely if 'in' check failed, but safety)
        if (taskId === dataSource.tool_name) continue; 

      
        // Check tool_results array
        if (taskData && typeof taskData === 'object' && 'tool_results' in taskData) {
          const toolResults = (taskData as { tool_results?: unknown[] }).tool_results;
          if (Array.isArray(toolResults)) {
            const foundTool = toolResults.find(
              (tr: unknown) => 
                tr && 
                typeof tr === 'object' && 
                'tool_name' in tr && 
                (tr as { tool_name: string }).tool_name === dataSource.tool_name
            );
            
            if (foundTool && typeof foundTool === 'object' && 'tool_result' in foundTool) {
              toolResult = (foundTool as { tool_result: unknown }).tool_result;
              break;
            }
          }
        }
      } // Closing brace for `for (const taskId in agentData)`
    } // Closing brace for `if (!toolResult)`

    if (!toolResult) {
      console.warn(`Tool ${dataSource.tool_name} not found in ${dataSource.agent_type}`);
      return null;
    }

    // Step 3: Navigate to data array using data_path
    let dataPath = dataSource.data_path;
    let rawData: unknown = null;
    
    if (dataPath) {
        rawData = navigatePath(toolResult, dataPath);
    } else {
        // Try common paths
        const paths = ['data', 'items', 'result'];
        for (const p of paths) {
            rawData = navigatePath(toolResult, p);
            if (Array.isArray(rawData) && rawData.length > 0) {
                dataPath = p;
                break;
            }
        }
        // If still not found, check if toolResult itself is array
        if (!rawData && Array.isArray(toolResult)) {
            rawData = toolResult;
        }
    }

    if (!Array.isArray(rawData) || rawData.length === 0) {
      console.warn(`No array data found (checked paths: ${dataPath || 'data, items, result'})`, toolResult);
      return null;
    }

    // Step 4: Extract labels and values
    const labels: string[] = [];
    const values: number[] = [];

    // Handle different field names based on chart type
    // Chart Type → (Label Field, Value Field)
    // - barchart/horizontalbarchart → (category_field, value_field)
    // - linechart → (x_field, y_field)
    // - piechart → (label_field, value_field)
    // - scatterplot → (x_field, y_field) [name_field & group_field for advanced features]
    const dsAny = dataSource as any;
    const labelField =
      dsAny.x_field ||           // linechart, scatterplot
      dsAny.category_field ||    // barchart, horizontalbarchart
      dsAny.label_field ||       // piechart
      dataSource.label_field;    // fallback

    const valueField =
      dsAny.y_field ||           // linechart, scatterplot
      dsAny.value_field ||       // barchart, horizontalbarchart, piechart
      dataSource.value_field;    // fallback

    if (!labelField) {
        console.warn("[chartDataExtractor] No label field specified", {
          tried: ['x_field', 'category_field', 'label_field'],
          dataSource
        });
        return null;
    }

    if (!valueField) {
        console.warn("[chartDataExtractor] No value field specified", {
          tried: ['y_field', 'value_field'],
          dataSource
        });
        return null;
    }

    console.log(`[chartDataExtractor] Extracting ${graphType} data: label="${labelField}", value="${valueField}"`);

    for (const item of rawData) {
      if (!item || typeof item !== 'object') continue;

      const labelValue = item[labelField];
      const valueValue = item[valueField];

      if (labelValue === undefined || labelValue === null) continue;
      if (valueValue === undefined || valueValue === null) continue;

      // Convert to appropriate types
      const labelStr = String(labelValue);
      const valueNum = typeof valueValue === 'number'
        ? valueValue
        : parseFloat(String(valueValue));

      if (isNaN(valueNum)) continue;

      labels.push(labelStr);
      values.push(valueNum);
    }

    if (labels.length === 0 || values.length === 0) {
      console.warn('No valid label/value pairs extracted');
      return null;
    }

    // Step 5: Apply limits based on chart type
    const maxPoints = getMaxPointsForChartType(graphType);
    const limitedLabels = labels.slice(0, maxPoints);
    const limitedValues = values.slice(0, maxPoints);

    // Step 6: Return standardized format
    const valueFieldLabel = valueField
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (c: string) => c.toUpperCase());

    return {
      labels: limitedLabels,
      datasets: [
        {
          label: valueFieldLabel,
          data: limitedValues,
          borderColor: 'rgb(75, 192, 192)',
          backgroundColor: 'rgba(75, 192, 192, 0.2)',
          fill: graphType === 'linechart',
        },
      ],
    };
  } catch (error) {
    console.error('Chart data extraction failed:', error);
    return null;
  }
}

/**
 * Extract table data from full_data using data_source specification
 */
export function extractTableData(
  fullData: unknown,
  dataSource: TableDataSource
): { headers: string[]; rows: string[][]; totalItems?: number } | null {
  try {
    // Step 1: Locate agent data & tool result (reuse logic pattern)
    if (!fullData || typeof fullData !== 'object') {
        console.warn("[Frontend] Table Extraction: fullData invalid");
        return null;
    }

    const agentData = (fullData as Record<string, unknown>)[dataSource.agent_type];
    if (!agentData || typeof agentData !== 'object') {
        console.warn(`[Frontend] Table Extraction: Agent ${dataSource.agent_type} not found`);
        return null;
    }

    let toolResult: unknown = null;
    
    // 1. Try direct access (fast path)
    if (dataSource.tool_name in agentData) {
        toolResult = (agentData as Record<string, unknown>)[dataSource.tool_name];
        console.log(`[Frontend] Found direct tool result for ${dataSource.tool_name}`);
    }

    // 2. Fallback: Search through task results
    if (!toolResult) {
        for (const taskId in agentData) {
        const taskData = (agentData as Record<string, unknown>)[taskId];
        if (taskData && typeof taskData === 'object' && 'tool_results' in taskData) {
            const toolResults = (taskData as { tool_results?: unknown[] }).tool_results;
            if (Array.isArray(toolResults)) {
            console.log(`[Frontend] Checking tool results for task ${taskId}:`, toolResults.map((t: any) => t?.tool_name));
            const foundTool = toolResults.find(
                (tr: unknown) => 
                tr && typeof tr === 'object' && 'tool_name' in tr && 
                (tr as { tool_name: string }).tool_name === dataSource.tool_name
            );
            if (foundTool && typeof foundTool === 'object' && 'tool_result' in foundTool) {
                toolResult = (foundTool as { tool_result: unknown }).tool_result;
                break;
            }
            }
        }
        }
    }

    if (!toolResult) {
        console.warn(`[Frontend] Table Extraction: Tool ${dataSource.tool_name} not found`);
        return null;
    }

    console.log(`[Frontend] Found tool result for ${dataSource.tool_name}:`, toolResult);

    // Extract total items from summary if available
    let totalItems: number | undefined;
    if (toolResult && typeof toolResult === 'object') {
      const result = toolResult as Record<string, any>;
      // Check summary.total_items or summary.total_items_need_replenishment
      if (result.summary?.total_items) {
        totalItems = result.summary.total_items;
      } else if (result.summary?.total_items_need_replenishment) {
        totalItems = result.summary.total_items_need_replenishment;
      }
    }

    // Step 2: Navigate to data array
    let dataPath = dataSource.data_path;
    let rawData: unknown = null;
    
    if (dataPath) {
        rawData = navigatePath(toolResult, dataPath);
    } else {
        // Try common paths
        const paths = ['data', 'items', 'result'];
        for (const p of paths) {
            rawData = navigatePath(toolResult, p);
            if (Array.isArray(rawData) && rawData.length > 0) {
                dataPath = p;
                break;
            }
        }
        // If still not found, check if toolResult itself is array
        if (!rawData && Array.isArray(toolResult)) {
            rawData = toolResult;
        }
    }

    if (!Array.isArray(rawData) || rawData.length === 0) {
      // Logic for single object -> single row
      if (rawData && typeof rawData === 'object') {
          rawData = [rawData];
      } else {
         console.warn(`[Frontend] No array/object data found (checked paths: ${dataPath || 'data, items, result'})`, toolResult);
         return null;
      }
    }

    // Check for _truncated marker to get total count
    const lastItem = (rawData as any[])[(rawData as any[]).length - 1];
    if (lastItem && lastItem._truncated && lastItem.total_items) {
      totalItems = lastItem.total_items;
      // Remove the truncated marker from display data
      rawData = (rawData as any[]).filter((item: any) => !item._truncated);
    }

    // Step 3: Extract columns
    const extractedRows: string[][] = [];
    
    for (const item of (rawData as any[])) {
      if (!item || typeof item !== 'object') continue;
      
      const row: string[] = [];
      const columns = dataSource.columns || Object.keys(item); // Fallback to all keys if no columns
      
      for (const colKey of columns) {
        let val = item[colKey];
        // Handle nested objects or nulls gracefully
        if (val === null || val === undefined) val = "";
        else if (typeof val === 'object') val = JSON.stringify(val);
        row.push(String(val));
      }
      extractedRows.push(row);
    }

    if (extractedRows.length === 0) return null;

    return {
      headers: dataSource.headers || dataSource.columns,
      rows: extractedRows,
      totalItems: totalItems
    };

  } catch (error) {
    console.error('Table data extraction failed:', error);
    return null;
  }
}

/**
 * Get max data points recommended for each chart type
 */
function getMaxPointsForChartType(graphType: string): number {
  const limits: Record<string, number> = {
    piechart: 8,              // Too many slices are hard to read
    barchart: 15,             // Balance visibility and detail
    horizontalbarchart: 15,   // Same as barchart
    linechart: 50,            // Can handle more points for trends
    scatterplot: 100,         // Can show many points effectively
  };
  return limits[graphType] || 20;
}

/**
 * Process layout and fill chart data from full_data
 */
export function processLayoutWithData(
  layout: Record<string, unknown>[],
  fullData: unknown
): Record<string, unknown>[] {
  if (!layout || !Array.isArray(layout)) return layout;

  return layout.map(field => {
    // If it's a graph field with data_source but no data, extract it
    if (
      field.field_type === 'graph' &&
      field.data_source &&
      !field.data &&
      fullData
    ) {
      const extractedData = extractChartData(
        fullData,
        field.data_source as ChartDataSource,
        field.graph_type as string
      );

      if (extractedData) {
        return {
          ...field,
          data: extractedData,
        };
      }
      if (extractedData) {
        return {
          ...field,
          data: extractedData,
        };
      }
    }

    // Table Handling
    if (
      field.field_type === 'table' &&
      field.data_source &&
      !field.data &&
      fullData
    ) {
      console.log(`[Frontend] Processing Table field: ${field.title}`, field.data_source);
      const extractedData = extractTableData(
        fullData,
        field.data_source as TableDataSource
      );
      
      console.log(`[Frontend] Extracted Table Data:`, extractedData);

      if (extractedData) {
        return {
          ...field,
          data: extractedData,
        };
      }
    }

    return field;
  });
}
