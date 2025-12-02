# Quick Start Guide

Get the three-tier agent system running in 5 minutes.

## Option 1: Local Python (Fastest)

### Prerequisites
- Python 3.11+
- Redis running on localhost:6379

### Steps

```bash
# 1. Navigate to project
cd agent-system

# 2. Install dependencies (one-time)
pip install -r requirements.txt

# 3. Run example
python example_e2e.py
```

**Expected Output:**
```
INFO - Initializing Coordinator...
INFO - Initializing Distributor...
INFO - Initializing Worker-1...
INFO - Initializing Worker-2...
INFO - All agents initialized successfully!
INFO - SCENARIO: Coordinator assigns tasks
...
INFO - FINAL STATE SUMMARY
INFO - Coordinator assigned 2 tasks
INFO - Workers executed 2 tasks successfully
```

### Next Steps
- Edit `example_e2e.py` to modify task types
- Read `README.md` for API documentation
- Check `tests/` for more examples

---

## Option 2: Docker (Recommended)

### Prerequisites
- Docker and Docker Compose

### Steps

```bash
# 1. Navigate to project
cd agent-system

# 2. Start all services
docker-compose up -d

# 3. Check logs
docker-compose logs -f coordinator

# 4. Stop services
docker-compose down
```

**Services Started:**
- Redis (port 6379)
- Coordinator (port 8001)
- Distributor (port 8002)
- Worker-1 (port 8003)
- Worker-2 (port 8004)

### Troubleshooting
```bash
# View specific service logs
docker-compose logs coordinator

# Check running containers
docker-compose ps

# Restart a service
docker-compose restart coordinator

# Remove all containers
docker-compose down -v
```

---

## Redis Setup (If Not Already Running)

### Option A: Docker (Easiest)
```bash
docker run -d -p 6379:6379 --name redis redis:latest
```

### Option B: Local Installation
```bash
# macOS
brew install redis
brew services start redis

# Ubuntu/Debian
sudo apt-get install redis-server
sudo service redis-server start

# Windows
# Download from: https://github.com/microsoftarchive/redis/releases
```

### Verify Redis
```bash
redis-cli ping
# Should return: PONG
```

---

## Configuration

### For Local Development
No changes needed. Uses defaults in `.env.example`:
```
REDIS_HOST=localhost
REDIS_PORT=6379
A2A_TOKEN_SECRET=default-secret
```

### For Remote Redis
Create `.env` file:
```bash
cp .env.example .env
```

Edit with your Redis connection — you can supply either `host:port` or a
Redis URI (`redis://` or `rediss://`) and set TLS via `REDIS_USE_TLS`:
```
# Either host/port form
REDIS_HOST=redis.example.com:6379
REDIS_PASSWORD=your-password
REDIS_USE_TLS=true

# Or a Redis URI (includes password and scheme)
REDIS_HOST=rediss://:your-password@redis-aiops-dev-wus3-01.redis.cache.windows.net:6380
REDIS_DB=0
```

---

## Running Tests

```bash
# Install test dependencies
pip install pytest pytest-asyncio

# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_core.py -v

# Run with coverage
pytest tests/ --cov=core --cov=coordinator --cov=distributor --cov=worker --cov-report=html

# View coverage report
open htmlcov/index.html
```

---

## Common Tasks

### See State Management
```python
from example_e2e import coordinator

# View agent state
print(coordinator.local_state.to_json())

# View shared state (Redis)
state = coordinator.redis_client.get("shared:distributor:distributor-1")
print(state)
```

### Create Custom Task
```python
from core import Task, TaskStatus

task = Task(
    task_id="custom-task",
    task_type="compute",
    payload={"custom": "data"}
)

coordinator.assign_task_to_distributor(task, "distributor-1")
```

### Monitor Agent Status
```bash
# Enable debug logging
LOG_LEVEL=DEBUG python example_e2e.py

# Or edit logging in your code
import logging
logging.basicConfig(level=logging.DEBUG)
```

---

## Next Steps

### Learn More
1. **Architecture**: Read `README.md`
2. **API Reference**: Section "API Reference" in `README.md`
3. **Deployment**: See `DEPLOYMENT.md`
4. **Development**: See `.github/copilot-instructions.md`

### Run Your Own Scenario
1. Copy `example_e2e.py` to `my_scenario.py`
2. Modify task creation
3. Run: `python my_scenario.py`

### Integrate with External System
1. Use `A2AClient` for messaging
2. Use `RedisClient` for shared state
3. Extend agent types by inheriting from `LangGraphAgent`

---

## Troubleshooting

### "Connection refused at localhost:6379"
**Problem**: Redis not running  
**Solution**:
```bash
docker run -d -p 6379:6379 redis:latest
# Then retry your command
```

### "ModuleNotFoundError: No module named 'core'"
**Problem**: Dependencies not installed  
**Solution**:
```bash
pip install -r requirements.txt
```

### "Message signature verification failed"
**Problem**: Token secret mismatch  
**Solution**: Check `.env` file and ensure all agents have same `A2A_TOKEN_SECRET`

### "Redis transaction conflict"
**Problem**: Normal under concurrent load  
**Solution**: System retries automatically. Check logs with `LOG_LEVEL=DEBUG`

---

## What's Happening

When you run `python example_e2e.py`:

```
┌─────────────────────────────────────────────────────┐
│ 1. Coordinator Starts                               │
│    - Connects to Redis                              │
│    - Subscribes to shared state updates             │
└─────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────┐
│ 2. Distributor Starts                               │
│    - Connects to Redis                              │
│    - Initializes shared state                       │
└─────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────┐
│ 3. Workers Start                                    │
│    - Register with Distributor (A2A)                │
│    - Ready to accept tasks                          │
└─────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────┐
│ 4. Coordinator Assigns Tasks                        │
│    - Creates Task objects                           │
│    - Sends via A2A to Distributor                   │
└─────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────┐
│ 5. Distributor Distributes to Workers               │
│    - Updates shared state in Redis                  │
│    - Sends tasks via A2A to Workers                 │
└─────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────┐
│ 6. Workers Execute Tasks                            │
│    - Mark as IN_PROGRESS                            │
│    - Execute logic                                  │
│    - Mark as COMPLETED                              │
└─────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────┐
│ 7. Report Results                                   │
│    - Workers send completion via A2A                │
│    - Distributor updates Redis                      │
│    - Coordinator receives notification              │
└─────────────────────────────────────────────────────┘
```

---

## Performance Metrics

Typical performance on modern hardware:

| Metric | Value |
|--------|-------|
| Message latency | 1-10ms |
| Task assignment | < 5ms |
| Task execution | ~1 second (simulated) |
| State sync | < 10ms |
| Throughput | 100+ tasks/sec |

---

## Support

- **Issues**: Check GitHub issues
- **Questions**: See `README.md` FAQ section
- **Development**: See `.github/copilot-instructions.md`
- **Deployment**: See `DEPLOYMENT.md`

---

**Last Updated**: November 28, 2025  
**Version**: 0.1.0  
**Status**: ✅ Ready to Use
