"""
LangGraph state management for agents.
Each agent maintains its own LangGraph state with local tasks, metadata, and history.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """Task status states"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ABANDONED = "abandoned"


class AgentStatus(str, Enum):
    """Agent status states"""
    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"
    RECOVERING = "recovering"


@dataclass
class Task:
    """Represents a task in the agent state"""
    task_id: str
    task_type: str
    payload: Dict[str, Any]
    status: TaskStatus = TaskStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    retry_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)

    def mark_started(self):
        """Mark task as started"""
        self.status = TaskStatus.IN_PROGRESS
        self.started_at = datetime.utcnow().isoformat()
        self.updated_at = datetime.utcnow().isoformat()

    def mark_completed(self, result: Dict[str, Any]):
        """Mark task as completed"""
        self.status = TaskStatus.COMPLETED
        self.completed_at = datetime.utcnow().isoformat()
        self.updated_at = datetime.utcnow().isoformat()
        self.result = result

    def mark_failed(self, error: str):
        """Mark task as failed"""
        self.status = TaskStatus.FAILED
        self.error = error
        self.updated_at = datetime.utcnow().isoformat()
        self.retry_count += 1

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class LocalAgentState:
    """Local LangGraph state for each agent"""
    agent_id: str
    status: AgentStatus = AgentStatus.IDLE
    local_tasks: List[Task] = field(default_factory=list)
    last_heartbeat: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    local_vars: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict:
        return {
            "agent_id": self.agent_id,
            "status": self.status.value,
            "local_tasks": [t.to_dict() for t in self.local_tasks],
            "last_heartbeat": self.last_heartbeat,
            "local_vars": self.local_vars,
            "history": self.history,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    def update_timestamp(self):
        """Update the last modified timestamp"""
        self.updated_at = datetime.utcnow().isoformat()
        self.last_heartbeat = datetime.utcnow().isoformat()

    def add_task(self, task: Task):
        """Add a task to the local state"""
        self.local_tasks.append(task)
        self.update_timestamp()
        logger.info(f"Task {task.task_id} added to {self.agent_id}")

    def update_task(self, task_id: str, task_update: Dict[str, Any]):
        """Update a task in the local state"""
        for task in self.local_tasks:
            if task.task_id == task_id:
                for key, value in task_update.items():
                    if key == "status":
                        task.status = TaskStatus(value)
                    else:
                        setattr(task, key, value)
                task.updated_at = datetime.utcnow().isoformat()
                self.update_timestamp()
                logger.info(f"Task {task_id} updated in {self.agent_id}")
                return True
        return False

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID"""
        for task in self.local_tasks:
            if task.task_id == task_id:
                return task
        return None

    def set_local_var(self, key: str, value: Any):
        """Set a local variable"""
        self.local_vars[key] = value
        self.update_timestamp()

    def get_local_var(self, key: str) -> Optional[Any]:
        """Get a local variable"""
        return self.local_vars.get(key)

    def add_history_entry(self, entry: Dict[str, Any]):
        """Add an entry to the history"""
        entry["timestamp"] = datetime.utcnow().isoformat()
        self.history.append(entry)
        self.update_timestamp()

    def set_status(self, status: AgentStatus):
        """Set agent status"""
        self.status = status
        self.update_timestamp()
        logger.info(f"Agent {self.agent_id} status changed to {status.value}")


@dataclass
class SharedAgentState:
    """Shared state between Coordinator and Distributor (stored in Redis)"""
    coordinator_version: str = "v1"
    distributor_version: str = "v1"
    status: AgentStatus = AgentStatus.IDLE
    assigned_workers: List[str] = field(default_factory=list)
    tasks: List[Task] = field(default_factory=list)
    lease: Optional[Dict[str, str]] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "coordinator_version": self.coordinator_version,
            "distributor_version": self.distributor_version,
            "status": self.status.value,
            "assigned_workers": self.assigned_workers,
            "tasks": [t.to_dict() for t in self.tasks],
            "lease": self.lease,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    def update_timestamp(self):
        """Update the last modified timestamp"""
        self.updated_at = datetime.utcnow().isoformat()

    def add_task(self, task: Task):
        """Add a task to the shared state"""
        self.tasks.append(task)
        self.update_timestamp()

    def update_task_status(self, task_id: str, status: TaskStatus):
        """Update task status"""
        for task in self.tasks:
            if task.task_id == task_id:
                task.status = status
                task.updated_at = datetime.utcnow().isoformat()
                self.update_timestamp()
                return True
        return False

    def assign_worker(self, worker_id: str):
        """Assign a worker"""
        if worker_id not in self.assigned_workers:
            self.assigned_workers.append(worker_id)
            self.update_timestamp()

    def unassign_worker(self, worker_id: str):
        """Unassign a worker"""
        if worker_id in self.assigned_workers:
            self.assigned_workers.remove(worker_id)
            self.update_timestamp()


class LangGraphAgent(ABC):
    """Base class for LangGraph-based agents"""

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.local_state = LocalAgentState(agent_id=agent_id)

    @abstractmethod
    def process_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process an incoming message"""
        pass

    @abstractmethod
    def execute_task(self, task: Task) -> Dict[str, Any]:
        """Execute a task"""
        pass

    def get_state(self) -> LocalAgentState:
        """Get current local state"""
        return self.local_state

    def set_state(self, state: LocalAgentState):
        """Set local state"""
        self.local_state = state

    def get_status(self) -> AgentStatus:
        """Get agent status"""
        return self.local_state.status

    def set_status(self, status: AgentStatus):
        """Set agent status"""
        self.local_state.set_status(status)

    def add_task(self, task: Task):
        """Add a task"""
        self.local_state.add_task(task)

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID"""
        return self.local_state.get_task(task_id)

    def get_pending_tasks(self) -> List[Task]:
        """Get all pending tasks"""
        return [t for t in self.local_state.local_tasks if t.status == TaskStatus.PENDING]

    def get_state_snapshot(self) -> str:
        """Get JSON snapshot of current state"""
        return self.local_state.to_json()
