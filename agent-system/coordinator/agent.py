"""
Coordinator Agent (Level 1)
Responsible for:
- High-level task assignment
- Monitoring Distributors
- Managing shared state with Distributors
- Making global scheduling decisions
"""

import logging
import json
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
import asyncio
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


class CoordinatorAgent(LangGraphAgent):
    """Coordinator agent implementation"""

    def __init__(
        self,
        agent_id: str,
        redis_config: RedisConfig,
        a2a_config: A2AConfig,
    ):
        super().__init__(agent_id)
        self.redis_client = RedisClient(redis_config)
        self.a2a_client = A2AClient(a2a_config)
        self.managed_distributors: Dict[str, Dict[str, Any]] = {}
        self.task_assignments: Dict[str, str] = {}  # task_id -> distributor_id

        # Register message handlers
        self.a2a_client.register_handler(MessageType.RESPONSE, self._handle_response)
        self.a2a_client.register_handler(MessageType.HEARTBEAT, self._handle_heartbeat)
        self.a2a_client.register_handler(MessageType.EVENT, self._handle_event)

    def initialize(self) -> bool:
        """Initialize coordinator"""
        try:
            # Connect to Redis
            self.redis_client.connect()

            # Subscribe to shared state updates
            self.redis_client.subscribe(
                "shared:distributor:*:events",
                self._on_shared_state_update,
            )

            self.local_state.set_status(AgentStatus.IDLE)
            logger.info(f"Coordinator {self.agent_id} initialized")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize coordinator: {e}")
            return False

    def assign_task_to_distributor(
        self,
        task: Task,
        distributor_id: str,
    ) -> bool:
        """Assign a task to a distributor"""
        try:
            # Update local state
            self.local_state.add_task(task)
            self.task_assignments[task.task_id] = distributor_id

            # Send assignment via A2A
            message = self.a2a_client.create_message(
                distributor_id,
                {
                    "action": "assign_task",
                    "task": task.to_dict(),
                },
                MessageType.REQUEST,
            )

            logger.info(f"Assigning task {task.task_id} to {distributor_id}")
            self.a2a_client._send(message)

            # Add to history
            self.local_state.add_history_entry(
                {
                    "action": "assign_task",
                    "task_id": task.task_id,
                    "distributor_id": distributor_id,
                }
            )

            return True
        except Exception as e:
            logger.error(f"Failed to assign task: {e}")
            return False

    def monitor_distributors(self):
        """Monitor health of all distributors"""
        for distributor_id, distributor_info in self.managed_distributors.items():
            last_heartbeat = distributor_info.get("last_heartbeat")
            if last_heartbeat:
                time_since_heartbeat = datetime.utcnow() - datetime.fromisoformat(
                    last_heartbeat
                )
                if time_since_heartbeat > timedelta(seconds=60):
                    logger.warning(
                        f"Distributor {distributor_id} heartbeat timeout"
                    )
                    # Attempt recovery from Redis snapshot
                    self._recover_from_snapshot(distributor_id)

    def register_distributor(self, distributor_id: str) -> bool:
        """Register a distributor for monitoring"""
        try:
            self.managed_distributors[distributor_id] = {
                "status": AgentStatus.IDLE.value,
                "last_heartbeat": datetime.utcnow().isoformat(),
                "worker_count": 0,
            }

            # Initialize shared state in Redis
            shared_key = f"shared:distributor:{distributor_id}"
            shared_state = SharedAgentState()
            self.redis_client.set(shared_key, json.dumps(shared_state.to_dict()))

            logger.info(f"Registered distributor {distributor_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to register distributor: {e}")
            return False

    def get_distributor_state(self, distributor_id: str) -> Optional[SharedAgentState]:
        """Get shared state of a distributor from Redis"""
        try:
            shared_key = f"shared:distributor:{distributor_id}"
            state_json = self.redis_client.get(shared_key)
            if not state_json:
                return None

            if isinstance(state_json, dict):
                state_dict = state_json
            else:
                state_dict = json.loads(state_json)

            shared_state = SharedAgentState(
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
                lease=state_dict.get("lease"),
            )
            return shared_state
        except Exception as e:
            logger.error(f"Failed to get distributor state: {e}")
            return None

    def _on_shared_state_update(self, channel: str, data: Any):
        """Handle shared state updates from Redis"""
        try:
            logger.info(f"Received shared state update on {channel}")

            # Extract distributor ID from channel
            parts = channel.split(":")
            if len(parts) >= 3:
                distributor_id = parts[2]

                # Fetch updated state
                updated_state = self.get_distributor_state(distributor_id)
                if updated_state:
                    # Update local tracking
                    if distributor_id in self.managed_distributors:
                        self.managed_distributors[distributor_id]["status"] = (
                            updated_state.status.value
                        )

                    # React to state changes
                    self._reconcile_distributor_state(distributor_id, updated_state)
        except Exception as e:
            logger.error(f"Error handling shared state update: {e}")

    def _reconcile_distributor_state(
        self,
        distributor_id: str,
        shared_state: SharedAgentState,
    ):
        """Reconcile local state with distributor's shared state"""
        logger.info(f"Reconciling state for {distributor_id}")

        # Update task statuses based on shared state
        for task in shared_state.tasks:
            if task.task_id in self.task_assignments:
                # Update local copy
                local_task = self.local_state.get_task(task.task_id)
                if local_task:
                    local_task.status = task.status
                    local_task.updated_at = task.updated_at

        # Add to history
        self.local_state.add_history_entry(
            {
                "action": "reconcile_distributor_state",
                "distributor_id": distributor_id,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    def _recover_from_snapshot(self, distributor_id: str):
        """Recover distributor state from Redis snapshot"""
        logger.info(f"Attempting recovery for {distributor_id}")

        shared_state = self.get_distributor_state(distributor_id)
        if shared_state:
            # Send recovery request to distributor
            message = self.a2a_client.create_message(
                distributor_id,
                {"action": "recover", "timestamp": datetime.utcnow().isoformat()},
                MessageType.REQUEST,
            )
            self.a2a_client._send(message)

            self.local_state.add_history_entry(
                {
                    "action": "recover_distributor",
                    "distributor_id": distributor_id,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )

    def _handle_response(self, message):
        """Handle response messages from distributors"""
        logger.info(f"Received response from {message.sender}")

        if message.payload.get("success"):
            # Handle successful response
            pass
        else:
            # Handle error response
            logger.error(f"Error response from {message.sender}: {message.payload}")

    def _handle_heartbeat(self, message):
        """Handle heartbeat messages from distributors"""
        if message.sender in self.managed_distributors:
            self.managed_distributors[message.sender]["last_heartbeat"] = (
                datetime.utcnow().isoformat()
            )
            status = message.payload.get("status", {})
            self.managed_distributors[message.sender]["status"] = status.get("state", "idle")

    def _handle_event(self, message):
        """Handle event messages from distributors"""
        event_type = message.payload.get("event_type")
        event_data = message.payload.get("event_data", {})
        logger.info(f"Received event {event_type} from {message.sender}")

        self.local_state.add_history_entry(
            {
                "action": "receive_event",
                "event_type": event_type,
                "from": message.sender,
                "data": event_data,
            }
        )

    def process_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process an incoming message"""
        logger.info(f"Processing message: {message.get('type')}")
        return {"status": "processed"}

    def execute_task(self, task: Task) -> Dict[str, Any]:
        """Execute a task (Coordinator doesn't execute tasks, it assigns them)"""
        logger.info(f"Cannot execute task {task.task_id} - Coordinator only assigns")
        return {"status": "error", "message": "Coordinator does not execute tasks"}

    def cleanup(self):
        """Cleanup resources"""
        self.redis_client.disconnect()
        logger.info(f"Coordinator {self.agent_id} cleaned up")
