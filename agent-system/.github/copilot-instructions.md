# Three-Tier Agent System - Project Guidelines

## Project Context

This is a **POC Implementation** of a three-tier hierarchical multi-agent system with:
- **Coordinator Agent**: High-level task orchestration
- **Distributor Agent**: Task distribution and worker management
- **Worker Agents**: Task execution
- **Technologies**: LangGraph (state), Redis (shared state), A2A (P2P messaging)

## Architecture Overview

```
Coordinator (LangGraph state + Redis shared state) 
    ↓ A2A Messaging
Distributor (LangGraph state + Redis shared state)
    ↓ A2A Messaging
Workers (LangGraph state only, no Redis)
```

## Key Principles

### 1. State Management
- Each agent has **LocalAgentState** (LangGraph) for runtime data
- Coordinator ↔ Distributor share **SharedAgentState** (Redis)
- Workers maintain only local state (no Redis)

### 2. Communication
- **A2A Messaging**: All agent-to-agent communication (signed, with causal metadata)
- **Redis Pub/Sub**: Shared state change notifications
- Message types: REQUEST, RESPONSE, HEARTBEAT, EVENT, ACK, ERROR

### 3. Consistency
- Optimistic concurrency with version tracking
- Redis transactions (WATCH/MULTI/EXEC)
- Distributed lease pattern for critical updates

### 4. Monitoring
- Heartbeat-based health checks
- Automatic failure detection and recovery
- State reconciliation on conflicts

## Directory Structure

```
agent-system/
├── core/                   # Core modules
│   ├── redis_client.py     # Redis integration
│   ├── a2a_messaging.py    # P2P messaging
│   └── langgraph_state.py  # State models
├── coordinator/            # Coordinator agent
├── distributor/           # Distributor agent
├── worker/                # Worker agent
├── tests/                 # Unit & integration tests
├── example_e2e.py         # End-to-end example
├── README.md              # User guide
├── DEPLOYMENT.md          # Deployment guide
└── requirements.txt       # Dependencies
```

## Development Workflow

### Adding New Features

1. **State Changes**: Update models in `core/langgraph_state.py`
2. **Messaging**: Add message types/handlers in `core/a2a_messaging.py`
3. **Agent Logic**: Update specific agent in `coordinator/agent.py`, `distributor/agent.py`, or `worker/agent.py`
4. **Tests**: Add tests in `tests/test_*.py`

### Naming Conventions

- **Classes**: PascalCase (e.g., `CoordinatorAgent`)
- **Functions**: snake_case (e.g., `execute_task`)
- **Constants**: UPPER_SNAKE_CASE (e.g., `MAX_RETRIES`)
- **Files**: snake_case (e.g., `redis_client.py`)

### Code Style

- Follow PEP 8
- Type hints on all functions
- Docstrings for all classes/methods
- Logging at appropriate levels (INFO, WARN, ERROR)

## Important Concepts

### Task Lifecycle
```
PENDING → IN_PROGRESS → COMPLETED (success)
       ↓
    FAILED (error, can retry)
```

### Agent Status
- `IDLE`: Agent ready for work
- `BUSY`: Agent executing/processing
- `ERROR`: Agent encountered error
- `RECOVERING`: Agent recovering from failure

### Redis Keys
- `shared:distributor:{id}` - Shared state
- `shared:distributor:{id}:events` - Event channel
- `shared:distributor:{id}:lease` - Lease for concurrency

### Message Flow

#### Task Assignment
```
Coordinator --REQUEST--> Distributor --RESPONSE--> Coordinator
Distributor --REQUEST--> Worker --RESPONSE--> Distributor
```

#### Shared State Update
```
Distributor: Update Redis transaction
Distributor: Publish event to Redis channel
Coordinator: Receives event, pulls latest state
Coordinator: Updates local copy
```

#### Health Check
```
Worker --HEARTBEAT--> Distributor
Distributor --HEARTBEAT--> Coordinator
```

## Common Tasks

### Adding a New Agent Type

1. Create `new_agent/agent.py` inheriting from `LangGraphAgent`
2. Implement `process_message()` and `execute_task()`
3. Register message handlers in `__init__`
4. Add initialization logic

### Adding a New Task Type

1. Add `TaskType` enum entry
2. Implement `_execute_{task_type}_task()` in Worker
3. Add result schema documentation
4. Test with example

### Adding Shared State Persistence

1. Update `SharedAgentState` model
2. Add Redis key for storage
3. Update publish/subscribe logic
4. Add reconciliation logic in agents

## Testing Guidelines

### Unit Tests
- Test individual components in isolation
- Mock external dependencies
- File: `tests/test_core.py`

### Integration Tests
- Test A2A message routing
- Test Redis operations
- Test state synchronization
- File: `tests/test_integration_a2a.py`

### End-to-End Tests
- Test complete workflow
- File: `example_e2e.py`

### Run Tests
```bash
pytest tests/ -v              # All tests
pytest tests/test_core.py -v  # Specific file
pytest --cov=core tests/      # With coverage
```

## Debugging

### Enable Debug Logging
```bash
LOG_LEVEL=DEBUG python example_e2e.py
```

### Common Debug Points
1. Message signature verification
2. Redis transaction conflicts
3. Lease acquisition failures
4. State reconciliation mismatches
5. Heartbeat timeouts

### Inspect State
```python
# Local state
print(agent.local_state.to_json())

# Shared state (Redis)
state = redis_client.get("shared:distributor:id")
print(state)

# Message history
print(agent.local_state.history)
```

## Performance Considerations

### Redis Operations
- Batch writes when possible
- Use pipelining for multiple commands
- Monitor transaction conflicts
- Keep values reasonably sized (< 1MB)

### A2A Messaging
- Minimize message size
- Batch related requests
- Implement backpressure
- Monitor signature verification time

### State Synchronization
- Reconcile only on changes
- Use exponential backoff for retries
- Limit history entries
- Archive old data

## Security Reminders

### Authentication
- All messages signed with HMAC-SHA256
- Verify signatures before processing
- Use strong token secrets
- Rotate secrets periodically

### Authorization
- Validate sender identity
- Check agent roles/permissions
- Audit all state changes
- Log security events

### Network
- Use TLS for Redis
- Use mTLS for A2A (when enabled)
- Validate all inputs
- Sanitize log output

## Deployment Notes

### Configuration
- Use `.env` for configuration
- Don't commit secrets
- Use environment-specific configs
- Document all configuration options

### Scaling
- Distributors can be scaled independently
- Workers can be scaled per distributor
- Redis should be replicated
- Use load balancing for distributors

### Monitoring
- Export Prometheus metrics
- Set up health checks
- Monitor Redis performance
- Track message latencies

## Useful Resources

- **LangGraph**: See `core/langgraph_state.py` for state management patterns
- **Redis**: See `core/redis_client.py` for connection/transaction examples
- **A2A Messaging**: See `core/a2a_messaging.py` for message formats/routing

## Project Status

- **Phase**: POC (Proof of Concept)
- **Version**: 0.1.0
- **Last Updated**: November 28, 2025

## Next Steps (Future)

1. Add persistent storage (PostgreSQL/MongoDB)
2. Integrate LLM models (replace hardcoded agents)
3. Add web dashboard for visualization
4. Implement distributed tracing
5. Add horizontal scaling across datacenters

---

When working on this project:
- Always update tests when changing functionality
- Follow the existing patterns and conventions
- Keep documentation in sync with code
- Run full test suite before committing
- Use meaningful commit messages with [agent-system] prefix
