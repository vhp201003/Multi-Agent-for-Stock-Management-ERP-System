/**
 * Chart Data Extractor - Extract chart data from data_source specification
 * 
 * Matches backend logic: Navigate full_data using data_source config
 */

interface ChartDataSource {
  agent_type: string;
  tool_name: string;
  label_field: string;
  value_field: string;
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
    // Backend structure: {agent_type: {task_id: {tool_results: [...]}}}
    let toolResult: unknown = null;
    
    // Search through task results
    for (const taskId in agentData) {
      const taskData = (agentData as Record<string, unknown>)[taskId];
      
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
    }

    if (!toolResult) {
      console.warn(`Tool ${dataSource.tool_name} not found in ${dataSource.agent_type}`);
      return null;
    }

    // Step 3: Navigate to data array using data_path
    const dataPath = dataSource.data_path || 'data';
    const rawData = navigatePath(toolResult, dataPath);

    if (!Array.isArray(rawData) || rawData.length === 0) {
      console.warn(`No array data found at path: ${dataPath}`, toolResult);
      return null;
    }

    // Step 4: Extract labels and values
    const labels: string[] = [];
    const values: number[] = [];

    for (const item of rawData) {
      if (!item || typeof item !== 'object') continue;

      const labelValue = item[dataSource.label_field];
      const valueValue = item[dataSource.value_field];

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
    const valueFieldLabel = dataSource.value_field
      .replace(/_/g, ' ')
      .replace(/\b\w/g, c => c.toUpperCase());

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
 * Get max data points recommended for each chart type
 */
function getMaxPointsForChartType(graphType: string): number {
  const limits: Record<string, number> = {
    piechart: 8,   // Too many slices are hard to read
    barchart: 15,  // Balance visibility and detail
    linechart: 50, // Can handle more points for trends
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
    }

    return field;
  });
}
