# Server-Sent Events (SSE) Contract

Endpoint: `GET /api/junctions/{id}/stream`

## Protocol Specification
- Content-Type: `text/event-stream`
- Cache-Control: `no-cache`
- Connection: `keep-alive`

## Message Format

### 1. Status Event
Sent immediately on connection established, and subsequently after every committed state change for the given junction.

```http
event: status
data: {"junction_id": "A", "mode": "AUTOMATIC", "phase": "NS", "controller_status": "ONLINE", "desired_signals": {"NORTH": "GREEN", "SOUTH": "GREEN", "EAST": "RED", "WEST": "RED"}, "actual_signals": {"NORTH": "GREEN", "SOUTH": "GREEN", "EAST": "RED", "WEST": "RED"}, "queues": {"NORTH": 3, "SOUTH": 1, "EAST": 7, "WEST": 2}, "transition": {"step": "GREEN", "target": null, "deadline_at": 1728123456.78}, "pending_commands": [], "emergency": {"active": false, "direction": null, "vehicle_id": null}, "manual": {"active": false, "lease_expires_at": null, "issued_by": null}, "alerts": [], "device_statuses": {"SIGNAL_CONTROLLER": {"status": "ONLINE"}}, "stale_queues": []}

```

### 2. Heartbeat Ping
Sent every 15 seconds (P-03) if no status event was transmitted, to prevent proxy/firewall idle connection timeouts.

```http
: ping

```

## Client Reconnection Behavior
- The client may reconnect at any time.
- Upon reconnect, the server immediately emits a fresh `event: status` message containing the current junction state snapshot.
- Per D-05: If SSE fails twice in a row, the client frontend falls back to polling `GET /api/junctions/{id}/status` every 2 seconds.
