"""
Integration tests for A2A messaging and Redis operations
"""

import pytest
import json
from core import (
    A2AClient,
    A2AConfig,
    A2ARouter,
    MessageType,
    Task,
)


class TestA2ARouting:
    """Test A2A message routing"""

    def test_agent_registration(self):
        """Test registering agents with router"""
        router = A2ARouter()
        config1 = A2AConfig(agent_id="agent-1")
        client1 = A2AClient(config1)

        router.register_agent("agent-1", client1)
        assert "agent-1" in router.agents

    def test_message_routing(self):
        """Test routing messages between agents"""
        router = A2ARouter()

        # Create two agents
        config1 = A2AConfig(agent_id="agent-1")
        client1 = A2AClient(config1)

        config2 = A2AConfig(agent_id="agent-2")
        client2 = A2AClient(config2)

        router.register_agent("agent-1", client1)
        router.register_agent("agent-2", client2)

        # Send message from agent-1 to agent-2
        message = client1.create_message(
            recipient="agent-2",
            payload={"test": "data"},
            message_type=MessageType.REQUEST,
        )

        result = router.route_message(message)
        assert result is True

    def test_message_queue(self):
        """Test message queuing"""
        router = A2ARouter()

        config1 = A2AConfig(agent_id="agent-1")
        client1 = A2AClient(config1)

        config2 = A2AConfig(agent_id="agent-2")
        client2 = A2AClient(config2)

        router.register_agent("agent-1", client1)
        router.register_agent("agent-2", client2)

        # Send multiple messages
        for i in range(3):
            message = client1.create_message(
                recipient="agent-2",
                payload={"index": i},
            )
            router.route_message(message)

        # Check pending messages
        messages = router.get_messages("agent-2")
        assert len(messages) == 3


class TestA2AMessageTypes:
    """Test different A2A message types"""

    def test_request_response_cycle(self):
        """Test request-response message cycle"""
        config = A2AConfig(agent_id="agent-1")
        client = A2AClient(config)

        # Create request
        request = client.create_message(
            recipient="agent-2",
            payload={"action": "compute"},
            message_type=MessageType.REQUEST,
        )

        assert request.type == MessageType.REQUEST

        # Create response
        response = client.create_message(
            recipient="agent-2",
            payload={"result": 42},
            message_type=MessageType.RESPONSE,
        )

        assert response.type == MessageType.RESPONSE

    def test_heartbeat_messages(self):
        """Test heartbeat messages"""
        config = A2AConfig(agent_id="agent-1")
        client = A2AClient(config)

        message = client.send_heartbeat(
            recipient="agent-2",
            status={"uptime": 100, "state": "active"},
        )

        assert message.type == MessageType.HEARTBEAT
        assert message.payload["status"]["state"] == "active"

    def test_event_messages(self):
        """Test event messages"""
        config = A2AConfig(agent_id="agent-1")
        client = A2AClient(config)

        message = client.send_event(
            recipient="agent-2",
            event_type="task_completed",
            event_data={"task_id": "task-1"},
        )

        assert message.type == MessageType.EVENT
        assert message.payload["event_type"] == "task_completed"


class TestCausalMetadata:
    """Test causal metadata in messages"""

    def test_metadata_tracking(self):
        """Test that metadata tracks causality"""
        config = A2AConfig(agent_id="agent-1")
        client = A2AClient(config)

        message1 = client.create_message(
            recipient="agent-2",
            payload={"index": 1},
        )

        message2 = client.create_message(
            recipient="agent-2",
            payload={"index": 2},
            message_type=MessageType.RESPONSE,
        )

        # Both should have incremental sequence numbers
        assert message1.metadata.sequence_number == 1
        assert message2.metadata.sequence_number == 2

    def test_parent_request_tracking(self):
        """Test parent request ID tracking"""
        config = A2AConfig(agent_id="agent-1")
        client = A2AClient(config)

        request = client.create_message(
            recipient="agent-2",
            payload={"action": "test"},
            message_type=MessageType.REQUEST,
        )

        response = client.create_message(
            recipient="agent-2",
            payload={"result": "ok"},
            message_type=MessageType.RESPONSE,
            parent_request_id=request.metadata.request_id,
        )

        assert response.metadata.parent_request_id == request.metadata.request_id


class TestMessageSigning:
    """Test message signing and verification"""

    def test_signature_generation(self):
        """Test that messages are signed"""
        config = A2AConfig(agent_id="agent-1", token_secret="secret")
        client = A2AClient(config)

        message = client.create_message(
            recipient="agent-2",
            payload={"test": "data"},
        )

        assert message.signature is not None
        assert len(message.signature) > 0

    def test_signature_verification_success(self):
        """Test successful signature verification"""
        config = A2AConfig(agent_id="agent-1", token_secret="secret")
        client = A2AClient(config)

        message = client.create_message(
            recipient="agent-2",
            payload={"test": "data"},
        )

        assert client._verify_message(message)

    def test_signature_verification_failure(self):
        """Test failed signature verification with tampering"""
        config = A2AConfig(agent_id="agent-1", token_secret="secret")
        client = A2AClient(config)

        message = client.create_message(
            recipient="agent-2",
            payload={"test": "data"},
        )

        # Tamper with message
        message.payload["test"] = "tampered"

        # Verification should fail
        assert not client._verify_message(message)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
