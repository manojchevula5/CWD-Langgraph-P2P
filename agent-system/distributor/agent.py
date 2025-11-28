"""
Distributor Agent (Level 2)
Responsible for:
- Receiving tasks from Coordinator
- Distributing work to Workers
- Maintaining shared state with Coordinator
- Managing Worker lifecycle
"""

import logging
import json
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from core.langgraph_state import (
    LangGraphAgent,
    LocalAgentState,
    SharedAgentState,
    Task,
    TaskStatus,
    AgentStatus,
)
from core.redis_client import RedisClient, RedisConfig
from core.a2a_messaging import A2AClient, A2AConfig, MessageType

logger = logging.getLogger(__name__)


class DistributorAgent(LangGraphAgent):
    """Distributor agent implementation"""

    def __init__(
        self,
        agent_id: str,
        coordinator_id: str,
        redis_config: RedisConfig,
        a2a_config: A2AConfig,
    ):
        super().__init__(agent_id)
        self.coordinator_id = coordinator_id
        self.redis_client = RedisClient(redis_config)
        self.a2a_client = A2AClient(a2a_config)
        self.managed_workers: Dict[str, Dict[str, Any]] = {}
        self.shared_state_key = f"shared:distributor:{agent_id}"
        self.shared_state = SharedAgentState()
        self.lease_key = f"shared:distributor:{agent_id}:lease"

        # Register message handlers
        self.a2a_client.register_handler(MessageType.REQUEST, self._handle_request)
        self.a2a_client.register_handler(MessageType.RESPONSE, self._handle_response)
        self.a2a_client.register_handler(MessageType.HEARTBEAT, self._handle_heartbeat)

    def initialize(self) -> bool:
        """Initialize distributor"""
        try:
            # Connect to Redis
            self.redis_client.connect()

            # Initialize shared state
            self._update_shared_state()

            # Subscribe to shared state updates from coordinator
            self.redis_client.subscribe(
                f"{self.shared_state_key}:updates",
                self._on_coordinator_update,
            )

            self.local_state.set_status(AgentStatus.IDLE)
            logger.info(f"Distributor {self.agent_id} initialized")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize distributor: {e}")
            return False

    def register_worker(self, worker_id: str) -> bool:
        """Register a worker"""
        try:
            self.managed_workers[worker_id] = {
                "status": AgentStatus.IDLE.value,
                "last_heartbeat": datetime.utcnow().isoformat(),
                "assigned_tasks": [],
            }

            self.shared_state.assign_worker(worker_id)
            self._update_shared_state()

            logger.info(f"Worker {worker_id} registered")
            return True
        except Exception as e:
            logger.error(f"Failed to register worker: {e}")
            return False

    def assign_task_to_worker(self, task: Task, worker_id: str) -> bool:
        """Assign a task to a worker"""
        try:
            # Update local state
            self.local_state.add_task(task)

            # Update shared state
            self.shared_state.add_task(task)
            self._update_shared_state()

            # Send assignment via A2A
            message = self.a2a_client.create_message(
                worker_id,
                {
                    "action": "assign_task",
                    "task": task.to_dict(),
                },
                MessageType.REQUEST,
            )

            logger.info(f"Assigning task {task.task_id} to {worker_id}")
            self.a2a_client._send(message)

            # Track assignment
            if worker_id in self.managed_workers:
                self.managed_workers[worker_id]["assigned_tasks"].append(task.task_id)

            self.local_state.add_history_entry(
                {
                    "action": "assign_task",
                    "task_id": task.task_id,
                    "worker_id": worker_id,
                }
            )

            return True
        except Exception as e:
            logger.error(f"Failed to assign task to worker: {e}")
            return False

    def acquire_shared_state_lease(self) -> bool:
        """Acquire exclusive lease on shared state"""
        return self.redis_client.acquire_lease(
            self.lease_key,
            self.agent_id,
            ttl=10,
        )

    def renew_shared_state_lease(self) -> bool:
        """Renew the shared state lease"""
        return self.redis_client.renew_lease(
            self.lease_key,
            self.agent_id,
            ttl=10,
        )

    def _update_shared_state(self, publish_event: bool = True) -> bool:
        """Update shared state in Redis with optimistic concurrency"""
        try:
            def merge_state(current_obj: Dict) -> Dict:
                """Merge function for optimistic concurrency"""
                # Extract current task list
                current_tasks = current_obj.get("tasks", [])

                # Rebuild with new state
                updated = self.shared_state.to_dict()
                updated["distributor_version"] = self.shared_state.distributor_version

                return updated

            result = self.redis_client.transaction(self.shared_state_key, merge_state)

            if result:
                self.local_state.update_timestamp()

                # Publish event if requested
                if publish_event:
                    self.redis_client.publish(
                        f"{self.shared_state_key}:events",
                        {
                            "who": "distributor",
                            "timestamp": datetime.utcnow().isoformat(),
                            "action": "state_update",
                        },
                    )

                logger.info(f"Shared state updated for {self.agent_id}")
                return True
            else:
                logger.error(f"Failed to update shared state for {self.agent_id}")
                return False
        except Exception as e:
            logger.error(f"Error updating shared state: {e}")
            return False

    def _on_coordinator_update(self, channel: str, data: Any):
        """Handle updates from Coordinator via Redis"""
        try:
            logger.info(f"Received coordinator update on {channel}")

            # Fetch latest shared state
            state_json = self.redis_client.get(self.shared_state_key)
            if state_json:
                if isinstance(state_json, dict):
                    state_dict = state_json
                else:
                    state_dict = json.loads(state_json)

                self.shared_state = SharedAgentState(
                    coordinator_version=state_dict.get("coordinator_version", "v1"),
                    distributor_version=state_dict.get("distributor_version", "v1"),
                    status=AgentStatus(state_dict.get("status", "idle")),
                    assigned_workers=state_dict.get("assigned_workers", []),
                    tasks=[
                        Task(
                            task_id=t["task_id"],
                            task_type=t["task_type"],
                            payload=t["payload"],
                            status=TaskStatus(t["status"]),
                        )
                        for t in state_dict.get("tasks", [])
                    ],
                )

                # React to changes
                self._reconcile_coordinator_state()
        except Exception as e:
            logger.error(f"Error handling coordinator update: {e}")

    def _reconcile_coordinator_state(self):
        """Reconcile with latest coordinator state"""
        logger.info(f"Reconciling with coordinator state")

        # Update local state based on shared state
        for shared_task in self.shared_state.tasks:
            local_task = self.local_state.get_task(shared_task.task_id)
            if not local_task:
                self.local_state.add_task(shared_task)
            else:
                # Sync status if changed
                if local_task.status != shared_task.status:
                    local_task.status = shared_task.status

        self.local_state.add_history_entry(
            {
                "action": "reconcile_coordinator",
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    def monitor_workers(self):
        """Monitor health of all workers"""
        for worker_id, worker_info in self.managed_workers.items():
            last_heartbeat = worker_info.get("last_heartbeat")
            if last_heartbeat:
                time_since_heartbeat = datetime.utcnow() - datetime.fromisoformat(
                    last_heartbeat
                )
                if time_since_heartbeat > timedelta(seconds=60):
                    logger.warning(f"Worker {worker_id} heartbeat timeout")
                    # Mark worker as unavailable and reassign tasks
                    self._handle_worker_failure(worker_id)

    def _handle_worker_failure(self, worker_id: str):
        """Handle worker failure"""
        try:
            logger.info(f"Handling failure of {worker_id}")

            # Get assigned tasks
            assigned_tasks = self.managed_workers.get(worker_id, {}).get(
                "assigned_tasks", []
            )

            # Mark tasks as failed in local state
            for task_id in assigned_tasks:
                task = self.local_state.get_task(task_id)
                if task and task.status == TaskStatus.IN_PROGRESS:
                    task.mark_failed(f"Worker {worker_id} failed")

            # Update shared state
            self._update_shared_state()

            # Notify coordinator of failures
            failed_tasks = [task_id for task_id in assigned_tasks]
            message = self.a2a_client.create_message(
                self.coordinator_id,
                {
                    "action": "worker_failure",
                    "worker_id": worker_id,
                    "failed_tasks": failed_tasks,
                },
                MessageType.EVENT,
            )
            self.a2a_client._send(message)

            self.local_state.add_history_entry(
                {
                    "action": "worker_failure",
                    "worker_id": worker_id,
                    "failed_tasks": failed_tasks,
                }
            )
        except Exception as e:
            logger.error(f"Error handling worker failure: {e}")

    def _handle_request(self, message):
        """Handle request messages from Coordinator"""
        action = message.payload.get("action")
        logger.info(f"Received request from {message.sender}: {action}")

        if action == "assign_task":
            task_data = message.payload.get("task", {})
            task = Task(
                task_id=task_data.get("task_id"),
                task_type=task_data.get("task_type"),
                payload=task_data.get("payload", {}),
            )

            # Add to local state
            self.local_state.add_task(task)

            # Send response
            self.a2a_client.send_response(
                message.sender,
                message.metadata.request_id,
                {"task_id": task.task_id, "status": "received"},
            )

    def _handle_response(self, message):
        """Handle response messages from workers"""
        logger.info(f"Received response from {message.sender}")

        if message.payload.get("success"):
            # Handle successful response
            pass
        else:
            logger.error(f"Error response from {message.sender}: {message.payload}")

    def _handle_heartbeat(self, message):
        """Handle heartbeat messages from workers"""
        if message.sender in self.managed_workers:
            self.managed_workers[message.sender]["last_heartbeat"] = (
                datetime.utcnow().isoformat()
            )
            status = message.payload.get("status", {})
            self.managed_workers[message.sender]["status"] = status.get("state", "idle")

    def process_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process an incoming message"""
        logger.info(f"Processing message: {message.get('type')}")
        return {"status": "processed"}

    def execute_task(self, task: Task) -> Dict[str, Any]:
        """Execute a task (Distributor assigns, doesn't execute)"""
        logger.info(f"Cannot execute task {task.task_id} - Distributor only assigns")
        return {"status": "error", "message": "Distributor does not execute tasks"}

    def cleanup(self):
        """Cleanup resources"""
        self.redis_client.release_lease(self.lease_key, self.agent_id)
        self.redis_client.disconnect()
        logger.info(f"Distributor {self.agent_id} cleaned up")
