# Module Documentation

Complete reference for all modules in the three-tier agent system.

## Core Modules (`core/`)

### `redis_client.py` - Redis Integration (400+ lines)

**Purpose**: Robust Redis client with connection pooling, pub/sub, transactions, and lease management.

**Key Classes**:
- `RedisConfig`: Configuration dataclass for Redis connection
- `RedisClient`: Main Redis client with retry logic

**Key Methods**:
```python
# Connection
.connect() -> bool                    # Connect to Redis
.disconnect() -> None                 # Close connection

# Basic Operations
.set(key, value, ttl) -> bool         # Set key-value
.get(key) -> Optional[Union[str, Dict]]  # Get value
.delete(key) -> bool                  # Delete key
.exists(key) -> bool                  # Check existence
.incr(key, amount) -> Optional[int]   # Increment counter

# Pub/Sub
.publish(channel, message) -> int     # Publish message
.subscribe(channels, callback) -> bool  # Subscribe to channels

# Transactions
.watch(key) -> bool                   # Watch for changes
.transaction(key, update_func) -> Optional[Any]  # Execute transaction

# Leasing (Distributed Locks)
.acquire_lease(lease_key, owner, ttl) -> bool    # Acquire lease
.renew_lease(lease_key, owner, ttl) -> bool      # Renew lease
.release_lease(lease_key, owner) -> bool         # Release lease
.get_lease(lease_key) -> Optional[Dict]          # Get lease info
```

**Usage Example**:
```python
from core import RedisConfig, RedisClient

config = RedisConfig(host="localhost", port=6379)
client = RedisClient(config)
client.connect()

# Set value
client.set("key", {"data": "value"}, ttl=3600)

# Get value
value = client.get("key")

# Publish event
client.publish("channel", {"event": "data"})

# Subscribe
def on_message(channel, data):
    print(f"Received: {data}")

client.subscribe("channel", on_message)
```

---

### `a2a_messaging.py` - P2P Agent Messaging (500+ lines)

**Purpose**: Agent-to-Agent peer-to-peer messaging with signing, routing, and causal metadata.

**Key Classes**:
- `MessageType`: Enum for message types (REQUEST, RESPONSE, HEARTBEAT, EVENT, ACK, ERROR)
- `CausalMetadata`: Causal metadata tracking
- `A2AMessage`: Message structure with payload and metadata
- `A2AConfig`: Configuration for A2A client
- `A2AClient`: Client for sending/receiving messages
- `A2ARouter`: Routes messages between agents (for testing)

**Key Methods**:
```python
# Message Creation
.create_message(recipient, payload, message_type, parent_request_id) -> A2AMessage
.send_request(recipient, payload, timeout) -> Optional[A2AMessage]
.send_response(recipient, parent_request_id, payload, success) -> A2AMessage
.send_heartbeat(recipient, status) -> A2AMessage
.send_event(recipient, event_type, event_data) -> A2AMessage

# Message Handling
.register_handler(message_type, handler) -> None
.handle_message(message) -> bool

# Signing & Verification
._sign_message(message) -> str
._verify_message(message) -> bool
```

**Usage Example**:
```python
from core import A2AConfig, A2AClient, MessageType

config = A2AConfig(
    agent_id="agent-1",
    token_secret="secret"
)
client = A2AClient(config)

# Send request
message = client.create_message(
    recipient="agent-2",
    payload={"action": "compute"},
    message_type=MessageType.REQUEST
)

# Send response
client.send_response(
    "agent-2",
    parent_request_id,
    {"result": 42},
    success=True
)

# Send heartbeat
client.send_heartbeat("agent-2", {"status": "active"})

# Register handler
def handle_request(msg):
    print(f"Received: {msg.payload}")

client.register_handler(MessageType.REQUEST, handle_request)
```

**Message Format**:
```json
{
    "type": "request|response|heartbeat|event|ack|error",
    "sender": "agent-1",
    "recipient": "agent-2",
    "payload": {"key": "value"},
    "metadata": {
        "origin": "agent-1",
        "version": "v1",
        "timestamp": "2025-11-28T...",
        "request_id": "uuid",
        "parent_request_id": null,
        "sequence_number": 1
    },
    "signature": "hmac-sha256-hex"
}
```

---

### `langgraph_state.py` - State Management (400+ lines)

**Purpose**: LangGraph-based state management for agents, including local and shared state models.

**Key Classes**:
- `TaskStatus`: Enum for task status
- `AgentStatus`: Enum for agent status
- `Task`: Task model with full lifecycle
- `LocalAgentState`: Per-agent LangGraph state
- `SharedAgentState`: Shared state between Coordinator and Distributor
- `LangGraphAgent`: Base class for agents

