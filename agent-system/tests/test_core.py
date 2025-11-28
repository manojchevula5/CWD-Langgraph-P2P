"""
Unit tests for core modules
"""

import pytest
import json
from datetime import datetime
from core import (
    RedisConfig,
    A2AConfig,
    A2AClient,
    MessageType,
    Task,
    TaskStatus,
    AgentStatus,
    LocalAgentState,
    SharedAgentState,
)


class TestA2AMessaging:
    """Test A2A messaging functionality"""

    def test_create_message(self):
        """Test message creation"""
        config = A2AConfig(agent_id="test-agent")
        client = A2AClient(config)

        message = client.create_message(
            recipient="recipient-agent",
            payload={"test": "data"},
            message_type=MessageType.REQUEST,
        )

        assert message.sender == "test-agent"
        assert message.recipient == "recipient-agent"
        assert message.type == MessageType.REQUEST
        assert message.payload == {"test": "data"}
        assert message.signature is not None

    def test_message_signing_and_verification(self):
        """Test message signing and verification"""
        config = A2AConfig(
            agent_id="test-agent",
            token_secret="test-secret",
        )
        client = A2AClient(config)

        message = client.create_message(
            recipient="recipient-agent",
            payload={"test": "data"},
        )

        assert client._verify_message(message)

    def test_message_json_serialization(self):
        """Test message JSON serialization"""
        config = A2AConfig(agent_id="test-agent")
        client = A2AClient(config)

        message = client.create_message(
            recipient="recipient-agent",
            payload={"test": "data"},
        )

        json_str = message.to_json()
        reconstructed = type(message).from_json(json_str)

        assert reconstructed.sender == message.sender
        assert reconstructed.recipient == message.recipient
        assert reconstructed.payload == message.payload


class TestLangGraphState:
    """Test LangGraph state management"""

    def test_local_agent_state_creation(self):
        """Test local agent state creation"""
        state = LocalAgentState(agent_id="test-agent")

        assert state.agent_id == "test-agent"
        assert state.status == AgentStatus.IDLE
        assert len(state.local_tasks) == 0

    def test_add_task_to_state(self):
        """Test adding tasks to state"""
        state = LocalAgentState(agent_id="test-agent")
        task = Task(
            task_id="task-1",
            task_type="test",
            payload={"test": "data"},
        )

        state.add_task(task)

        assert len(state.local_tasks) == 1
        assert state.get_task("task-1") == task

    def test_task_status_transitions(self):
        """Test task status transitions"""
        task = Task(
            task_id="task-1",
            task_type="test",
            payload={},
        )

        assert task.status == TaskStatus.PENDING

        task.mark_started()
        assert task.status == TaskStatus.IN_PROGRESS

        result = {"output": "test"}
        task.mark_completed(result)
        assert task.status == TaskStatus.COMPLETED
        assert task.result == result

    def test_shared_agent_state_creation(self):
        """Test shared agent state creation"""
        state = SharedAgentState()

        assert state.status == AgentStatus.IDLE
        assert len(state.assigned_workers) == 0
        assert len(state.tasks) == 0

    def test_add_worker_to_shared_state(self):
        """Test adding workers to shared state"""
        state = SharedAgentState()

        state.assign_worker("worker-1")
        assert "worker-1" in state.assigned_workers

        state.assign_worker("worker-2")
        assert len(state.assigned_workers) == 2

    def test_shared_state_serialization(self):
        """Test shared state JSON serialization"""
        state = SharedAgentState()
        state.assign_worker("worker-1")

        json_str = state.to_json()
        state_dict = json.loads(json_str)

        assert state_dict["assigned_workers"] == ["worker-1"]
        assert state_dict["status"] == "idle"


class TestRedisConfig:
    """Test Redis configuration"""

    def test_redis_config_creation(self):
        """Test Redis config creation"""
        config = RedisConfig(
            host="localhost",
            port=6379,
            password="secret",
            use_tls=True,
        )

        assert config.host == "localhost"
        assert config.port == 6379
        assert config.password == "secret"
        assert config.use_tls is True

    def test_redis_config_defaults(self):
        """Test Redis config defaults"""
        config = RedisConfig()

        assert config.host == "localhost"
        assert config.port == 6379
        assert config.db == 0
        assert config.use_tls is False


class TestTaskModel:
    """Test Task data model"""

    def test_task_creation(self):
        """Test task creation"""
        task = Task(
            task_id="task-1",
            task_type="compute",
            payload={"value": 42},
        )

        assert task.task_id == "task-1"
        assert task.task_type == "compute"
        assert task.status == TaskStatus.PENDING
        assert task.created_at is not None

    def test_task_serialization(self):
        """Test task JSON serialization"""
        task = Task(
            task_id="task-1",
            task_type="compute",
            payload={"value": 42},
        )

        task_dict = task.to_dict()
        assert task_dict["task_id"] == "task-1"
        assert task_dict["task_type"] == "compute"
        assert task_dict["status"] == "pending"

        json_str = task.to_json()
        parsed = json.loads(json_str)
        assert parsed["task_id"] == "task-1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
