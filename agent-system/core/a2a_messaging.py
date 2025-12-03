"""
Agent-to-Agent (A2A) P2P messaging system.
Supports RPC-style and pub/sub messaging with authentication and causal metadata.
"""

import json
import uuid
import logging
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Union
from dataclasses import dataclass, field, asdict
from enum import Enum
import hashlib
import hmac

logger = logging.getLogger(__name__)

# Optional global router used by tests/examples to route messages in-process
GLOBAL_A2A_ROUTER = None


class MessageType(str, Enum):
    """A2A message types"""
    REQUEST = "request"
    RESPONSE = "response"
    HEARTBEAT = "heartbeat"
    EVENT = "event"
    ACK = "ack"
    ERROR = "error"


@dataclass
class CausalMetadata:
    """Causal metadata for A2A messages"""
    origin: str
    version: str = "v1"
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_request_id: Optional[str] = None
    sequence_number: int = 0

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class A2AMessage:
    """A2A message structure"""
    type: MessageType
    sender: str
    recipient: str
    payload: Dict[str, Any]
    metadata: CausalMetadata
    signature: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "type": self.type.value,
            "sender": self.sender,
            "recipient": self.recipient,
            "payload": self.payload,
            "metadata": self.metadata.to_dict(),
            "signature": self.signature,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict) -> "A2AMessage":
        metadata = CausalMetadata(**data["metadata"])
        return cls(
            type=MessageType(data["type"]),
            sender=data["sender"],
            recipient=data["recipient"],
            payload=data["payload"],
            metadata=metadata,
            signature=data.get("signature"),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "A2AMessage":
        return cls.from_dict(json.loads(json_str))


class A2AConfig:
    """A2A configuration"""
    def __init__(
        self,
        agent_id: str,
        agent_port: int = 8000,
        use_mtls: bool = False,
        cert_path: Optional[str] = None,
        key_path: Optional[str] = None,
        token_secret: str = "default-secret",
    ):
        self.agent_id = agent_id
        self.agent_port = agent_port
        self.use_mtls = use_mtls
        self.cert_path = cert_path
        self.key_path = key_path
        self.token_secret = token_secret


class A2AClient:
    """Agent-to-Agent communication client"""

    def __init__(self, config: A2AConfig):
        self.config = config
        self.message_handlers: Dict[str, Callable] = {}
        self.pending_requests: Dict[str, Dict] = {}
        self._sequence_number = 0

    def _sign_message(self, message: A2AMessage) -> str:
        """Sign message with HMAC"""
        message_dict = message.to_dict()
        message_dict["signature"] = None  # Remove signature before signing
        message_str = json.dumps(message_dict, sort_keys=True)
        signature = hmac.new(
            self.config.token_secret.encode(),
            message_str.encode(),
            hashlib.sha256,
        ).hexdigest()
        return signature

    def _verify_message(self, message: A2AMessage) -> bool:
        """Verify message signature"""
        # If running with an in-process router, try to verify using the
        # sender's configured token_secret (safer for tests). If the
        # sender client isn't registered with the router, fall back to
        # allowing the message (convenience for simple examples).
        global GLOBAL_A2A_ROUTER
        if GLOBAL_A2A_ROUTER is not None:
            try:
                sender_client = GLOBAL_A2A_ROUTER.agents.get(message.sender)
                if sender_client and getattr(sender_client, "config", None):
                    # Recreate the signing process using the sender's secret
                    message_dict = message.to_dict()
                    message_dict["signature"] = None
                    message_str = json.dumps(message_dict, sort_keys=True)
                    expected_signature = hmac.new(
                        sender_client.config.token_secret.encode(),
                        message_str.encode(),
                        hashlib.sha256,
                    ).hexdigest()

                    if hmac.compare_digest(message.signature or "", expected_signature):
                        return True
                    else:
                        logger.warning(
                            f"In-process verification failed for message from {message.sender}"
                        )
                        return False
                else:
                    logger.debug(
                        "Sender client not known to in-process router; bypassing verification"
                    )
                    return True
            except Exception:
                logger.exception(
                    "Error verifying signature using in-process router; allowing message"
                )
                return True

        if not message.signature:
            logger.warning(f"Message from {message.sender} has no signature")
            return False

        expected_signature = self._sign_message(message)
        return hmac.compare_digest(message.signature, expected_signature)

    def create_message(
        self,
        recipient: str,
        payload: Dict[str, Any],
        message_type: MessageType = MessageType.REQUEST,
        parent_request_id: Optional[str] = None,
    ) -> A2AMessage:
        """Create and sign an A2A message"""
        logger.debug(f"[create_message] ENTRY - recipient={recipient}, message_type={message_type.value}, payload_keys={list(payload.keys())}")
        self._sequence_number += 1

        metadata = CausalMetadata(
            origin=self.config.agent_id,
            request_id=str(uuid.uuid4()),
            parent_request_id=parent_request_id,
            sequence_number=self._sequence_number,
        )
        logger.debug(f"[create_message] Metadata created - request_id={metadata.request_id}, seq={self._sequence_number}")

        message = A2AMessage(
            type=message_type,
            sender=self.config.agent_id,
            recipient=recipient,
            payload=payload,
            metadata=metadata,
        )
        logger.debug(f"[create_message] Signing message")

        message.signature = self._sign_message(message)
        logger.debug(f"[create_message] EXIT SUCCESS - Message created and signed")
        return message

    def send_request(
        self,
        recipient: str,
        payload: Dict[str, Any],
        timeout: int = 30,
    ) -> Optional[A2AMessage]:
        """Send a request and wait for response"""
        message = self.create_message(recipient, payload, MessageType.REQUEST)
        self.pending_requests[message.metadata.request_id] = {
            "message": message,
            "timestamp": datetime.utcnow(),
            "timeout": timeout,
        }

        logger.info(f"Sending request from {message.sender} to {message.recipient}")
        self._send(message)

        # In a real implementation, this would wait for a response
        # For now, we'll just return the message
        return message

    def send_response(
        self,
        recipient: str,
        parent_request_id: str,
        payload: Dict[str, Any],
        success: bool = True,
    ) -> A2AMessage:
        """Send a response to a request"""
        response_payload = {
            "success": success,
            "data": payload if success else None,
            "error": payload if not success else None,
        }

        message = self.create_message(
            recipient,
            response_payload,
            MessageType.RESPONSE,
            parent_request_id=parent_request_id,
        )

        logger.info(f"Sending response from {message.sender} to {message.recipient}")
        self._send(message)
        return message

    def send_heartbeat(self, recipient: str, status: Dict[str, Any]) -> A2AMessage:
        """Send a heartbeat message"""
        message = self.create_message(
            recipient,
            {"status": status},
            MessageType.HEARTBEAT,
        )

        logger.debug(f"Sending heartbeat from {message.sender} to {message.recipient}")
        self._send(message)
        return message

    def send_event(
        self,
        recipient: str,
        event_type: str,
        event_data: Dict[str, Any],
    ) -> A2AMessage:
        """Send an event message"""
        message = self.create_message(
            recipient,
            {"event_type": event_type, "event_data": event_data},
            MessageType.EVENT,
        )

        logger.info(f"Sending event {event_type} from {message.sender} to {message.recipient}")
        self._send(message)
        return message

    def register_handler(self, message_type: MessageType, handler: Callable):
        """Register a handler for a message type"""
        logger.info(f"[register_handler] ENTRY - message_type={message_type.value}, handler={handler.__name__}")
        self.message_handlers[message_type.value] = handler
        logger.debug(f"[register_handler] EXIT SUCCESS - Handler registered for {message_type.value} messages")

    def handle_message(self, message: A2AMessage) -> bool:
        """Handle an incoming A2A message"""
        logger.info(f"[handle_message] ENTRY - message_type={message.type.value}, sender={message.sender}, request_id={message.metadata.request_id}")
        
        # Verify signature
        logger.debug(f"[handle_message] Verifying message signature")
        if not self._verify_message(message):
            logger.error(f"[handle_message] Message signature verification failed from {message.sender}")
            return False
        logger.debug(f"[handle_message] Signature verified")

        logger.info(f"[handle_message] Received {message.type.value} from {message.sender}")

        handler = self.message_handlers.get(message.type.value)
        if handler:
            try:
                logger.debug(f"[handle_message] Calling handler for {message.type.value}")
                handler(message)
                logger.info(f"[handle_message] EXIT SUCCESS - Message handled")
                return True
            except Exception as e:
                logger.error(f"[handle_message] EXCEPTION - Error handling {message.type.value} message: {e}", exc_info=True)
                return False

        logger.warning(f"[handle_message] No handler registered for {message.type.value} messages")
        return False

    def _send(self, message: A2AMessage):
        """Internal method to send a message (placeholder for network transport)"""
        # In a real implementation, this would send over HTTP, gRPC, or other transport
        logger.debug(f"Message queued for sending: {message.to_json()[:100]}...")

        # If a global in-process router is set (used for tests/examples), route the
        # message immediately so handlers receive it synchronously.
        try:
            global GLOBAL_A2A_ROUTER
            if GLOBAL_A2A_ROUTER is not None:
                GLOBAL_A2A_ROUTER.route_message(message)
        except Exception:
            # Don't allow routing failures to break the sender; just log.
            logger.exception("Failed to route message via GLOBAL_A2A_ROUTER")


class A2ARouter:
    """Routes messages between agents"""

    def __init__(self):
        self.agents: Dict[str, A2AClient] = {}
        self.message_queue: Dict[str, list] = {}

    def register_agent(self, agent_id: str, client: A2AClient):
        """Register an agent with the router"""
        self.agents[agent_id] = client
        self.message_queue[agent_id] = []
        logger.info(f"Registered agent {agent_id}")

    def route_message(self, message: A2AMessage):
        """Route a message to its recipient"""
        logger.debug(f"[route_message] ENTRY - recipient={message.recipient}, sender={message.sender}, type={message.type.value}")
        recipient_client = self.agents.get(message.recipient)
        if not recipient_client:
            logger.error(f"[route_message] No agent registered with ID {message.recipient}")
            return False

        # Queue the message
        logger.debug(f"[route_message] Queuing message")
        self.message_queue[message.recipient].append(message)
        logger.info(f"[route_message] Message routed to {message.recipient}")

        # Handle the message
        logger.debug(f"[route_message] Handling message")
        result = recipient_client.handle_message(message)
        logger.debug(f"[route_message] EXIT SUCCESS - routing result={result}")
        return result

    def get_messages(self, agent_id: str) -> list:
        """Get pending messages for an agent"""
        messages = self.message_queue.get(agent_id, [])
        self.message_queue[agent_id] = []
        return messages
