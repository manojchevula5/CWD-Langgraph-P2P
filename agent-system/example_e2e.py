"""
End-to-end example demonstrating the three-tier agent system.
Coordinator assigns a task → Distributor updates shared state → Worker executes.
"""

import logging
import sys
import os
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import (
    RedisClient,
    RedisConfig,
    A2AClient,
    A2AConfig,
    A2ARouter,
    Task,
    TaskStatus,
)
from dotenv import load_dotenv
import os
from coordinator.agent import CoordinatorAgent
from distributor.agent import DistributorAgent
from worker.agent import WorkerAgent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def run_example():
    """Run end-to-end example"""
    logger.info("="*80)
    logger.info("Starting three-tier agent system example")
    logger.info("="*80)

    # Load environment variables from .env (if present) and initialize Redis configuration
    load_dotenv()
    # Support REDIS_HOST as host, host:port, or full URI (redis:// or rediss://)
    raw_redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port_env = os.getenv("REDIS_PORT")
    redis_password_env = os.getenv("REDIS_PASSWORD")
    raw = raw_redis_host.strip()

    redis_host = "localhost"
    redis_port = 6379
    redis_password = redis_password_env or None
    use_tls = str(os.getenv("REDIS_USE_TLS", "false")).lower() in ("1", "true", "yes")

    # If REDIS_HOST contains a URI like redis://host:port or rediss://host:port
    if raw.startswith("redis://") or raw.startswith("rediss://"):
        from urllib.parse import urlparse

        p = urlparse(raw)
        redis_host = p.hostname or "localhost"
        redis_port = p.port or int(redis_port_env or 6379)
        if p.password:
            redis_password = p.password
        use_tls = (p.scheme == "rediss") or use_tls
    elif ":" in raw and not raw.startswith("["):
        # simple host:port parsing (IPv6 addresses are not handled here)
        host_part, port_part = raw.split(":", 1)
        redis_host = host_part
        try:
            redis_port = int(port_part)
        except ValueError:
            redis_port = int(redis_port_env or 6379)
    else:
        redis_host = raw
        redis_port = int(redis_port_env or 6379)

    redis_config = RedisConfig(
        host=redis_host,
        port=redis_port,
        db=int(os.getenv("REDIS_DB", "0")),
        password=redis_password or None,
        use_tls=use_tls,
    )

    # Initialize A2A router for local testing
    a2a_router = A2ARouter()
    # Wire the router into the a2a messaging module so A2AClient._send routes messages
    import core.a2a_messaging as _a2a_mod
    _a2a_mod.GLOBAL_A2A_ROUTER = a2a_router

    # Create Coordinator
    coordinator_a2a_config = A2AConfig(
        agent_id="coordinator-1",
        agent_port=8001,
        token_secret="coordinator-secret",
    )
    coordinator = CoordinatorAgent(
        agent_id="coordinator-1",
        redis_config=redis_config,
        a2a_config=coordinator_a2a_config,
    )

    # Register coordinator with router
    a2a_router.register_agent("coordinator-1", coordinator.a2a_client)

    logger.info("Initializing Coordinator...")
    if not coordinator.initialize():
        logger.error("Failed to initialize Coordinator")
        return

    # Create Distributor
    distributor_a2a_config = A2AConfig(
        agent_id="distributor-1",
        agent_port=8002,
        token_secret="distributor-secret",
    )
    distributor = DistributorAgent(
        agent_id="distributor-1",
        coordinator_id="coordinator-1",
        redis_config=redis_config,
        a2a_config=distributor_a2a_config,
    )

    # Register distributor with router and coordinator
    a2a_router.register_agent("distributor-1", distributor.a2a_client)
    coordinator.register_distributor("distributor-1")

    logger.info("Initializing Distributor...")
    if not distributor.initialize():
        logger.error("Failed to initialize Distributor")
        return

    # Create Workers
    workers = []
    for i in range(2):
        worker_id = f"worker-{i+1}"
        worker_a2a_config = A2AConfig(
            agent_id=worker_id,
            agent_port=8003 + i,
            token_secret=f"worker-{i+1}-secret",
        )
        worker = WorkerAgent(
            agent_id=worker_id,
            distributor_id="distributor-1",
            a2a_config=worker_a2a_config,
        )

        a2a_router.register_agent(worker_id, worker.a2a_client)
        distributor.register_worker(worker_id)

        logger.info(f"Initializing {worker_id}...")
        if worker.initialize():
            workers.append(worker)

    logger.info("\n" + "="*80)
    logger.info("All agents initialized successfully!")
    logger.info("="*80 + "\n")

    # Example scenario: Assign tasks
    logger.info("SCENARIO: Coordinator assigns tasks")
    logger.info("-" * 80)

    # Create tasks
    tasks = [
        Task(
            task_id="task-1",
            task_type="compute",
            payload={"operation": "sum", "values": [1, 2, 3]},
        ),
        Task(
            task_id="task-2",
            task_type="data_processing",
            payload={"data": [1, 2, 3, 4, 5]},
        ),
    ]

    # Coordinator assigns tasks to distributor
    for i, task in enumerate(tasks):
        distributor_id = "distributor-1"
        logger.info(f"\n[Coordinator] Assigning {task.task_id} to {distributor_id}")
        coordinator.assign_task_to_distributor(task, distributor_id)

    # Simulate distributor processing assignments
    logger.info("\n[Distributor] Processing task assignments...")
    for task in coordinator.local_state.local_tasks:
        worker_idx = len(distributor.local_state.local_tasks) % len(workers)
        worker_id = workers[worker_idx].agent_id

        logger.info(
            f"[Distributor] Assigning {task.task_id} to {worker_id}"
        )
        distributor.assign_task_to_worker(task, worker_id)

    # Simulate workers executing tasks
    logger.info("\n" + "="*80)
    logger.info("WORKERS EXECUTING TASKS")
    logger.info("="*80)

    for worker in workers:
        pending_tasks = worker.local_state.get_pending_tasks()
        for task in pending_tasks:
            logger.info(f"\n[{worker.agent_id}] Executing {task.task_id}...")
            result = worker.execute_task(task)
            logger.info(f"[{worker.agent_id}] Result: {result}")

    # Simulate heartbeats
    logger.info("\n" + "="*80)
    logger.info("SENDING HEARTBEATS")
    logger.info("="*80 + "\n")

    for worker in workers:
        worker.send_heartbeat()

    # Display final state
    logger.info("\n" + "="*80)
    logger.info("FINAL STATE SUMMARY")
    logger.info("="*80)

    logger.info(f"\nCoordinator State:")
    logger.info(f"  - Status: {coordinator.local_state.status.value}")
    logger.info(f"  - Tasks Assigned: {len(coordinator.local_state.local_tasks)}")
    for task in coordinator.local_state.local_tasks:
        logger.info(f"    - {task.task_id}: {task.status.value}")

    logger.info(f"\nDistributor State:")
    logger.info(f"  - Status: {distributor.local_state.status.value}")
    logger.info(f"  - Local Tasks: {len(distributor.local_state.local_tasks)}")
    logger.info(f"  - Managed Workers: {len(distributor.managed_workers)}")
    for task in distributor.local_state.local_tasks:
        logger.info(f"    - {task.task_id}: {task.status.value}")

    logger.info(f"\nShared State (in Redis):")
    logger.info(f"  - Status: {distributor.shared_state.status.value}")
    logger.info(f"  - Assigned Workers: {distributor.shared_state.assigned_workers}")
    logger.info(f"  - Tasks: {len(distributor.shared_state.tasks)}")

    for worker in workers:
        logger.info(f"\n{worker.agent_id} State:")
        logger.info(f"  - Status: {worker.local_state.status.value}")
        logger.info(f"  - Tasks Executed: {len(worker.local_state.local_tasks)}")
        completed = [
            t for t in worker.local_state.local_tasks
            if t.status == TaskStatus.COMPLETED
        ]
        logger.info(f"  - Completed: {len(completed)}")
        for task in completed:
            logger.info(f"    - {task.task_id}: {task.status.value}")

    # Cleanup
    logger.info("\n" + "="*80)
    logger.info("CLEANUP")
    logger.info("="*80 + "\n")

    coordinator.cleanup()
    distributor.cleanup()
    for worker in workers:
        worker.cleanup()

    logger.info("\n" + "="*80)
    logger.info("Example completed successfully!")
    logger.info("="*80)


if __name__ == "__main__":
    run_example()
