# Three-Tier Agent System (Coordinator/Distributor/Worker)

A POC (Proof of Concept) implementation of a hierarchical multi-agent system using LangGraph, Redis, and Agent-to-Agent (A2A) peer-to-peer messaging.

## Overview

This system implements a three-tier agent architecture:

```
┌─────────────────────────────────────────────────────┐
│            COORDINATOR (Level 1)                    │
│  - High-level task assignment                      │
│  - Distributor monitoring                          │
│  - Shared state management with Redis              │
└─────────────────┬───────────────────────────────────┘
                  │ A2A P2P + Redis Shared State
┌─────────────────▼───────────────────────────────────┐
│            DISTRIBUTOR (Level 2)                   │
│  - Receives tasks from Coordinator                 │
│  - Distributes work to Workers                     │
│  - Worker lifecycle management                     │
│  - Shared state sync with Coordinator              │
└────────┬─────────────────────┬──────────────────────┘
         │ A2A P2P             │ A2A P2P
┌────────▼──────┐      ┌───────▼──────┐
│   WORKER-1    │      │   WORKER-N   │
│  - Execute    │      │  - Execute   │
│    tasks      │      │    tasks     │
│  - Local      │      │  - Local     │
│    state      │      │    state     │
└───────────────┘      └──────────────┘
```

## Key Features

### 1. **LangGraph State Management**
- Each agent maintains its own `LocalAgentState` for runtime data, memory, and local decisions
- Per-agent state includes: metadata, local tasks, heartbeat, local variables, and history
- Implements task lifecycle: PENDING → IN_PROGRESS → COMPLETED (or FAILED)

### 2. **Redis Shared State (Coordinator ↔ Distributor)**
- Shared state stored at: `shared:distributor:{distributor_id}`
- Includes: versions, status, assigned workers, tasks list, and lease information
- Optimistic concurrency control with version tracking
- Distributed lease pattern for conflict-free updates
- Pub/sub notifications for state change propagation

### 3. **Agent-to-Agent (A2A) P2P Messaging**
- **Coordinator ↔ Distributor**: A2A messaging for task assignment and coordination
- **Distributor ↔ Worker**: A2A messaging for work distribution
- Message types: REQUEST, RESPONSE, HEARTBEAT, EVENT, ACK, ERROR
- All messages signed with HMAC-SHA256 for authentication
- Causal metadata tracking (origin, version, timestamp, request_id, sequence_number)

### 4. **Concurrency & Consistency**
- Optimistic concurrency with version tracking
- Redis WATCH/MULTI/EXEC transactions for atomic updates
- Distributed lock pattern using lease keys with TTL
- Lease renewal mechanism for long-running operations

### 5. **Monitoring & Health**
- Heartbeat messages from Workers and Distributors
- Timeout detection and automatic recovery
- State reconciliation on heartbeat failures
- History logging for audit trail

## Project Structure

```
agent-system/
├── core/
│   ├── __init__.py
│   ├── redis_client.py         # Redis integration with pub/sub
│   ├── a2a_messaging.py        # P2P messaging system
│   └── langgraph_state.py      # LangGraph state models
├── coordinator/
│   ├── __init__.py
│   └── agent.py                # Coordinator agent implementation
├── distributor/
│   ├── __init__.py
│   └── agent.py                # Distributor agent implementation
├── worker/
│   ├── __init__.py
│   └── agent.py                # Worker agent implementation
├── tests/
│   ├── __init__.py
│   ├── test_core.py            # Unit tests
│   └── test_integration_a2a.py # A2A and Redis integration tests
├── example_e2e.py              # End-to-end example
├── requirements.txt            # Python dependencies
├── pyproject.toml              # Project configuration
├── .env.example                # Configuration template
├── .gitignore
└── README.md                   # This file
```

## Installation

### Prerequisites
- Python 3.11+
- Redis server (local or remote)
- pip or poetry

### Setup

1. **Clone/setup the project**
```bash
cd agent-system
```

2. **Create virtual environment**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Configure environment**
```bash
cp .env.example .env
# Edit .env with your Redis connection details
```

5. **Start Redis**
```bash
# Using Docker
docker run -d -p 6379:6379 redis:latest

# Or using local Redis installation
redis-server
```

## Configuration

### Redis Configuration (.env)
```
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=
REDIS_USE_TLS=false
```

### Agent Configuration (.env)
```
COORDINATOR_ID=coordinator-1
DISTRIBUTOR_ID=distributor-1
WORKER_ID=worker-1
```

### A2A Messaging Configuration
```
A2A_USE_MTLS=false
A2A_CERT_PATH=/path/to/cert.pem
A2A_KEY_PATH=/path/to/key.pem
A2A_TOKEN_SECRET=your-secret-token
```

