"""Asteroids multiplayer server entry point.

The server owns a single authoritative `World`, advances it at FPS (60 Hz),
and broadcasts a serialized snapshot to every connected client at
SNAPSHOT_HZ (30 Hz). Client input is not yet wired — that lands with the
networked player client in the next PR.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
from typing import Any

import websockets

from core import config as C
from core.world import World
from server.protocol import (
    HELLO,
    REJECT,
    SNAPSHOT,
    WELCOME,
    envelope,
    parse,
    world_to_snapshot,
)

HANDSHAKE_TIMEOUT = 5.0


class Server:
    """Connection lifecycle and per-client handshake.

    ``connections`` is the set of accepted clients indexed by the
    server-assigned ``player_id``. New ids are handed out by an incrementing
    counter; ids are not reused across disconnects (simpler than a free list,
    and there is no reason to reuse them at this stage).
    """

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.tick = 0
        # The websocket connection type differs slightly between websockets
        # 13 (legacy) and 14+ (asyncio). Both expose recv/send/close and
        # async iteration, so Any keeps the API surface narrow.
        self.connections: dict[int, Any] = {}
        self._next_player_id = 1
        self._seq_by_player_id: dict[int, int] = {}

        self.world = World()

    async def run(self) -> None:
        async with websockets.serve(self._handle_connection, self.host, self.port):
            print(f"asteroids server listening on ws://{self.host}:{self.port}")
            await asyncio.gather(self._tick_loop(), self._snapshot_loop())

    async def _tick_loop(self) -> None:
        dt = 1.0 / C.FPS
        period = 1.0 / C.FPS
        while True:
            await asyncio.sleep(period)
            self.world.update(dt, {})
            self.tick += 1

    async def _snapshot_loop(self) -> None:
        period = 1.0 / C.SNAPSHOT_HZ
        while True:
            await asyncio.sleep(period)
            await self._broadcast_snapshot()

    async def _broadcast_snapshot(self) -> None:
        if not self.connections:
            return
        snap = world_to_snapshot(self.world)
        for player_id, ws in list(self.connections.items()):
            seq = self._seq_by_player_id.get(player_id, 0)
            self._seq_by_player_id[player_id] = seq + 1
            # Connection handler cleans up its own slot on close; skipping
            # this client for the current frame is the right local response.
            with contextlib.suppress(websockets.ConnectionClosed):
                await ws.send(envelope(SNAPSHOT, self.tick, seq, snap))

    async def _handle_connection(self, ws: Any) -> None:
        player_id = await self._handshake(ws)
        if player_id is None:
            return

        self.connections[player_id] = ws
        try:
            async for _ in ws:
                pass  # input handling lands in a later PR
        finally:
            self.connections.pop(player_id, None)
            self._seq_by_player_id.pop(player_id, None)

    async def _handshake(self, ws: Any) -> int | None:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=HANDSHAKE_TIMEOUT)
        except TimeoutError:
            await ws.close()
            return None
        except websockets.ConnectionClosed:
            return None

        msg = parse(raw)
        if msg is None or msg["type"] != HELLO:
            await ws.close()
            return None

        if len(self.connections) >= C.MAX_PLAYERS:
            await ws.send(envelope(REJECT, self.tick, 0, {"reason": "server_full"}))
            await ws.close()
            return None

        player_id = self._next_player_id
        self._next_player_id += 1

        await ws.send(envelope(WELCOME, self.tick, 0, {"player_id": player_id}))
        return player_id


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="server",
        description="Asteroids multiplayer server (LAN deathmatch).",
    )
    parser.add_argument("--host", default="0.0.0.0", help="bind address (default: 0.0.0.0)")
    parser.add_argument("--port", default=8765, type=int, help="bind port (default: 8765)")
    args = parser.parse_args()

    try:
        asyncio.run(Server(args.host, args.port).run())
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
