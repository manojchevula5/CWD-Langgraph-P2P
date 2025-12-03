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
        self._listening = False

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
        # Stop pubsub listener first
        try:
            self._stop_listener()
        except Exception:
            logger.exception("Error stopping pubsub listener")

        if self.client:
            try:
                self.client.close()
            except Exception:
                logger.exception("Error closing redis client")
            logger.info("Disconnected from Redis")

    def set(self, key: str, value: Union[str, Dict, Any], ttl: Optional[int] = None) -> bool:
        """Set a key-value pair with optional TTL"""
        logger.debug(f"[set] ENTRY - key={key}, value_type={type(value).__name__}, ttl={ttl}")
        try:
            if isinstance(value, dict):
                logger.debug(f"[set] Converting dict to JSON")
                value = json.dumps(value)
            if ttl:
                logger.debug(f"[set] Setting key with TTL={ttl}s")
                self.client.setex(key, ttl, value)
            else:
                logger.debug(f"[set] Setting key without TTL")
                self.client.set(key, value)
            logger.debug(f"[set] EXIT SUCCESS - key {key} set")
            return True
        except Exception as e:
            logger.error(f"[set] EXCEPTION - Failed to set key {key}: {e}", exc_info=True)
            return False

    def get(self, key: str) -> Optional[Union[str, Dict]]:
        """Get a value by key"""
        logger.debug(f"[get] ENTRY - key={key}")
        try:
            value = self.client.get(key)
            logger.debug(f"[get] Retrieved value_type={type(value).__name__}")
            if value and key.endswith(":json"):
                logger.debug(f"[get] Attempting JSON parse")
                try:
                    result = json.loads(value)
                    logger.debug(f"[get] EXIT SUCCESS - JSON parsed")
                    return result
                except json.JSONDecodeError:
                    logger.debug(f"[get] JSON parse failed, returning raw value")
                    return value
            logger.debug(f"[get] EXIT SUCCESS")
            return value
        except Exception as e:
            logger.error(f"[get] EXCEPTION - Failed to get key {key}: {e}", exc_info=True)
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
        logger.info(f"[publish] ENTRY - channel={channel}, message_type={type(message).__name__}")
        try:
            if isinstance(message, dict):
                logger.debug(f"[publish] Converting dict message to JSON")
                message = json.dumps(message)
            logger.debug(f"[publish] Publishing message")
            result = self.client.publish(channel, message)
            logger.info(f"[publish] EXIT SUCCESS - Published to {result} subscribers on {channel}")
            return result
        except Exception as e:
            logger.error(f"[publish] EXCEPTION - Failed to publish to channel {channel}: {e}", exc_info=True)
            return 0

    def subscribe(self, channels: Union[str, list], callback: Callable):
        """Subscribe to one or more channels"""
        logger.info(f"[subscribe] ENTRY - channels={channels}")
        try:
            if isinstance(channels, str):
                channels = [channels]
                logger.debug(f"[subscribe] Converted single channel to list")

            logger.debug(f"[subscribe] Creating pubsub instance")
            self.pubsub = self.client.pubsub()
            
            # Check if pattern subscribe needed
            has_pattern = any(("*" in ch or "?" in ch or "[" in ch) for ch in channels)
            if has_pattern:
                logger.debug(f"[subscribe] Pattern detected, using psubscribe")
                self.pubsub.psubscribe(*channels)
            else:
                logger.debug(f"[subscribe] No pattern, using subscribe")
                self.pubsub.subscribe(*channels)

            for channel in channels:
                self._subscriptions[channel] = callback
                logger.debug(f"[subscribe] Registered callback for channel: {channel}")

            logger.info(f"[subscribe] Subscribed to channels: {channels}, callback registered")

            # Start listening in a separate thread
            logger.debug(f"[subscribe] Starting listener thread")
            self._start_listener()
            logger.info(f"[subscribe] EXIT SUCCESS - Listener started")
            return True
        except Exception as e:
            logger.error(f"[subscribe] EXCEPTION - Failed to subscribe to channels: {e}", exc_info=True)
            return False

    def _start_listener(self):
        """Start listening for pub/sub messages"""
        def listen():
            # Use a blocking listen loop but handle socket/connection errors
            self._listening = True
            try:
                # Use get_message polling instead of blocking listen() to avoid
                # issues when the underlying socket is closed during shutdown.
                while self._listening:
                    try:
                        message = self.pubsub.get_message(timeout=1)
                    except (OSError, ConnectionError, ValueError) as e:
                        logger.info(f"PubSub get_message stopped due to connection error: {e}")
                        break

                    if not message:
                        continue

                    try:
                        if message.get("type") == "message":
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
                                    logger.error(
                                        f"Error in subscription callback for {channel}: {e}"
                                    )
                    except Exception as e:
                        logger.exception(f"Unexpected error in pubsub listener: {e}")
                        continue
            finally:
                self._listening = False

        import threading
        self._listener_thread = threading.Thread(target=listen, daemon=True)
        self._listener_thread.start()

    def _stop_listener(self):
        """Stop the pubsub listener thread and close pubsub."""
        self._listening = False
        try:
            if self.pubsub:
                try:
                    # Unsubscribe and close pubsub to unblock listener
                    try:
                        # attempt to unsubscribe from all channels first
                        self.pubsub.unsubscribe()
                    except Exception:
                        pass
                    self.pubsub.close()
                except Exception:
                    logger.exception("Error closing pubsub")

            if self._listener_thread and self._listener_thread.is_alive():
                # join briefly to allow thread to exit
                self._listener_thread.join(timeout=2)
        finally:
            self._listener_thread = None

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
        logger.debug(f"[transaction] ENTRY - key={key}")
        try:
            pipe = self.client.pipeline()
            attempt = 0
            while True:
                attempt += 1
                logger.debug(f"[transaction] Attempt {attempt}: watching key {key}")
                try:
                    pipe.watch(key)
                    logger.debug(f"[transaction] Fetching current value")
                    current = self.client.get(key)
                    current_obj = json.loads(current) if current else {}
                    logger.debug(f"[transaction] Current object: {type(current_obj).__name__}")

                    # Apply update function
                    logger.debug(f"[transaction] Applying update function")
                    updated_obj = update_func(current_obj)
                    logger.debug(f"[transaction] Update function returned: {type(updated_obj).__name__}")

                    logger.debug(f"[transaction] Starting transaction pipe")
                    pipe.multi()
                    pipe.set(key, json.dumps(updated_obj))
                    pipe.execute()
                    logger.info(f"[transaction] EXIT SUCCESS - Transaction committed on attempt {attempt}")
                    return updated_obj
                except redis.WatchError:
                    logger.debug(f"[transaction] WatchError on attempt {attempt}, retrying...")
                    continue
        except Exception as e:
            logger.error(f"[transaction] EXCEPTION - Transaction failed for key {key}: {e}", exc_info=True)
            return None

    def acquire_lease(
        self,
        lease_key: str,
        owner: str,
        ttl: int = 30,
    ) -> bool:
        """Acquire a distributed lease with TTL"""
        logger.info(f"[acquire_lease] ENTRY - lease_key={lease_key}, owner={owner}, ttl={ttl}")
        try:
            lease_obj = {
                "owner": owner,
                "acquired_at": datetime.utcnow().isoformat(),
                "expires_at": (datetime.utcnow() + timedelta(seconds=ttl)).isoformat(),
            }
            logger.debug(f"[acquire_lease] Attempting NX set with TTL={ttl}")
            result = self.client.set(lease_key, json.dumps(lease_obj), nx=True, ex=ttl)
            if result:
                logger.info(f"[acquire_lease] EXIT SUCCESS - Lease acquired by {owner}")
            else:
                logger.debug(f"[acquire_lease] Lease already held by another owner")
            return result
        except Exception as e:
            logger.error(f"[acquire_lease] EXCEPTION - Failed to acquire lease {lease_key}: {e}", exc_info=True)
            return False

    def renew_lease(self, lease_key: str, owner: str, ttl: int = 30) -> bool:
        """Renew a lease if still owned"""
        logger.debug(f"[renew_lease] ENTRY - lease_key={lease_key}, owner={owner}, ttl={ttl}")
        try:
            logger.debug(f"[renew_lease] Fetching current lease")
            lease_obj = self.client.get(lease_key)
            if not lease_obj:
                logger.debug(f"[renew_lease] Lease not found")
                return False

            lease_data = json.loads(lease_obj)
            current_owner = lease_data.get("owner")
            logger.debug(f"[renew_lease] Current owner: {current_owner}")
            if current_owner != owner:
                logger.warning(f"[renew_lease] Lease owned by different owner: {current_owner}")
                return False

            new_lease_obj = {
                "owner": owner,
                "acquired_at": lease_data["acquired_at"],
                "expires_at": (datetime.utcnow() + timedelta(seconds=ttl)).isoformat(),
            }
            logger.debug(f"[renew_lease] Renewing lease with new TTL={ttl}")
            self.client.setex(lease_key, ttl, json.dumps(new_lease_obj))
            logger.debug(f"[renew_lease] EXIT SUCCESS - Lease renewed")
            return True
        except Exception as e:
            logger.error(f"[renew_lease] EXCEPTION - Failed to renew lease {lease_key}: {e}", exc_info=True)
            return False

    def release_lease(self, lease_key: str, owner: str) -> bool:
        """Release a lease"""
        logger.debug(f"[release_lease] ENTRY - lease_key={lease_key}, owner={owner}")
        try:
            logger.debug(f"[release_lease] Fetching current lease")
            lease_obj = self.client.get(lease_key)
            if not lease_obj:
                logger.debug(f"[release_lease] Lease not found")
                return False

            lease_data = json.loads(lease_obj)
            if lease_data.get("owner") != owner:
                logger.warning(f"[release_lease] Cannot release lease owned by {lease_data.get('owner')}")
                return False

            logger.debug(f"[release_lease] Deleting lease")
            self.client.delete(lease_key)
            logger.info(f"[release_lease] EXIT SUCCESS - Lease released by {owner}")
            return True
        except Exception as e:
            logger.error(f"[release_lease] EXCEPTION - Failed to release lease {lease_key}: {e}", exc_info=True)
            return False

    def get_lease(self, lease_key: str) -> Optional[Dict]:
        """Get current lease information"""
        try:
            lease_obj = self.client.get(lease_key)
            return json.loads(lease_obj) if lease_obj else None
        except Exception as e:
            logger.error(f"Failed to get lease {lease_key}: {e}")
            return None
