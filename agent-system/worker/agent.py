"""
Worker Agent (Level 3)
Responsible for:
- Executing assigned tasks
- Maintaining local state
- Reporting status to Distributor
- No Redis involvement (only A2A communication)
"""

import logging
import json
import time
from typing import Any, Dict, Optional
from datetime import datetime
from core.langgraph_state import (
    LangGraphAgent,
    LocalAgentState,
    Task,
    TaskStatus,
    AgentStatus,
)
from core.a2a_messaging import A2AClient, A2AConfig, MessageType

logger = logging.getLogger(__name__)


class WorkerAgent(LangGraphAgent):
    """Worker agent implementation"""

    def __init__(
        self,
        agent_id: str,
        distributor_id: str,
        a2a_config: A2AConfig,
    ):
        super().__init__(agent_id)
        self.distributor_id = distributor_id
        self.a2a_client = A2AClient(a2a_config)
        self.current_task: Optional[Task] = None
        self._running = False

        # Register message handlers
        self.a2a_client.register_handler(MessageType.REQUEST, self._handle_request)
        self.a2a_client.register_handler(MessageType.HEARTBEAT, self._handle_heartbeat)

    def initialize(self) -> bool:
        """Initialize worker"""
        try:
            self.local_state.set_status(AgentStatus.IDLE)
            self._running = True

            # Send initialization message to distributor
            message = self.a2a_client.create_message(
                self.distributor_id,
                {
                    "action": "register",
                    "worker_id": self.agent_id,
                    "timestamp": datetime.utcnow().isoformat(),
                },
                MessageType.EVENT,
            )
            self.a2a_client._send(message)

            logger.info(f"Worker {self.agent_id} initialized")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize worker: {e}")
            return False

    def process_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process an incoming message"""
        logger.info(f"Processing message: {message.get('type')}")
        return {"status": "processed"}

    def execute_task(self, task: Task) -> Dict[str, Any]:
        """Execute a task (Worker's primary responsibility)"""
        try:
            logger.info(f"Executing task {task.task_id}")

            # Update local state
            task.mark_started()
            self.current_task = task
            self.local_state.set_status(AgentStatus.BUSY)

            # Simulate task execution (in real scenario, this would be actual work)
            task_type = task.task_type
            if task_type == "compute":
                result = self._execute_compute_task(task)
            elif task_type == "data_processing":
                result = self._execute_data_processing_task(task)
            else:
                result = self._execute_generic_task(task)

            # Mark task as completed
            task.mark_completed(result)
            self.local_state.set_status(AgentStatus.IDLE)

            # Report completion to distributor
            self._report_task_completion(task, result)

            self.local_state.add_history_entry(
                {
                    "action": "execute_task",
                    "task_id": task.task_id,
                    "status": "completed",
                }
            )

            return result
        except Exception as e:
            logger.error(f"Error executing task: {e}")
            task.mark_failed(str(e))
            self.local_state.set_status(AgentStatus.ERROR)
            self._report_task_failure(task, str(e))
            return {"status": "error", "error": str(e)}

    def _execute_compute_task(self, task: Task) -> Dict[str, Any]:
        """Execute a compute-type task"""
        logger.info(f"Executing compute task: {task.task_id}")

        # Simulate computation
        time.sleep(1)

        return {
            "status": "success",
            "task_type": "compute",
            "result": {"computed_value": 42},
            "executed_at": datetime.utcnow().isoformat(),
        }

    def _execute_data_processing_task(self, task: Task) -> Dict[str, Any]:
        """Execute a data processing task"""
        logger.info(f"Executing data processing task: {task.task_id}")

        # Get payload data
        payload = task.payload or {}
        data = payload.get("data", [])

        # Simulate data processing
        time.sleep(1)
        processed_data = [x * 2 for x in data] if isinstance(data, list) else data

        return {
            "status": "success",
            "task_type": "data_processing",
            "result": {"processed_data": processed_data},
            "executed_at": datetime.utcnow().isoformat(),
        }

    def _execute_generic_task(self, task: Task) -> Dict[str, Any]:
        """Execute a generic task"""
        logger.info(f"Executing generic task: {task.task_id}")

        # Simulate generic work
        time.sleep(1)

        return {
            "status": "success",
            "task_type": task.task_type,
            "result": {"message": "Task completed"},
            "executed_at": datetime.utcnow().isoformat(),
        }

    def _report_task_completion(self, task: Task, result: Dict[str, Any]):
        """Report task completion to distributor"""
        try:
            message = self.a2a_client.create_message(
                self.distributor_id,
                {
                    "action": "task_completed",
                    "task_id": task.task_id,
                    "result": result,
                },
                MessageType.EVENT,
            )
            self.a2a_client._send(message)
            logger.info(f"Task completion reported for {task.task_id}")
        except Exception as e:
            logger.error(f"Failed to report task completion: {e}")

    def _report_task_failure(self, task: Task, error: str):
        """Report task failure to distributor"""
        try:
            message = self.a2a_client.create_message(
                self.distributor_id,
                {
                    "action": "task_failed",
                    "task_id": task.task_id,
                    "error": error,
                },
                MessageType.EVENT,
            )
            self.a2a_client._send(message)
            logger.info(f"Task failure reported for {task.task_id}")
        except Exception as e:
            logger.error(f"Failed to report task failure: {e}")

    def send_heartbeat(self) -> bool:
        """Send heartbeat to distributor"""
        try:
            task_status = None
            if self.current_task:
                task_status = {
                    "task_id": self.current_task.task_id,
                    "status": self.current_task.status.value,
                }

            message = self.a2a_client.send_heartbeat(
                self.distributor_id,
                {
                    "state": self.local_state.status.value,
                    "uptime": (datetime.utcnow() - datetime.fromisoformat(
                        self.local_state.created_at
                    )).total_seconds(),
                    "current_task": task_status,
                    "completed_tasks": len([
                        t for t in self.local_state.local_tasks
                        if t.status == TaskStatus.COMPLETED
                    ]),
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send heartbeat: {e}")
            return False

    def _handle_request(self, message):
        """Handle request messages from distributor"""
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
                {"task_id": task.task_id, "status": "accepted"},
            )

            # Execute the task
            self.execute_task(task)

    def _handle_heartbeat(self, message):
        """Handle heartbeat messages (for future use)"""
        logger.debug(f"Received heartbeat from {message.sender}")

    def cleanup(self):
        """Cleanup resources"""
        self._running = False
        logger.info(f"Worker {self.agent_id} cleaned up")
