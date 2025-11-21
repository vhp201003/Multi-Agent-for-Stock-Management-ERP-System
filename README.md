# Multi-Agent Stock Management ERP System

Hệ thống ERP quản lý kho bằng kiến trúc multi-agent với giao tiếp async qua Redis pub/sub, tích hợp MCP (Model Context Protocol) và AI agents.

## Kiến trúc Hệ thống

### Agent Architecture
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ OrchestratorAgent│    │   WorkerAgents  │    │   ChatAgent     │
│ - Query parsing │    │ - InventoryAgent│    │ - UI Generation │
│ - Task decomp.  │    │ - ForecastAgent │    │ - Final response│
│ - Coordination  │    │ - OrderingAgent │    │ - Layout render │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                        │                        │
         └────────────────────────┼────────────────────────┘
                                  │
                        ┌─────────────────┐
                        │  Redis Pub/Sub  │
                        │ - Event routing │ 
                        │ - State sync    │
                        │ - Task queuing  │
                        └─────────────────┘
```

### Manager Layer
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ BaseManager     │    │InventoryManager │    │   ChatManager   │
│ - Queue mgmt    │    │ - Inventory flow│    │ - Response flow │
│ - Dependency    │    │ - Task dispatch │    │ - Final trigger │
│ - Task routing  │    │ - Status track  │    │ - UI generation │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Redis Channel Communication

### Core Channels
```python
# Query Distribution
QUERY_CHANNEL = "agent:query_channel"

# Agent Commands  
COMMAND_CHANNEL = "agent:command_channel:{agent_type}"

# Task Updates
TASK_UPDATES = "agent:task_updates:{agent_type}"

# Completion Notifications
QUERY_COMPLETION = "query:completion:{query_id}"
```

### Message Flow Patterns
```
User Query → OrchestratorAgent → Managers → WorkerAgents → ChatAgent → Response
     ↓              ↓              ↓           ↓            ↓
   Parse      →  Decompose   →  Queue    →  Execute   →  Generate
     ↓              ↓              ↓           ↓            ↓
  Validate    → Dependencies → Dispatch  → MCP Tools → UI Layout
```

## Complete Workflow

### 1. Query Processing Pipeline
```python
# User submits query
POST /query {"query": "Check inventory for Product A and create purchase order"}

# OrchestratorAgent decomposes
{
  "agents_needed": ["inventory", "forecasting", "ordering"],
  "task_dependency": {
    "inventory": {"tasks": [...], "dependencies": []},
    "forecasting": {"tasks": [...], "dependencies": []}, 
    "ordering": {"tasks": [...], "dependencies": ["inventory", "forecasting"]}
  }
}
```

### 2. Event-Driven Task Execution
```python
# Manager receives query → checks dependencies → queues tasks
if dependencies_satisfied:
    queue_key = RedisKeys.get_agent_queue(agent_type)
else:
    queue_key = RedisKeys.get_agent_pending_queue(agent_type)

# Agent receives command → processes → broadcasts completion
await redis.publish(
    RedisChannels.get_task_updates_channel(agent_type),
    task_completion_message
)
```

### 3. Dependency Resolution
```python
# OrchestratorAgent tracks completion
if all_dependencies_done:
    # Move from pending → active queue
    # Trigger next dependent tasks
    await check_and_trigger_next(query_id)
```

## Key Features

### Multi-Agent Coordination
- **Event-driven architecture**: No polling loops, pure reactive
- **Dependency management**: DAG-based task dependencies
- **Atomic operations**: Redis transactions for shared state
- **Error recovery**: Graceful failure handling and retries

### MCP Integration
- **Tool execution**: Inventory, forecasting, ordering tools
- **Resource access**: Database queries, external APIs
- **Schema validation**: Type-safe tool parameters
- **Async operations**: Non-blocking MCP client connections

### Advanced State Management
```python
# SharedData with task graph
class SharedData(BaseModel):
    agents_needed: List[str]
    agents_done: List[str] 
    task_graph: TaskDependencyGraph
    results: Dict[str, Dict[str, Any]]
    context: Dict[str, Dict[str, Any]]
    status: str