**Key Methods (LocalAgentState)**:
```python
.add_task(task) -> None              # Add task
.update_task(task_id, updates) -> bool   # Update task
.get_task(task_id) -> Optional[Task]     # Get task
.set_local_var(key, value) -> None       # Set variable
.get_local_var(key) -> Optional[Any]     # Get variable
.add_history_entry(entry) -> None        # Add history
.set_status(status) -> None              # Set status
.update_timestamp() -> None              # Update timestamps
.to_dict() -> Dict                       # Serialize
.to_json() -> str                        # JSON serialization
```

**Key Methods (Task)**:
```python
.mark_started() -> None                  # Mark IN_PROGRESS
.mark_completed(result) -> None          # Mark COMPLETED
.mark_failed(error) -> None              # Mark FAILED
.to_dict() -> Dict                       # Serialize
.to_json() -> str                        # JSON
```

**Usage Example**:
```python
from core import LocalAgentState, SharedAgentState, Task, TaskStatus, AgentStatus

# Create local state
local_state = LocalAgentState(agent_id="agent-1")
local_state.set_status(AgentStatus.BUSY)

# Create and add task
task = Task(
    task_id="task-1",
    task_type="compute",
    payload={"operation": "sum"}
)
local_state.add_task(task)

# Update task
task.mark_started()
# ... do work ...
task.mark_completed({"result": 42})

# Access state
print(local_state.to_json())

# Shared state
shared_state = SharedAgentState()
shared_state.assign_worker("worker-1")
shared_state.add_task(task)
print(shared_state.to_json())
```

**State Models**:

LocalAgentState:
```python
{
    "agent_id": "coordinator-1",
    "status": "idle|busy|error|recovering",
    "local_tasks": [Task, ...],
    "last_heartbeat": "2025-11-28T10:30:00",
    "local_vars": {key: value, ...},
    "history": [event, ...],
    "metadata": {key: value, ...}
}
```

SharedAgentState (Redis):
```python
{
    "coordinator_version": "v1",
    "distributor_version": "v1",
    "status": "idle|busy|error",
    "assigned_workers": ["worker-1"],
    "tasks": [Task, ...],
    "lease": {
        "owner": "coordinator|distributor",
        "acquired_at": "...",
        "expires_at": "..."
    }
}
```

---

## Agent Modules

### `coordinator/agent.py` - Coordinator Agent (300+ lines)

**Purpose**: High-level task orchestration, distributor monitoring, and shared state management.

**Class**: `CoordinatorAgent(LangGraphAgent)`

**Key Methods**:
```python
.initialize() -> bool                           # Initialize agent
.assign_task_to_distributor(task, distributor_id) -> bool  # Assign task
.register_distributor(distributor_id) -> bool   # Register distributor
.get_distributor_state(distributor_id) -> Optional[SharedAgentState]  # Get state
.monitor_distributors() -> None                 # Monitor health
.process_message(message) -> Dict               # Process incoming
.execute_task(task) -> Dict                     # Not used in Coordinator
.cleanup() -> None                              # Cleanup resources
```

**Responsibilities**:
- Create and assign tasks to distributors
- Monitor distributor health via heartbeats
- Manage shared state with Redis
- Reconcile state changes
- Recover from failures

**Usage**:
```python
from coordinator.agent import CoordinatorAgent
from core import RedisConfig, A2AConfig, Task

redis_config = RedisConfig()
a2a_config = A2AConfig(agent_id="coordinator-1")

coordinator = CoordinatorAgent(
    agent_id="coordinator-1",
    redis_config=redis_config,
    a2a_config=a2a_config
)

coordinator.initialize()

# Create and assign task
task = Task(task_id="task-1", task_type="compute", payload={})
coordinator.assign_task_to_distributor(task, "distributor-1")

coordinator.cleanup()
```

---

### `distributor/agent.py` - Distributor Agent (350+ lines)

**Purpose**: Task distribution, worker management, and shared state synchronization with coordinator.

**Class**: `DistributorAgent(LangGraphAgent)`

**Key Methods**:
```python
.initialize() -> bool                           # Initialize
.register_worker(worker_id) -> bool             # Register worker
.assign_task_to_worker(task, worker_id) -> bool # Assign task
.acquire_shared_state_lease() -> bool           # Acquire lock
.renew_shared_state_lease() -> bool             # Renew lock
.monitor_workers() -> None                      # Monitor health
.process_message(message) -> Dict               # Process incoming
.execute_task(task) -> Dict                     # Not used
.cleanup() -> None                              # Cleanup
```

**Responsibilities**:
- Receive tasks from coordinator
- Distribute work to workers
- Manage worker lifecycle and health
- Maintain shared state with coordinator
- Handle worker failures
- Update Redis with optimistic concurrency

