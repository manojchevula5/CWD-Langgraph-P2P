Production transport guidance

This repo uses an in-process `A2ARouter` for local tests/examples. For production
(or Azure Container Apps), replace the in-process router with a durable
transport adapter. Recommended options:

- Azure Service Bus (queues/topics): best for command/control and reliable
  delivery. Supports DLQ, sessions, ordering, and managed identity.
- Dapr pub/sub: provides a vendor-agnostic pub/sub API with adapters for many backends
  (Service Bus, Redis, Kafka). Good for portable architecture.
- Azure Event Grid / Event Hubs: for high-throughput telemetry or event-driven
  reactions (Event Grid) or stream processing (Event Hubs).
- Redis pub/sub: low-latency but no delivery guarantees.

How to wire an adapter

1. Implement `TransportAdapter` (see `core/a2a_transport.py`).
2. Create a concrete adapter (e.g. `ServiceBusAdapter`) that implements `send` and
   `start/stop` as needed.
3. Modify `A2AClient._send` to call the configured adapter when present instead of
   routing through `GLOBAL_A2A_ROUTER`.

Security

- Use Managed Identity (recommended) or connection strings stored in Key Vault.
- Use message properties (correlation id, origin) and include signing or tokens for
  message authenticity. With Service Bus you can use shared access or Azure AD.

Testing

- Keep the `A2ARouter` for local dev and tests.
- Use Dapr or service emulator for integration tests where possible.
