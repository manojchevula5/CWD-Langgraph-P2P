# Deployment Guide

## Quick Start (Local Development)

### 1. Prerequisites
- Python 3.11+
- Redis server
- Git

### 2. Installation Steps

```bash
# Clone the repository
git clone <repo-url>
cd agent-system

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Setup environment
cp .env.example .env
```

### 3. Start Redis

```bash
# Using Docker (recommended)
docker run -d -p 6379:6379 --name redis redis:latest

# Or using local Redis
redis-server
```

### 4. Run Example

```bash
python example_e2e.py
```

## Docker Deployment

### Single Container

```bash
docker build -t agent-system:latest .
docker run -e REDIS_HOST=redis-container agent-system:latest
```

### Docker Compose

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  redis:
    image: redis:latest
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  coordinator:
    build: .
    environment:
      REDIS_HOST: redis
      COORDINATOR_ID: coordinator-1
      LOG_LEVEL: INFO
    depends_on:
      redis:
        condition: service_healthy
    ports:
      - "8001:8001"

  distributor:
    build: .
    environment:
      REDIS_HOST: redis
      DISTRIBUTOR_ID: distributor-1
      COORDINATOR_ID: coordinator-1
      LOG_LEVEL: INFO
    depends_on:
      redis:
        condition: service_healthy
    ports:
      - "8002:8002"

  worker1:
    build: .
    environment:
      REDIS_HOST: redis
      WORKER_ID: worker-1
      DISTRIBUTOR_ID: distributor-1
      LOG_LEVEL: INFO
    depends_on:
      redis:
        condition: service_healthy
    ports:
      - "8003:8003"

  worker2:
    build: .
    environment:
      REDIS_HOST: redis
      WORKER_ID: worker-2
      DISTRIBUTOR_ID: distributor-1
      LOG_LEVEL: INFO
    depends_on:
      redis:
        condition: service_healthy
    ports:
      - "8004:8004"

volumes:
  redis_data:
```

Run with:
```bash
docker-compose up -d
```

## Redis Configuration

### Development (insecure)
```
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_USE_TLS=false
```

### Production (secure)

1. **Enable Redis AUTH**
```bash
# In redis.conf
requirepass your-strong-password
```

2. **Enable TLS**
```bash
# Generate certificates
openssl req -x509 -newkey rsa:2048 -keyout redis.key -out redis.crt -days 365

# In redis.conf
port 0
tls-port 6380
tls-cert-file /path/to/redis.crt
tls-key-file /path/to/redis.key
tls-ca-cert-file /path/to/ca.crt
```

3. **Configure application**
```
REDIS_HOST=redis.example.com
REDIS_PORT=6380
REDIS_PASSWORD=your-strong-password
REDIS_USE_TLS=true
REDIS_SSL_CERT_REQS=required
```

## Kubernetes Deployment

### Create ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: agent-system-config
data:
  redis_host: redis-service
  redis_port: "6379"
  log_level: "INFO"
```

### Create Redis StatefulSet

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis
spec:
  serviceName: redis-service
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis:latest
        ports:
        - containerPort: 6379
        volumeMounts:
        - name: redis-data
          mountPath: /data
  volumeClaimTemplates:
  - metadata:
      name: redis-data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 1Gi
```

### Create Coordinator Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: coordinator
spec:
  replicas: 1
  selector:
    matchLabels:
      app: coordinator
  template:
    metadata:
      labels:
        app: coordinator
    spec:
      containers:
      - name: coordinator
        image: agent-system:latest
        env:
        - name: COORDINATOR_ID
          value: coordinator-1
        - name: REDIS_HOST
          valueFrom:
            configMapKeyRef:
              name: agent-system-config
              key: redis_host
        - name: REDIS_PORT
          valueFrom:
            configMapKeyRef:
              name: agent-system-config
              key: redis_port
        ports:
        - containerPort: 8001
        livenessProbe:
          httpGet:
            path: /health
            port: 8001
          initialDelaySeconds: 10
          periodSeconds: 10
```

### Create Worker Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: worker
spec:
  replicas: 3
  selector:
    matchLabels:
      app: worker
  template:
    metadata:
      labels:
        app: worker
    spec:
      containers:
      - name: worker
        image: agent-system:latest
        env:
        - name: WORKER_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: REDIS_HOST
          valueFrom:
            configMapKeyRef:
              name: agent-system-config
              key: redis_host
        ports:
        - containerPort: 8003
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "500m"
```

## Health Checks

### HTTP Health Endpoint

Agents should expose a health endpoint:

```python
@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "agent_id": agent_id,
        "uptime": uptime,
        "redis_connected": redis_client.client is not None,
    }
```

### Redis Health Check

```bash
redis-cli ping
# Response: PONG
```

### Logs Inspection

```bash
# View agent logs
tail -f agent_system.log

# Check for errors
grep ERROR agent_system.log

# Monitor message throughput
grep "Sending\|Received" agent_system.log | wc -l
```

## Monitoring & Alerting

### Prometheus Metrics

Expose metrics endpoint:

```python
from prometheus_client import Counter, Histogram, start_http_server