## Usage

### Running the End-to-End Example

```bash
python example_e2e.py
```

This will:
1. Initialize Coordinator, Distributor, and 2 Workers
2. Coordinator assigns tasks to Distributor
3. Distributor distributes tasks to Workers
4. Workers execute tasks and report results
5. Shared state is updated in Redis and synchronized

### Using in Your Code

```python
from core import RedisConfig, A2AConfig
from coordinator.agent import CoordinatorAgent
from distributor.agent import DistributorAgent
from worker.agent import WorkerAgent

# Create Redis config
redis_config = RedisConfig(host="localhost", port=6379)

# Create Coordinator
coordinator = CoordinatorAgent(
    agent_id="coordinator-1",
    redis_config=redis_config,
    a2a_config=A2AConfig(agent_id="coordinator-1")
)

# Initialize
coordinator.initialize()

# Create and assign task
from core import Task
task = Task(
    task_id="task-1",
    task_type="compute",
    payload={"operation": "sum"}
)
coordinator.assign_task_to_distributor(task, "distributor-1")
```

## State Models

### LocalAgentState (Per-Agent)
```python
{
    "agent_id": "coordinator-1",
    "status": "idle|busy|error|recovering",
    "local_tasks": [Task, ...],
    "last_heartbeat": "2025-11-28T10:30:00",
    "local_vars": {key: value, ...},
    "history": [event, ...],
    "metadata": {key: value, ...},
    "created_at": "2025-11-28T10:00:00",
    "updated_at": "2025-11-28T10:30:00"
}
```

### SharedAgentState (Coordinator ↔ Distributor in Redis)
```json
{
    "coordinator_version": "v1",
    "distributor_version": "v1",
    "status": "idle|busy|error",
    "assigned_workers": ["worker-1", "worker-2"],
    "tasks": [
        {
            "task_id": "task-1",
            "task_type": "compute",
            "payload": {...},
            "status": "completed",
            "updated_at": "2025-11-28T10:30:00"
        }
    ],
    "lease": {
        "owner": "coordinator|distributor",
        "acquired_at": "2025-11-28T10:25:00",
        "expires_at": "2025-11-28T10:35:00"
    }
}
```

### Task Model
```python
{
    "task_id": "task-1",
    "task_type": "compute|data_processing|...",
    "payload": {any: data},
    "status": "pending|in_progress|completed|failed|abandoned",
    "created_at": "2025-11-28T10:00:00",
    "updated_at": "2025-11-28T10:30:00",
    "started_at": "2025-11-28T10:05:00",
    "completed_at": "2025-11-28T10:30:00",
    "result": {...},
    "error": null,
    "retry_count": 0,
    "metadata": {...}
}
```

## A2A Message Format

```json
{
    "type": "request|response|heartbeat|event|ack|error",
    "sender": "agent-1",
    "recipient": "agent-2",
    "payload": {
        "action": "assign_task",
        "task": {...}
    },
    "metadata": {
        "origin": "agent-1",
        "version": "v1",
        "timestamp": "2025-11-28T10:30:00",
        "request_id": "uuid",
        "parent_request_id": null,
        "sequence_number": 1
    },
    "signature": "hmac-sha256-hex"
}
```

## Testing

### Run All Tests
```bash
pytest tests/ -v
```

### Run Specific Test File
```bash
pytest tests/test_core.py -v
pytest tests/test_integration_a2a.py -v
```

### Run with Coverage
```bash
pytest tests/ --cov=core --cov=coordinator --cov=distributor --cov=worker
```

### Test Categories

1. **Unit Tests** (`test_core.py`)
   - A2A message creation and signing
   - LangGraph state management
   - Task lifecycle
   - State serialization

2. **Integration Tests** (`test_integration_a2a.py`)
   - A2A message routing
   - Message type handling
   - Causal metadata tracking
   - Signature verification

## Deployment

### Local Development
```bash
# Start Redis
docker run -d -p 6379:6379 redis:latest

# Run example
python example_e2e.py
```

### Docker Deployment

Create `Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["python", "example_e2e.py"]
```

Build and run:
```bash
docker build -t agent-system .
docker run -e REDIS_HOST=redis agent-system
```

### Production Configuration

For production deployment:

1. **Redis**
   - Use Redis Cluster for high availability
   - Enable TLS with certificates
   - Use authentication (password or ACL)
   - Configure persistence (RDB or AOF)

2. **Security**
   - Enable mTLS for A2A messaging
   - Use signed JWT tokens for agent authentication
   - Implement role-based access control (RBAC)
   - Validate all incoming messages