```

### UI Generation
- **Layout-based responses**: Structured UI components
- **Data visualization**: Charts, tables, metrics
- **Responsive design**: Column layouts, sections
- **Real-time updates**: Live progress tracking

## Setup & Development

### Prerequisites
```bash
# Install uv package manager
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Node.js (for frontend)
# Visit https://nodejs.org/ or use nvm
```

### Environment Configuration

The system uses `.env` files for configuration management. **Never commit `.env` files to version control!**

#### Backend Configuration

1. **Copy the example file**:
   ```bash
   cp .env.example .env
   ```

2. **Edit `.env` with your configuration**:
   ```bash
   # Server Configuration
   HOST=0.0.0.0
   PORT=8010
   RELOAD=true
   LOG_LEVEL=info
   
   # CORS Origins (comma-separated)
   CORS_ORIGINS=http://localhost:5173,http://localhost:5174
   
   # Redis Configuration
   REDIS_HOST=localhost
   REDIS_PORT=6379
   
   # ERPNext Configuration
   ERPNEXT_URL=http://erp.localhost:8000
   ERPNEXT_API_KEY=your_api_key_here
   ERPNEXT_API_SECRET=your_api_secret_here
   
   # MCP Server Ports
   INVENTORY_SERVER_PORT=8011
   ANALYTICS_SERVER_PORT=8012
   
   # Warehouse Settings
   DEFAULT_WAREHOUSE=Main Warehouse
   LOW_STOCK_THRESHOLD=10
   CRITICAL_STOCK_THRESHOLD=5
   
   # Analytics Settings
   DEFAULT_LOOKBACK_DAYS=30
   DEFAULT_TOP_N=10
   PARETO_CUTOFF=0.8
   
   # Profile Configuration
   CONFIG_PROFILE=default
   ```

#### Frontend Configuration

1. **Navigate to frontend directory**:
   ```bash
   cd frontend
   ```

2. **Copy the example file**:
   ```bash
   cp .env.example .env
   ```

3. **Edit `frontend/.env` with your configuration**:
   ```bash
   # Backend API Configuration
   VITE_API_BASE_URL=http://localhost:8010
   VITE_WS_BASE_URL=ws://localhost:8010
   ```

#### Environment Variables Reference

**Backend Variables:**

| Variable | Description | Default |
|----------|-------------|---------|
| `HOST` | Server host address | `0.0.0.0` |
| `PORT` | Server port | `8010` |
| `RELOAD` | Enable auto-reload in development | `true` |
| `LOG_LEVEL` | Logging level (debug, info, warning, error) | `info` |
| `CORS_ORIGINS` | Comma-separated allowed CORS origins | `http://localhost:5173,http://localhost:5174` |
| `REDIS_HOST` | Redis server host | `localhost` |
| `REDIS_PORT` | Redis server port | `6379` |
| `GROQ_API_KEY` | Groq API key for LLM (shared by all agents) | *(required)* |
| `ERPNEXT_URL` | ERPNext instance URL | `http://localhost:8001` |
| `ERPNEXT_API_KEY` | ERPNext API key | *(required)* |
| `ERPNEXT_API_SECRET` | ERPNext API secret | *(required)* |
| `INVENTORY_SERVER_PORT` | Inventory MCP server port | `8011` |
| `ANALYTICS_SERVER_PORT` | Analytics MCP server port | `8012` |
| `DEFAULT_WAREHOUSE` | Default warehouse name | `Main Warehouse` |
| `LOW_STOCK_THRESHOLD` | Low stock alert threshold | `10` |
| `CRITICAL_STOCK_THRESHOLD` | Critical stock alert threshold | `5` |
| `DEFAULT_LOOKBACK_DAYS` | Default analytics lookback period | `30` |
| `DEFAULT_TOP_N` | Default top N items in analytics | `10` |
| `PARETO_CUTOFF` | Pareto analysis cutoff percentage | `0.8` |
| `CONFIG_PROFILE` | Configuration profile to use | `default` |

