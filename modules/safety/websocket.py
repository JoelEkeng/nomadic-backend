"""WebSocket endpoint for live trip sharing.

Clients connect with a valid share token and receive real-time updates
about the driver's location, ETA, and trip status changes.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from core.database import get_db
from modules.rides.repository import RideRepository
from modules.safety.repository import TripShareTokenRepository

logger = logging.getLogger(__name__)

ws_router = APIRouter()

# In-memory store of active WebSocket connections per ride_id
# In production, this would be backed by Redis pub/sub for horizontal scaling
_active_connections: dict[str, list[WebSocket]] = {}


class ConnectionManager:
    """Manages WebSocket connections for trip sharing."""

    def __init__(self):
        self.connections: dict[str, list[WebSocket]] = {}

    async def connect(self, ride_id: str, websocket: WebSocket):
        await websocket.accept()
        if ride_id not in self.connections:
            self.connections[ride_id] = []
        self.connections[ride_id].append(websocket)
        logger.info("WebSocket connected for ride %s (total: %d)", ride_id, len(self.connections[ride_id]))

    def disconnect(self, ride_id: str, websocket: WebSocket):
        if ride_id in self.connections:
            self.connections[ride_id] = [ws for ws in self.connections[ride_id] if ws != websocket]
            if not self.connections[ride_id]:
                del self.connections[ride_id]

    async def broadcast_to_ride(self, ride_id: str, message: dict):
        if ride_id not in self.connections:
            return
        dead = []
        for ws in self.connections[ride_id]:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ride_id, ws)

    @property
    def active_ride_ids(self) -> list[str]:
        return list(self.connections.keys())


manager = ConnectionManager()


@ws_router.websocket("/ws/share/{token}")
async def websocket_trip_share(websocket: WebSocket, token: str):
    """WebSocket endpoint for live trip tracking via share token.

    Validates the share token, then streams location updates and status changes.
    """
    # Validate token using a fresh DB session
    from core.database import SessionLocal

    db = SessionLocal()
    try:
        share_repo = TripShareTokenRepository(db)
        share = share_repo.get_by_token(token)

        if share is None or share.expires_at < datetime.now(timezone.utc):
            await websocket.close(code=4001, reason="Invalid or expired token")
            return

        ride_id = share.ride_id
        ride_repo = RideRepository(db)
        ride = ride_repo.get_by_id(ride_id)

        if ride is None:
            await websocket.close(code=4004, reason="Ride not found")
            return
    finally:
        db.close()

    await manager.connect(ride_id, websocket)

    try:
        # Send initial state
        await websocket.send_json({
            "type": "initial",
            "data": {
                "ride_id": ride_id,
                "status": ride.status,
                "pickup": ride.pickup_location,
                "destination": ride.destination_location,
            },
        })

        # Keep connection alive and listen for client pings
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                # Send keepalive
                try:
                    await websocket.send_json({"type": "keepalive"})
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("WebSocket error for ride %s: %s", ride_id, e)
    finally:
        manager.disconnect(ride_id, websocket)


async def broadcast_location_update(ride_id: str, latitude: float, longitude: float, eta: str | None = None):
    """Called by the location update handler to broadcast to all watchers."""
    await manager.broadcast_to_ride(ride_id, {
        "type": "location_update",
        "data": {
            "latitude": latitude,
            "longitude": longitude,
            "eta": eta,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    })


async def broadcast_status_update(ride_id: str, new_status: str):
    """Called when ride status changes to notify all watchers."""
    await manager.broadcast_to_ride(ride_id, {
        "type": "status_update",
        "data": {
            "status": new_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    })
