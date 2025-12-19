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
    console.log(`[extractTableData] Starting extraction:`, {
      agent_type: dataSource.agent_type,
      tool_name: dataSource.tool_name,
      columns: dataSource.columns,
      headers: dataSource.headers,
    });

    // Step 1: Locate agent data & tool result (reuse logic pattern)
    if (!fullData || typeof fullData !== 'object') {
        console.warn("[extractTableData] fullData is invalid or empty", { fullData });
        return null;
    }

    console.log(`[extractTableData] fullData keys:`, Object.keys(fullData as Record<string, unknown>));

    const agentData = (fullData as Record<string, unknown>)[dataSource.agent_type];
    if (!agentData || typeof agentData !== 'object') {
        console.warn(`[extractTableData] Agent '${dataSource.agent_type}' not found in fullData`, {
          availableAgents: Object.keys(fullData as Record<string, unknown>),
          requestedAgent: dataSource.agent_type
        });
        return null;
    }

    console.log(`[extractTableData] Found agent data, keys:`, Object.keys(agentData as Record<string, unknown>));

    let toolResult: unknown = null;

    // 1. Try direct access (fast path)
    if (dataSource.tool_name in agentData) {
        toolResult = (agentData as Record<string, unknown>)[dataSource.tool_name];
        console.log(`[extractTableData] ✓ Found direct tool result for '${dataSource.tool_name}'`);
    }

    // 2. Fallback: Search through task results
    if (!toolResult) {
        console.log(`[extractTableData] Tool '${dataSource.tool_name}' not found in direct path, searching task results...`);
        for (const taskId in agentData) {
        const taskData = (agentData as Record<string, unknown>)[taskId];
        if (taskData && typeof taskData === 'object' && 'tool_results' in taskData) {
            const toolResults = (taskData as { tool_results?: unknown[] }).tool_results;
            if (Array.isArray(toolResults)) {
            console.log(`[extractTableData] Checking task ${taskId} tool results:`, toolResults.map((t: any) => t?.tool_name));
            const foundTool = toolResults.find(
                (tr: unknown) =>
                tr && typeof tr === 'object' && 'tool_name' in tr &&
                (tr as { tool_name: string }).tool_name === dataSource.tool_name
            );
            if (foundTool && typeof foundTool === 'object' && 'tool_result' in foundTool) {
                toolResult = (foundTool as { tool_result: unknown }).tool_result;
                console.log(`[extractTableData] ✓ Found tool in task ${taskId}`);
                break;
            }
            }
        }
        }
    }

    if (!toolResult) {
        console.warn(`[extractTableData] ✗ Tool '${dataSource.tool_name}' not found anywhere`, {
          agent_type: dataSource.agent_type,
          agentKeys: Object.keys(agentData as Record<string, unknown>)
        });
        return null;
    }

    console.log(`[extractTableData] Tool result structure:`, {
      isArray: Array.isArray(toolResult),
      keys: typeof toolResult === 'object' && toolResult !== null ? Object.keys(toolResult as Record<string, unknown>) : 'N/A',
      toolResult: toolResult
    });

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

    console.log(`[extractTableData] Looking for array data (dataPath: ${dataPath || 'auto-detect'})...`);

    if (dataPath) {
        rawData = navigatePath(toolResult, dataPath);
        const arrayLen = Array.isArray(rawData) ? (rawData as unknown[]).length : 0;
        console.log(`[extractTableData] Using explicit dataPath '${dataPath}':`, Array.isArray(rawData) ? `✓ Found array (${arrayLen} items)` : `✗ Not an array`);
    } else {
        // Try common paths
        const paths = ['data', 'items', 'result'];
        console.log(`[extractTableData] Auto-detecting data path from: ${paths.join(', ')}`);
        for (const p of paths) {
            rawData = navigatePath(toolResult, p);
            const arrayLen = Array.isArray(rawData) ? (rawData as unknown[]).length : 0;
            console.log(`[extractTableData] Trying path '${p}':`, Array.isArray(rawData) ? `✓ Is array (${arrayLen} items)` : `✗ Not an array`);
            if (Array.isArray(rawData) && rawData.length > 0) {
                dataPath = p;
                console.log(`[extractTableData] ✓ Selected path: '${dataPath}'`);
                break;
            }
        }
        // If still not found, check if toolResult itself is array
        if (!rawData && Array.isArray(toolResult)) {
            rawData = toolResult;
            dataPath = '(root)';
            const arrayLen = (rawData as unknown[]).length;
            console.log(`[extractTableData] ✓ Using toolResult as array (${arrayLen} items)`);
        }
    }

    console.log(`[extractTableData] After path resolution:`, {
      dataPath,
      isArray: Array.isArray(rawData),
      length: Array.isArray(rawData) ? (rawData as unknown[]).length : 'N/A'
    });

    if (!Array.isArray(rawData) || rawData.length === 0) {
      // Logic for single object -> single row
      if (rawData && typeof rawData === 'object') {
          console.log(`[extractTableData] Single object detected, converting to single-row array`);
          rawData = [rawData];
      } else {
         console.warn(`[extractTableData] ✗ No array/object data found`, {
           checkedPaths: dataPath || 'data, items, result',
           toolResult: toolResult
         });
         return null;
      }
    }

    // Check for _truncated marker to get total count
    const rawDataArray = rawData as unknown[];
    const lastItem = rawDataArray[rawDataArray.length - 1];
    if (lastItem && typeof lastItem === 'object' && '_truncated' in lastItem && (lastItem as Record<string, unknown>).total_items) {
      totalItems = (lastItem as Record<string, unknown>).total_items as number;
      // Remove the truncated marker from display data
      rawData = rawDataArray.filter((item: unknown) => !((item as Record<string, unknown>) && '_truncated' in (item as Record<string, unknown>)));
      console.log(`[extractTableData] Found truncated marker, total items: ${totalItems}, display items: ${(rawData as unknown[]).length}`);
    }

    // Step 3: Extract columns
    const extractedRows: string[][] = [];

    console.log(`[extractTableData] Extracting rows...`, {
      totalItems: (rawData as unknown[]).length,
      columns: dataSource.columns,
      hasHeaders: !!dataSource.headers
    });

    for (const item of (rawData as unknown[])) {
      if (!item || typeof item !== 'object') {
        console.warn(`[extractTableData] Skipping invalid item:`, item);
        continue;
      }

      const row: string[] = [];
      const itemObj = item as Record<string, unknown>;
      const columns = dataSource.columns || Object.keys(itemObj); // Fallback to all keys if no columns

      for (const colKey of columns) {
        let val = itemObj[colKey];
        // Handle nested objects or nulls gracefully
        if (val === null || val === undefined) val = "";
        else if (typeof val === 'object') val = JSON.stringify(val);
        row.push(String(val));
      }
      extractedRows.push(row);
    }

    console.log(`[extractTableData] ✓ Extracted ${extractedRows.length} rows`, {
      headers: dataSource.headers || dataSource.columns,
      firstRow: extractedRows[0] || 'N/A'
    });

    if (extractedRows.length === 0) {
      console.warn(`[extractTableData] ✗ No valid rows extracted`);
      return null;
    }

    const result = {
      headers: dataSource.headers || dataSource.columns,
      rows: extractedRows,
      totalItems: totalItems
    };

    console.log(`[extractTableData] ✓ SUCCESS`, result);
    return result;

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
