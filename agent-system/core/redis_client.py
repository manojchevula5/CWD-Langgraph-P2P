"""
Core Redis integration module for shared state management.
Provides connection pooling, pub/sub, transactions, and lease management.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional, Union
from dataclasses import dataclass, asdict
import redis
from redis.exceptions import ConnectionError, TimeoutError as RedisTimeoutError
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


@dataclass
class RedisConfig:
    """Redis connection configuration"""
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None
    use_tls: bool = False
    ssl_cert_reqs: str = "required"
    socket_timeout: int = 5
    socket_keepalive: bool = True
    health_check_interval: int = 30
    max_retries: int = 3
    retry_backoff: float = 1.0


class RedisClient:
    """Robust Redis client with retry logic and pub/sub support"""

    def __init__(self, config: RedisConfig):
        self.config = config
        self.client: Optional[redis.Redis] = None
        self.pubsub = None
        self._subscriptions: Dict[str, Callable] = {}
        self._listener_thread = None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    def connect(self):
        """Establish Redis connection with retry logic"""
        try:
            connection_kwargs = {
                "host": self.config.host,
                "port": self.config.port,
                "db": self.config.db,
                "socket_timeout": self.config.socket_timeout,
                "socket_keepalive": self.config.socket_keepalive,
                "health_check_interval": self.config.health_check_interval,
                "decode_responses": True,
            }

            if self.config.password:
                connection_kwargs["password"] = self.config.password

            if self.config.use_tls:
                connection_kwargs["ssl"] = True
                connection_kwargs["ssl_cert_reqs"] = self.config.ssl_cert_reqs

            self.client = redis.Redis(**connection_kwargs)
            self.client.ping()
            logger.info(f"Connected to Redis at {self.config.host}:{self.config.port}")
            return True
        except (ConnectionError, RedisTimeoutError) as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    def disconnect(self):
        """Close Redis connection"""
        if self.client:
            self.client.close()
            logger.info("Disconnected from Redis")

    def set(self, key: str, value: Union[str, Dict, Any], ttl: Optional[int] = None) -> bool:
        """Set a key-value pair with optional TTL"""
        try:
            if isinstance(value, dict):
                value = json.dumps(value)
            if ttl:
                self.client.setex(key, ttl, value)
            else:
                self.client.set(key, value)
            return True
        except Exception as e:
            logger.error(f"Failed to set key {key}: {e}")
            return False

    def get(self, key: str) -> Optional[Union[str, Dict]]:
        """Get a value by key"""
        try:
            value = self.client.get(key)
            if value and key.endswith(":json"):
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value
            return value
        except Exception as e:
            logger.error(f"Failed to get key {key}: {e}")
            return None

    def delete(self, key: str) -> bool:
        """Delete a key"""
        try:
            self.client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Failed to delete key {key}: {e}")
            return False

    def exists(self, key: str) -> bool:
        """Check if a key exists"""
        try:
            return self.client.exists(key) > 0
        except Exception as e:
            logger.error(f"Failed to check key existence {key}: {e}")
            return False

    def incr(self, key: str, amount: int = 1) -> Optional[int]:
        """Increment a counter"""
        try:
            return self.client.incrby(key, amount)
        except Exception as e:
            logger.error(f"Failed to increment key {key}: {e}")
            return None

    def publish(self, channel: str, message: Union[str, Dict]) -> int:
        """Publish a message to a channel"""
        try:
            if isinstance(message, dict):
                message = json.dumps(message)
            return self.client.publish(channel, message)
        except Exception as e:
            logger.error(f"Failed to publish to channel {channel}: {e}")
            return 0

    def subscribe(self, channels: Union[str, list], callback: Callable):
        """Subscribe to one or more channels"""
        try:
            if isinstance(channels, str):
                channels = [channels]

            self.pubsub = self.client.pubsub()
            self.pubsub.subscribe(*channels)

            for channel in channels:
                self._subscriptions[channel] = callback

            logger.info(f"Subscribed to channels: {channels}")

            # Start listening in a separate thread
            self._start_listener()
            return True
        except Exception as e:
            logger.error(f"Failed to subscribe to channels: {e}")
            return False

    def _start_listener(self):
        """Start listening for pub/sub messages"""
        def listen():
            for message in self.pubsub.listen():
                if message["type"] == "message":
                    channel = message["channel"]
                    data = message["data"]

                    # Parse JSON if applicable
                    try:
                        data = json.loads(data)
                    except (json.JSONDecodeError, TypeError):
                        pass

                    callback = self._subscriptions.get(channel)
                    if callback:
                        try:
                            callback(channel, data)
                        except Exception as e:
                            logger.error(f"Error in subscription callback for {channel}: {e}")

        import threading
        self._listener_thread = threading.Thread(target=listen, daemon=True)
        self._listener_thread.start()

    def watch(self, key: str):
        """Watch a key for changes (for transactions)"""
        try:
            self.client.watch(key)
            return True
        except Exception as e:
            logger.error(f"Failed to watch key {key}: {e}")
            return False

    def transaction(self, key: str, update_func: Callable) -> Optional[Any]:
        """Execute a transaction with optimistic concurrency"""
        try:
            pipe = self.client.pipeline()
            while True:
                try:
                    pipe.watch(key)
                    current = self.client.get(key)
                    current_obj = json.loads(current) if current else {}

                    # Apply update function
                    updated_obj = update_func(current_obj)

                    pipe.multi()
                    pipe.set(key, json.dumps(updated_obj))
                    pipe.execute()
                    return updated_obj
                except redis.WatchError:
                    continue
        except Exception as e:
            logger.error(f"Transaction failed for key {key}: {e}")
            return None

    def acquire_lease(
        self,
        lease_key: str,
        owner: str,
        ttl: int = 30,
    ) -> bool:
        """Acquire a distributed lease with TTL"""
        try:
            lease_obj = {
                "owner": owner,
                "acquired_at": datetime.utcnow().isoformat(),
                "expires_at": (datetime.utcnow() + timedelta(seconds=ttl)).isoformat(),
            }
            result = self.client.set(lease_key, json.dumps(lease_obj), nx=True, ex=ttl)
            if result:
                logger.info(f"Lease acquired by {owner} on {lease_key}")
            return result
        except Exception as e:
            logger.error(f"Failed to acquire lease {lease_key}: {e}")
            return False

    def renew_lease(self, lease_key: str, owner: str, ttl: int = 30) -> bool:
        """Renew a lease if still owned"""
        try:
            lease_obj = self.client.get(lease_key)
            if not lease_obj:
                return False

            lease_data = json.loads(lease_obj)
            if lease_data.get("owner") != owner:
                return False

            new_lease_obj = {
                "owner": owner,
                "acquired_at": lease_data["acquired_at"],
                "expires_at": (datetime.utcnow() + timedelta(seconds=ttl)).isoformat(),
            }
            self.client.setex(lease_key, ttl, json.dumps(new_lease_obj))
            return True
        except Exception as e:
            logger.error(f"Failed to renew lease {lease_key}: {e}")
            return False

    def release_lease(self, lease_key: str, owner: str) -> bool:
        """Release a lease"""
        try:
            lease_obj = self.client.get(lease_key)
            if not lease_obj:
                return False

            lease_data = json.loads(lease_obj)
            if lease_data.get("owner") != owner:
                return False

            self.client.delete(lease_key)
            logger.info(f"Lease released by {owner} on {lease_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to release lease {lease_key}: {e}")
            return False

    def get_lease(self, lease_key: str) -> Optional[Dict]:
        """Get current lease information"""
        try:
            lease_obj = self.client.get(lease_key)
            return json.loads(lease_obj) if lease_obj else None
        except Exception as e:
            logger.error(f"Failed to get lease {lease_key}: {e}")
            return None