message_count = Counter('agent_messages_total', 'Total messages')
task_duration = Histogram('task_duration_seconds', 'Task execution time')

@app.get("/metrics")
def metrics():
    # Prometheus format
    pass
```

### Key Metrics to Monitor

1. **Message Metrics**
   - Messages per second
   - Message latency
   - Failed message rate

2. **Task Metrics**
   - Tasks created/completed
   - Task success rate
   - Task duration (p50, p95, p99)

3. **System Metrics**
   - Redis connection pool status
   - Memory usage
   - CPU usage

### Alert Rules

```yaml
# Prometheus alert rules
groups:
- name: agent_system
  rules:
  - alert: HighFailureRate
    expr: rate(agent_failures_total[5m]) > 0.05
    for: 1m
    annotations:
      summary: "High agent failure rate"
      
  - alert: RedisUnavailable
    expr: redis_connected == 0
    for: 30s
    annotations:
      summary: "Redis connection lost"
      
  - alert: TaskBacklog
    expr: pending_tasks > 1000
    for: 5m
    annotations:
      summary: "Large task backlog"
```

## Troubleshooting

### Common Issues

#### Redis Connection Failed
```
ERROR: Connection refused at localhost:6379
```

**Solution:**
```bash
# Check Redis status
redis-cli ping

# Start Redis if not running
docker run -d -p 6379:6379 redis:latest
```

#### Message Signature Verification Failed
```
ERROR: Message signature verification failed
```

**Solution:**
- Verify token_secret is consistent across agents
- Check message tampering in transit
- Verify all agents use same signing algorithm

#### State Conflict (Optimistic Concurrency)
```
WARN: Transaction failed due to state conflict
```

**Solution:**
- This is expected under high concurrent load
- System will retry automatically
- Monitor retry metrics

#### Lease Timeout
```
WARN: Lease acquisition timeout
```

**Solution:**
- Increase lease TTL if operations take longer
- Check for long-running operations blocking updates
- Verify Redis performance

### Debug Mode

Enable debug logging:

```
LOG_LEVEL=DEBUG python example_e2e.py
```

This will show:
- All message sends/receives
- State transitions
- Redis operations
- Retry attempts

## Performance Tuning

### Redis Configuration

```conf
# redis.conf

# Memory optimization
maxmemory 2gb
maxmemory-policy allkeys-lru

# Network optimization
tcp-keepalive 300
timeout 0

# Persistence (optional)
save 900 1
save 300 10
save 60 10000
```

### Python Application

```python
# Connection pooling
pool = redis.ConnectionPool(
    host='localhost',
    port=6379,
    max_connections=50,
)
client = redis.Redis(connection_pool=pool)

# Batch operations
pipe = redis.client.pipeline(transaction=False)
for i in range(1000):
    pipe.set(f"key:{i}", f"value:{i}")
pipe.execute()
```

### Task Optimization

1. **Batch Similar Tasks**
```python
# Instead of assigning tasks one by one
tasks = [task1, task2, task3]
distributor.batch_assign_tasks(tasks, worker_id)
```

2. **Task Prioritization**
```python
task.priority = 10  # Higher priority
distributor.assign_task_to_worker(task, worker_id)
```

3. **Worker Load Balancing**
```python
# Assign to least busy worker
least_busy = min(workers, 
    key=lambda w: len(w.pending_tasks))
distributor.assign_task_to_worker(task, least_busy.id)
```

## Backup & Recovery

### Redis Backup

```bash
# Manual backup
redis-cli BGSAVE

# Scheduled backup
0 2 * * * /usr/bin/redis-cli BGSAVE

# Restore from backup
docker run -d -v $(pwd)/dump.rdb:/data/dump.rdb redis:latest
```

### State Snapshots

```python
# Snapshot current state
snapshot = {
    "coordinator_state": coordinator.get_state_snapshot(),
    "distributor_state": distributor.get_state_snapshot(),
    "worker_states": [w.get_state_snapshot() for w in workers],
}

# Save to file
with open("state_snapshot.json", "w") as f:
    json.dump(snapshot, f)

# Restore on startup
with open("state_snapshot.json", "r") as f:
    snapshot = json.load(f)
    agent.set_state(snapshot)
```

## Update & Rollout

### Blue-Green Deployment

```bash
# Deploy new version (green)
docker build -t agent-system:v2 .
docker tag agent-system:v2 registry/agent-system:v2

# Test green deployment
docker-compose -f docker-compose.green.yml up

# If successful, switch traffic
docker-compose -f docker-compose.yml up

# Remove old version (blue)
docker-compose down
```

### Rolling Update (Kubernetes)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: worker
spec:
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
```

## Security Checklist

- [ ] Enable Redis authentication
- [ ] Enable TLS for Redis
- [ ] Enable mTLS for A2A messaging
- [ ] Validate all incoming messages
- [ ] Use strong token secrets
- [ ] Rotate credentials regularly
- [ ] Enable audit logging
- [ ] Restrict network access
- [ ] Use secrets management (Vault, K8s Secrets)
- [ ] Enable Redis persistence
- [ ] Regular security scanning

---

**Last Updated**: November 28, 2025
