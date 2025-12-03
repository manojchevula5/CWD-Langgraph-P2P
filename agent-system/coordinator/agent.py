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
        logger.info(f"[initialize] ENTRY - Initializing coordinator {self.agent_id}")
        try:
            # Connect to Redis
            logger.debug(f"[initialize] Connecting to Redis at {self.redis_client.config.host}:{self.redis_client.config.port}")
            self.redis_client.connect()
            logger.debug(f"[initialize] Redis connected successfully")

            # Subscribe to shared state updates
            logger.debug(f"[initialize] Subscribing to channel: shared:distributor:*:events")
            self.redis_client.subscribe(
                "shared:distributor:*:events",
                self._on_shared_state_update,
            )
            logger.debug(f"[initialize] Subscription successful")

            self.local_state.set_status(AgentStatus.IDLE)
            logger.info(f"[initialize] EXIT - Coordinator {self.agent_id} initialized, status=IDLE")
            return True
        except Exception as e:
            logger.error(f"[initialize] EXCEPTION - Failed to initialize coordinator: {e}", exc_info=True)
            return False

    def assign_task_to_distributor(
        self,
        task: Task,
        distributor_id: str,
    ) -> bool:
        """Assign a task to a distributor"""
        logger.info(f"[assign_task_to_distributor] ENTRY - task_id={task.task_id}, task_type={task.task_type}, distributor_id={distributor_id}, payload={task.payload}")
        try:
            # Update local state
            logger.debug(f"[assign_task_to_distributor] Adding task to local_state")
            self.local_state.add_task(task)
            self.task_assignments[task.task_id] = distributor_id
            logger.debug(f"[assign_task_to_distributor] State changes - task_assignments now has {len(self.task_assignments)} entries")

            # Send assignment via A2A
            logger.debug(f"[assign_task_to_distributor] Creating A2A message for {distributor_id}")
            message = self.a2a_client.create_message(
                distributor_id,
                {
                    "action": "assign_task",
                    "task": task.to_dict(),
                },
                MessageType.REQUEST,
            )
            logger.debug(f"[assign_task_to_distributor] Message created - message_id={message.metadata.request_id}, signature_len={len(message.signature) if message.signature else 0}")

            logger.info(f"[assign_task_to_distributor] Sending message to {distributor_id}")
            self.a2a_client._send(message)
            logger.debug(f"[assign_task_to_distributor] Message sent successfully")

            # Add to history
            logger.debug(f"[assign_task_to_distributor] Adding history entry")
            self.local_state.add_history_entry(
                {
                    "action": "assign_task",
                    "task_id": task.task_id,
                    "distributor_id": distributor_id,
                }
            )

            logger.info(f"[assign_task_to_distributor] EXIT SUCCESS - task {task.task_id} assigned to {distributor_id}")
            return True
        except Exception as e:
            logger.error(f"[assign_task_to_distributor] EXCEPTION - Failed to assign task {task.task_id}: {e}", exc_info=True)
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
        logger.info(f"[register_distributor] ENTRY - distributor_id={distributor_id}")
        try:
            logger.debug(f"[register_distributor] Creating distributor entry in managed_distributors")
            self.managed_distributors[distributor_id] = {
                "status": AgentStatus.IDLE.value,
                "last_heartbeat": datetime.utcnow().isoformat(),
                "worker_count": 0,
            }
            logger.debug(f"[register_distributor] Distributor entry created - status=IDLE, worker_count=0")

            # Initialize shared state in Redis
            shared_key = f"shared:distributor:{distributor_id}"
            shared_state = SharedAgentState()
            logger.debug(f"[register_distributor] Setting shared state in Redis - key={shared_key}")
            self.redis_client.set(shared_key, json.dumps(shared_state.to_dict()))
            logger.debug(f"[register_distributor] Shared state set in Redis successfully")

            logger.info(f"[register_distributor] EXIT SUCCESS - Registered distributor {distributor_id}, total_distributors={len(self.managed_distributors)}")
            return True
        except Exception as e:
            logger.error(f"[register_distributor] EXCEPTION - Failed to register distributor {distributor_id}: {e}", exc_info=True)
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
        logger.info(f"[_on_shared_state_update] ENTRY - channel={channel}, data={data}")
        try:
            logger.debug(f"[_on_shared_state_update] Parsing channel name")

            # Extract distributor ID from channel
            parts = channel.split(":")
            if len(parts) >= 3:
                distributor_id = parts[2]
                logger.debug(f"[_on_shared_state_update] Extracted distributor_id={distributor_id}")

                # Fetch updated state
                logger.debug(f"[_on_shared_state_update] Fetching updated state")
                updated_state = self.get_distributor_state(distributor_id)
                if updated_state:
                    logger.debug(f"[_on_shared_state_update] State fetched - status={updated_state.status.value}, tasks={len(updated_state.tasks)}")
                    
                    # Update local tracking
                    if distributor_id in self.managed_distributors:
                        old_status = self.managed_distributors[distributor_id]["status"]
                        self.managed_distributors[distributor_id]["status"] = (
                            updated_state.status.value
                        )
                        logger.debug(f"[_on_shared_state_update] Updated local tracking - status change: {old_status} -> {updated_state.status.value}")

                    # React to state changes
                    logger.debug(f"[_on_shared_state_update] Reconciling state")
                    self._reconcile_distributor_state(distributor_id, updated_state)
                    logger.info(f"[_on_shared_state_update] EXIT SUCCESS - Update handled for {distributor_id}")
                else:
                    logger.debug(f"[_on_shared_state_update] No state found for {distributor_id}")
            else:
                logger.warning(f"[_on_shared_state_update] Invalid channel format: {channel}")
        except Exception as e:
            logger.error(f"[_on_shared_state_update] EXCEPTION - Error handling shared state update on {channel}: {e}", exc_info=True)

    def _reconcile_distributor_state(
        self,
        distributor_id: str,
        shared_state: SharedAgentState,
    ):
        """Reconcile local state with distributor's shared state"""
        logger.info(f"[_reconcile_distributor_state] ENTRY - distributor_id={distributor_id}, shared_tasks={len(shared_state.tasks)}")

        # Update task statuses based on shared state
        reconciliation_updates = []
        for task in shared_state.tasks:
            if task.task_id in self.task_assignments:
                # Update local copy
                logger.debug(f"[_reconcile_distributor_state] Updating task {task.task_id}")
                local_task = self.local_state.get_task(task.task_id)
                if local_task:
                    old_status = local_task.status.value
                    local_task.status = task.status
                    local_task.updated_at = task.updated_at
                    reconciliation_updates.append({
                        "task_id": task.task_id,
                        "old_status": old_status,
                        "new_status": task.status.value
                    })
                    logger.debug(f"[_reconcile_distributor_state] Task {task.task_id} status updated: {old_status} -> {task.status.value}")

        # Add to history
        logger.debug(f"[_reconcile_distributor_state] Adding history entry with {len(reconciliation_updates)} updates")
        self.local_state.add_history_entry(
            {
                "action": "reconcile_distributor_state",
                "distributor_id": distributor_id,
                "timestamp": datetime.utcnow().isoformat(),
                "updates": reconciliation_updates,
            }
        )
        logger.info(f"[_reconcile_distributor_state] EXIT SUCCESS - Reconciliation complete for {distributor_id}, {len(reconciliation_updates)} tasks updated")

    def _recover_from_snapshot(self, distributor_id: str):
        """Recover distributor state from Redis snapshot"""
        logger.info(f"[_recover_from_snapshot] ENTRY - distributor_id={distributor_id}")
        logger.warning(f"[_recover_from_snapshot] Heartbeat timeout detected for {distributor_id}, attempting recovery")

        shared_state = self.get_distributor_state(distributor_id)
        if shared_state:
            logger.debug(f"[_recover_from_snapshot] Snapshot retrieved - tasks={len(shared_state.tasks)}, status={shared_state.status.value}")
            
            # Send recovery request to distributor
            logger.debug(f"[_recover_from_snapshot] Creating recovery request message")
            message = self.a2a_client.create_message(
                distributor_id,
                {"action": "recover", "timestamp": datetime.utcnow().isoformat()},
                MessageType.REQUEST,
            )
            logger.debug(f"[_recover_from_snapshot] Sending recovery request - message_id={message.metadata.request_id}")
            self.a2a_client._send(message)
            logger.info(f"[_recover_from_snapshot] Recovery request sent")

            logger.debug(f"[_recover_from_snapshot] Adding recovery history entry")
            self.local_state.add_history_entry(
                {
                    "action": "recover_distributor",
                    "distributor_id": distributor_id,
                    "timestamp": datetime.utcnow().isoformat(),
                    "snapshot_tasks": len(shared_state.tasks),
                }
            )
            logger.info(f"[_recover_from_snapshot] EXIT SUCCESS - Recovery initiated for {distributor_id}")
        else:
            logger.error(f"[_recover_from_snapshot] No snapshot found for {distributor_id}")

    def _handle_response(self, message):
        """Handle response messages from distributors"""
        logger.info(f"[_handle_response] ENTRY - sender={message.sender}, request_id={message.metadata.request_id}, success={message.payload.get('success')}")

        if message.payload.get("success"):
            # Handle successful response
            logger.debug(f"[_handle_response] Processing successful response from {message.sender}")
            logger.info(f"[_handle_response] EXIT SUCCESS - Response handled")
        else:
            # Handle error response
            logger.error(f"[_handle_response] Error response from {message.sender}: {message.payload}")
            logger.info(f"[_handle_response] EXIT ERROR - Error handled")

    def _handle_heartbeat(self, message):
        """Handle heartbeat messages from distributors"""
        logger.debug(f"[_handle_heartbeat] ENTRY - sender={message.sender}, payload={message.payload}")
        if message.sender in self.managed_distributors:
            old_heartbeat = self.managed_distributors[message.sender]["last_heartbeat"]
            self.managed_distributors[message.sender]["last_heartbeat"] = (
                datetime.utcnow().isoformat()
            )
            status = message.payload.get("status", {})
            old_status = self.managed_distributors[message.sender]["status"]
            self.managed_distributors[message.sender]["status"] = status.get("state", "idle")
            logger.debug(f"[_handle_heartbeat] Heartbeat updated - status {old_status} -> {status.get('state', 'idle')}, last_heartbeat refreshed")
            logger.debug(f"[_handle_heartbeat] EXIT SUCCESS")
        else:
            logger.warning(f"[_handle_heartbeat] Unknown distributor {message.sender}, heartbeat ignored")

    def _handle_event(self, message):
        """Handle event messages from distributors"""
        event_type = message.payload.get("event_type")
        event_data = message.payload.get("event_data", {})
        logger.info(f"[_handle_event] ENTRY - event_type={event_type}, sender={message.sender}, data_keys={list(event_data.keys())}")

        logger.debug(f"[_handle_event] Adding event to history")
        self.local_state.add_history_entry(
            {
                "action": "receive_event",
                "event_type": event_type,
                "from": message.sender,
                "data": event_data,
            }
        )
        logger.info(f"[_handle_event] EXIT SUCCESS - Event {event_type} processed")

    def process_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process an incoming message"""
        logger.debug(f"[process_message] ENTRY - message_type={message.get('type')}")
        logger.debug(f"[process_message] EXIT SUCCESS")
        return {"status": "processed"}

    def execute_task(self, task: Task) -> Dict[str, Any]:
        """Execute a task (Coordinator doesn't execute tasks, it assigns them)"""
        logger.warning(f"[execute_task] ENTRY - task_id={task.task_id} - Coordinator does not execute tasks")
        logger.warning(f"[execute_task] EXIT ERROR - Task execution not supported on Coordinator")
        return {"status": "error", "message": "Coordinator does not execute tasks"}

    def cleanup(self):
        """Cleanup resources"""
        logger.info(f"[cleanup] ENTRY - Cleaning up coordinator {self.agent_id}")
        logger.debug(f"[cleanup] Current state - distributors={len(self.managed_distributors)}, task_assignments={len(self.task_assignments)}")
        logger.debug(f"[cleanup] Disconnecting Redis")
        self.redis_client.disconnect()
        logger.info(f"[cleanup] EXIT SUCCESS - Coordinator {self.agent_id} cleaned up")