3. **Monitoring**
   - Collect metrics on message rates
   - Track shared state write conflicts
   - Monitor lease failures
   - Log all state changes

4. **Resilience**
   - Implement circuit breakers for Redis failures
   - Add retry policies with exponential backoff
   - Maintain state snapshots for recovery
   - Implement distributed tracing

## Metrics & Monitoring

The system provides tracking for:

- **Message Metrics**
  - Message count by type
  - Message latency
  - Signature verification failures
  - Routing errors

- **State Metrics**
  - Shared state update frequency
  - Update conflicts (version mismatches)
  - Lease acquisition time
  - Lease renewal failures

- **Task Metrics**
  - Task count by status
  - Task execution time
  - Task retry count
  - Task failure reasons

- **Health Metrics**
  - Heartbeat send/receive counts
  - Agent availability
  - Worker failure detection time
  - State reconciliation time

## Failure Scenarios & Recovery

### Worker Failure
1. Distributor detects heartbeat timeout
2. Tasks marked as FAILED in local state
3. Shared state updated via Redis transaction
4. Coordinator notified via A2A event
5. Tasks can be reassigned to other workers

### Distributor Failure
1. Coordinator detects heartbeat timeout
2. Coordinator pulls latest state from Redis
3. Attempts to recover distributor via A2A
4. Manages worker failover

### Redis Failure
1. Coordinator/Distributor detect Redis connection error
2. Retry with exponential backoff
3. Local state maintained during outage
4. Reconcile with Redis on recovery

### Network Partition
1. Agents continue operating locally
2. A2A messages buffered/queued
3. On partition heal, state synchronization occurs
4. Lease patterns prevent conflicting updates

## Future Enhancements

1. **Persistent State Store**
   - Add PostgreSQL/MongoDB for long-term storage
   - Implement event sourcing

2. **Advanced Scheduling**
   - Task prioritization
   - Load balancing across workers
   - Resource constraint awareness

3. **Machine Learning Integration**
   - Replace hardcoded agents with LLM models
   - Use LangGraph with chat models
   - Implement decision-making logic

4. **Visualization**
   - Web dashboard for agent status
   - Real-time message flow visualization
   - State change history browser

5. **Scalability**
   - Support for distributed agent nodes
   - Cross-datacenter communication
   - Horizontal scaling of workers

## Architecture Decisions

### Why LangGraph?
- Native state management for AI agents
- Composable graph-based workflows
- Clean separation of concerns
- Easy to extend with custom nodes

### Why Redis for Shared State?
- Fast, in-memory data store
- Built-in pub/sub for notifications
- Transaction support for consistency
- Easy deployment and scaling

### Why A2A P2P Messaging?
- Direct agent-to-agent communication
- Low latency compared to message brokers
- Full control over message format
- Support for request-response patterns

### Why Optimistic Concurrency?
- Higher throughput than pessimistic locking
- Simpler implementation than distributed locks
- Works well for infrequent conflicts
- Redis transactions (WATCH/MULTI/EXEC) provide safety

## API Reference

### CoordinatorAgent

```python
# Initialize
coordinator.initialize() -> bool

# Task Assignment
coordinator.assign_task_to_distributor(task: Task, distributor_id: str) -> bool

# Monitoring
coordinator.register_distributor(distributor_id: str) -> bool
coordinator.get_distributor_state(distributor_id: str) -> Optional[SharedAgentState]
coordinator.monitor_distributors() -> None
```

### DistributorAgent

```python
# Initialize
distributor.initialize() -> bool

# Worker Management
distributor.register_worker(worker_id: str) -> bool
distributor.assign_task_to_worker(task: Task, worker_id: str) -> bool
distributor.monitor_workers() -> None

# Shared State Management
distributor.acquire_shared_state_lease() -> bool
distributor.renew_shared_state_lease() -> bool
```

### WorkerAgent

```python
# Initialize
worker.initialize() -> bool

# Task Execution
worker.execute_task(task: Task) -> Dict[str, Any]

# Health Reporting
worker.send_heartbeat() -> bool
```

## License

MIT License - See LICENSE file for details

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

## Support

For issues, questions, or suggestions:
1. Check existing GitHub issues
2. Create a new issue with reproduction steps
3. Include logs and configuration details

## Related Resources

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [Redis Documentation](https://redis.io/documentation)
- [Agent-Based Systems](https://en.wikipedia.org/wiki/Multiagent_system)
- [Distributed Systems Patterns](https://martinfowler.com/articles/patterns-of-distributed-systems/)

---

**Last Updated**: November 28, 2025
**POC Version**: 0.1.0