**Frontend Variables:**

| Variable | Description | Default |
|----------|-------------|---------|
| `VITE_API_BASE_URL` | Backend API base URL (HTTP) | `http://localhost:8010` |
| `VITE_WS_BASE_URL` | Backend WebSocket base URL | `ws://localhost:8010` |

### Infrastructure
```yaml
# docker-compose.yml
services:
  redis:    # Pub/sub messaging
  postgres: # Data storage  
  qdrant:   # Vector database
```

### Installation
```bash
# 1. Start infrastructure
docker-compose up -d

# 2. Install dependencies
uv sync

# 3. Run application
./scripts/run.sh

# 4. Test system
curl -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{"query": "Check inventory levels and forecast demand"}'
```

## System Monitoring

### Redis Key Patterns
```python
# Agent status tracking
"agent:status" → hash of {agent_type: status}

# Task queues
"agent:queue:{agent_type}" → list of pending tasks
"agent:pending_queue:{agent_type}" → list of blocked tasks

# Shared state
"agent:shared_data:{query_id}" → JSON document

# Conversations
"conversation:{conversation_id}" → message history
```

### Performance Metrics
- **Concurrent processing**: Multiple agents work in parallel
- **Dependency optimization**: Tasks execute as soon as dependencies ready
- **Memory efficiency**: Streaming operations, bounded queues
- **Fault tolerance**: Redis persistence, agent restart capability

## Testing

### Core Test Suites
```bash
# Event-driven manager tests
python tests/test_event_driven_manager.py

# Complete multi-agent flow
python tests/test_complete_multi_agent_flow.py  

# Task lifecycle integration
python tests/run_lifecycle_test.py

# Redis pub/sub functionality  
python tests/redis_test.py
```

### Load Testing
```python
# High concurrency simulation
async def stress_test():
    # 100 concurrent queries
    # Cross-agent dependencies  
    # Performance monitoring
```

## Project Structure

```
src/
├── agents/          # Agent implementations
│   ├── base_agent.py       # Abstract agent interface
│   ├── orchestrator_agent.py  # Query coordination
│   ├── worker_agent.py     # Task execution base
│   ├── inventory_agent.py  # Inventory operations
│   └── chat_agent.py       # UI generation
├── managers/        # Task management layer
│   └── base_manager.py     # Queue & dependency management
├── mcp/            # Model Context Protocol
│   ├── client/     # MCP client implementations
│   └── server/     # MCP server implementations  
├── typing/         # Type definitions
│   ├── redis/      # Redis data models
│   ├── response/   # Response schemas
│   └── schema/     # Validation schemas
└── utils/          # Utility functions
```

## Advanced Features

### Security & Validation
- **Input sanitization**: All queries validated before processing
- **Schema enforcement**: Pydantic models for type safety
- **Access control**: Agent-specific channel permissions
- **Secret management**: Environment-based configuration

### Scalability Design
- **Horizontal scaling**: Multiple agent instances per type
- **Load balancing**: Redis-based task distribution
- **State persistence**: Durable shared data storage
- **Monitoring hooks**: Performance and health metrics

### AI Integration
- **LLM coordination**: Groq API for intelligent orchestration
- **Context management**: Conversation history and state
- **Prompt engineering**: Specialized prompts per agent type
- **Response optimization**: Structured output generation

## Use Cases

1. **Inventory Management**: Real-time stock checking and alerts
2. **Demand Forecasting**: AI-powered demand prediction
3. **Purchase Automation**: Intelligent order generation
4. **Report Generation**: Interactive dashboards and analytics
5. **Workflow Automation**: Complex multi-step business processes

Hệ thống được thiết kế để scale và mở rộng với các agent mới, workflow phức tạp, và tích hợp enterprise-grade.