**Usage**:
```python
from distributor.agent import DistributorAgent

distributor = DistributorAgent(
    agent_id="distributor-1",
    coordinator_id="coordinator-1",
    redis_config=redis_config,
    a2a_config=a2a_config
)

distributor.initialize()

# Register workers
distributor.register_worker("worker-1")
distributor.register_worker("worker-2")

# Assign task
distributor.assign_task_to_worker(task, "worker-1")

distributor.cleanup()
```

---

### `worker/agent.py` - Worker Agent (300+ lines)

**Purpose**: Task execution, local state management, and result reporting.

**Class**: `WorkerAgent(LangGraphAgent)`

**Key Methods**:
```python
.initialize() -> bool                   # Initialize
.execute_task(task) -> Dict             # Execute task
.send_heartbeat() -> bool               # Send heartbeat
.process_message(message) -> Dict       # Process incoming
.cleanup() -> None                      # Cleanup

# Task Execution
._execute_compute_task(task) -> Dict    # Compute task
._execute_data_processing_task(task) -> Dict  # Data task
._execute_generic_task(task) -> Dict    # Generic task
```

**Responsibilities**:
- Execute assigned tasks
- Maintain local state (no Redis)
- Send heartbeats to distributor
- Report task results
- Handle task failures
- Support task-specific execution logic

**Usage**:
```python
from worker.agent import WorkerAgent

worker = WorkerAgent(
    agent_id="worker-1",
    distributor_id="distributor-1",
    a2a_config=a2a_config
)

worker.initialize()

# Execute task
task = Task(task_id="task-1", task_type="compute", payload={})
result = worker.execute_task(task)

# Send heartbeat
worker.send_heartbeat()

worker.cleanup()
```

**Task Types**:
- `compute`: Numerical computation
- `data_processing`: Data transformation
- (Custom types can be added)

---

## Helper Classes

### `A2ARouter` - Message Router

Used for testing and local development without network transport.

```python
from core import A2ARouter, A2AClient, A2AConfig

router = A2ARouter()

# Register agents
config1 = A2AConfig(agent_id="agent-1")
client1 = A2AClient(config1)
router.register_agent("agent-1", client1)

# Route messages
message = client1.create_message("agent-2", {"data": "test"})
router.route_message(message)

# Retrieve messages
pending = router.get_messages("agent-2")
```

---

## Enums

### TaskStatus
```python
PENDING = "pending"          # Not yet started
IN_PROGRESS = "in_progress"  # Currently executing
COMPLETED = "completed"      # Successfully finished
FAILED = "failed"            # Failed (can retry)
ABANDONED = "abandoned"      # Abandoned
```

### AgentStatus
```python
IDLE = "idle"            # Ready for work
BUSY = "busy"            # Currently processing
ERROR = "error"          # Encountered error
RECOVERING = "recovering"  # Recovering from error
```

### MessageType
```python
REQUEST = "request"       # Request message
RESPONSE = "response"     # Response to request
HEARTBEAT = "heartbeat"  # Health check
EVENT = "event"          # Event notification
ACK = "ack"              # Acknowledgment
ERROR = "error"          # Error message
```

---

## Utility Functions

### Configuration

```python
# Redis
redis_config = RedisConfig(
    host="localhost",
    port=6379,
    password="optional",
    use_tls=False
)

# A2A
a2a_config = A2AConfig(
    agent_id="agent-1",
    agent_port=8001,
    token_secret="secret"
)
```

### State Serialization

```python
# To JSON
state_json = agent.local_state.to_json()

# To Dict
state_dict = agent.local_state.to_dict()

# From Dict
state = LocalAgentState(**state_dict)
```

---

## Integration Example

Complete example combining all modules:

```python
from core import (
    RedisConfig, A2AConfig, RedisClient, A2AClient,
    Task, TaskStatus, LocalAgentState, SharedAgentState
)
from coordinator.agent import CoordinatorAgent
from distributor.agent import DistributorAgent
from worker.agent import WorkerAgent

# Initialize
redis_config = RedisConfig()
redis_client = RedisClient(redis_config)
redis_client.connect()

# Create agents
coordinator = CoordinatorAgent(
    "coordinator-1",
    redis_config,
    A2AConfig(agent_id="coordinator-1")
)
coordinator.initialize()

distributor = DistributorAgent(
    "distributor-1",
    "coordinator-1",
    redis_config,
    A2AConfig(agent_id="distributor-1")
)
distributor.initialize()

worker = WorkerAgent(
    "worker-1",
    "distributor-1",
    A2AConfig(agent_id="worker-1")
)
worker.initialize()

# Workflow
task = Task(task_id="task-1", task_type="compute", payload={})
coordinator.assign_task_to_distributor(task, "distributor-1")
distributor.assign_task_to_worker(task, "worker-1")
result = worker.execute_task(task)

# Cleanup
coordinator.cleanup()
distributor.cleanup()
worker.cleanup()
redis_client.disconnect()
```

---

**Last Updated**: November 28, 2025
