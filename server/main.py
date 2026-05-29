"""Asteroids multiplayer server entry point.

The server owns a single authoritative `World`, advances it at FPS (60 Hz),
and broadcasts a serialized snapshot to every connected client at
SNAPSHOT_HZ (30 Hz). Each client owns one ship — spawned at the welcome
handshake and removed on disconnect — and pushes INPUT messages into a
per-player queue that the tick loop drains one entry per tick. The last
consumed input seq is echoed back in each snapshot (the ack) so the
client can reconcile its prediction against the authoritative state.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

import websockets

from core import config as C
from core.commands import PlayerCommand
from core.world import World
from multiplayer.command_codec import dict_to_command
from server.auth import load_tokens
from server.protocol import (
    HELLO,
    INPUT,
    REJECT,
    RESTART_REQUEST,
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

    def __init__(
        self,
        host: str,
        port: int,
        allowed_tokens: set[str],
        rooms: int = C.DEFAULT_ROOMS,
        profile_broadcast: bool = False,
    ) -> None:
        if rooms < 1:
            raise ValueError(f"rooms must be >= 1, got {rooms}")
        if not allowed_tokens:
            raise ValueError("allowed_tokens must not be empty")
        self.host = host
        self.port = port
        self.allowed_tokens = allowed_tokens
        self.profile_broadcast = profile_broadcast
        self.tick = 0
        # The websocket connection type differs slightly between websockets
        # 13 (legacy) and 14+ (asyncio). Both expose recv/send/close and
        # async iteration, so Any keeps the API surface narrow.
        self.connections: dict[int, Any] = {}
        self._next_player_id = 1
        self._seq_by_player_id: dict[int, int] = {}
        # Per-player FIFO of (client_seq, command). The tick loop consumes
        # exactly one entry per player per tick, so the server's trajectory
        # is reproducible on the client for prediction/replay; the last
        # consumed seq is echoed back as the snapshot ack. An empty queue
        # means the ship coasts that tick. This replaces the old sticky
        # "latest input wins" slot, which could not be reconciled because
        # the client could not know how many times a command was applied.
        self._input_queues: dict[int, deque[tuple[int, PlayerCommand]]] = {}
        self._last_processed_seq: dict[int, int] = {}
        # Display names from the HELLO handshake, forwarded into every
        # snapshot so each client can render a scoreboard.
        self._names_by_player_id: dict[int, str] = {}
        # Each player_id belongs to exactly one room; populated at handshake
        # acceptance and consulted by tick, broadcast, and cleanup paths.
        self.room_by_player_id: dict[int, int] = {}
        # Connections that joined as read-only spectators. They get
        # snapshots from their room but never spawn a ship, never send
        # INPUT or RESTART_REQUEST, and do not count toward room cap.
        self.spectator_pids: set[int] = set()

        self.worlds: dict[int, World] = {
            i: World(spawn_default_player=False, deathmatch=True)
            for i in range(rooms)
        }

    async def run(self) -> None:
        async with websockets.serve(
            self._handle_connection, self.host, self.port
        ):
            print(
                f"asteroids server listening on ws://{self.host}:{self.port}"
            )
            await asyncio.gather(self._tick_loop(), self._snapshot_loop())

    async def _tick_loop(self) -> None:
        dt = 1.0 / C.FPS
        period = 1.0 / C.FPS
        while True:
            await asyncio.sleep(period)
            for room_id, world in self.worlds.items():
                prev_state = world.match_state
                prev_deaths = dict(world.deaths)
                world.update(dt, self._drain_inputs_for_room(room_id))
                self._log_world_events(room_id, world, prev_state, prev_deaths)
            self.tick += 1

    def _log_world_events(
        self,
        room_id: int,
        world: World,
        prev_state: str,
        prev_deaths: dict[int, int],
    ) -> None:
        if prev_state != world.match_state:
            if world.match_state == "running":
                print(f"match started: room={room_id}", flush=True)
            elif world.match_state == "ended":
                print(
                    f"match ended: room={room_id}, "
                    f"winner={self._name_for(world.winner_id)}",
                    flush=True,
                )
        for pid, n in world.deaths.items():
            if n > prev_deaths.get(pid, 0):
                print(
                    f"ship killed: {self._name_for(pid)} "
                    f"(pid={pid}, room={room_id})",
                    flush=True,
                )

    def _name_for(self, player_id: int | None) -> str:
        if player_id is None:
            return "?"
        return self._names_by_player_id.get(player_id, f"P{player_id}")

    def _drain_inputs_for_room(self, room_id: int) -> dict[int, PlayerCommand]:
        """Pop one queued input per player in the room for this tick.

        Records each consumed seq for the snapshot ack. A player whose
        queue is empty is omitted, so their ship simply coasts this tick
        (the deterministic starvation policy that keeps the server's
        trajectory reproducible for client-side reconciliation).
        """
        commands: dict[int, PlayerCommand] = {}
        for pid in self._pids_in_room(room_id):
            queue = self._input_queues.get(pid)
            if not queue:
                continue
            seq, cmd = queue.popleft()
            self._last_processed_seq[pid] = seq
            commands[pid] = cmd
        return commands

    def _enqueue_input(
        self, player_id: int, seq: int, cmd: PlayerCommand
    ) -> None:
        """Append an input to a player's queue, capping its length.

        The cap bounds how much input latency can build up if a client
        ever sends faster than the server drains; the oldest entry is
        dropped first.
        """
        queue = self._input_queues.setdefault(player_id, deque())
        queue.append((seq, cmd))
        if len(queue) > C.INPUT_QUEUE_CAP:
            queue.popleft()

    def _names_for_room(self, room_id: int) -> dict[int, str]:
        return {
            pid: name
            for pid, name in self._names_by_player_id.items()
            if self.room_by_player_id.get(pid) == room_id
        }

    def _pids_in_room(self, room_id: int) -> list[int]:
        return [
            pid
            for pid, rid in self.room_by_player_id.items()
            if rid == room_id
        ]

    def _player_pids_in_room(self, room_id: int) -> list[int]:
        """`_pids_in_room` minus spectators; used for the room cap."""
        return [
            pid
            for pid in self._pids_in_room(room_id)
            if pid not in self.spectator_pids
        ]

    async def _snapshot_loop(self) -> None:
        period = 1.0 / C.SNAPSHOT_HZ
        while True:
            await asyncio.sleep(period)
            await self._broadcast_snapshot()

    async def _broadcast_snapshot(self) -> None:
        if not self.connections:
            return
        if self.profile_broadcast:
            t0 = time.perf_counter()
        bytes_total = 0
        for room_id, world in self.worlds.items():
            pids = self._pids_in_room(room_id)
            if not pids:
                continue
            snap = world_to_snapshot(
                world, names=self._names_for_room(room_id)
            )
            for player_id in pids:
                ws = self.connections.get(player_id)
                if ws is None:
                    continue
                seq = self._seq_by_player_id.get(player_id, 0)
                self._seq_by_player_id[player_id] = seq + 1
                # Per-player ack of the last input the tick loop consumed
                # (-1 until the first one). Shallow copy so each client
                # gets its own ack without rebuilding the room snapshot.
                data = dict(snap)
                data["ack"] = self._last_processed_seq.get(player_id, -1)
                payload = envelope(SNAPSHOT, self.tick, seq, data)
                # Connection handler cleans up its own slot on close;
                # skipping this client for the current frame is the
                # right local response.
                with contextlib.suppress(websockets.ConnectionClosed):
                    await ws.send(payload)
                    bytes_total += len(payload)
        if self.profile_broadcast:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            print(
                f"broadcast tick={self.tick} "
                f"ms={elapsed_ms:.2f} "
                f"bytes={bytes_total} "
                f"conns={len(self.connections)} "
                f"rooms={len(self.worlds)}",
                file=sys.stderr,
            )

    async def _handle_connection(self, ws: Any) -> None:
        result = await self._handshake(ws)
        if result is None:
            return
        player_id, name, room_id, is_spectator = result

        self.connections[player_id] = ws
        self._names_by_player_id[player_id] = name
        self.room_by_player_id[player_id] = room_id
        if is_spectator:
            self.spectator_pids.add(player_id)
        else:
            self.worlds[room_id].spawn_player(player_id)
            print(
                f"ship spawned: {name} (pid={player_id}, room={room_id})",
                flush=True,
            )
        try:
            async for raw in ws:
                msg = parse(raw)
                if msg is None:
                    continue
                if player_id in self.spectator_pids:
                    # Spectators are read-only; drop any unsolicited input
                    # or restart attempt silently. Defense in depth — the
                    # client side already refuses to send these.
                    continue
                if msg["type"] == INPUT:
                    self._enqueue_input(
                        player_id,
                        msg["seq"],
                        dict_to_command(msg["data"]),
                    )
                elif msg["type"] == RESTART_REQUEST:
                    self._handle_restart_request(player_id)
        finally:
            room_id = self.room_by_player_id.pop(player_id, 0)
            was_spectator = player_id in self.spectator_pids
            self.spectator_pids.discard(player_id)
            self.connections.pop(player_id, None)
            self._seq_by_player_id.pop(player_id, None)
            self._input_queues.pop(player_id, None)
            self._last_processed_seq.pop(player_id, None)
            self._names_by_player_id.pop(player_id, None)
            world = self.worlds.get(room_id)
            if world is not None and not was_spectator:
                world.despawn_player(player_id)

    def _handle_restart_request(self, player_id: int) -> None:
        """Reset only the room that ``player_id`` belongs to and re-spawn
        every player currently connected to that room.

        Idempotent: a request that arrives outside ``ended`` is a no-op,
        so duplicate ENTER presses from multiple clients cause one reset.
        """
        room_id = self.room_by_player_id.get(player_id)
        if room_id is None:
            return
        world = self.worlds.get(room_id)
        if world is None or world.match_state != "ended":
            return
        world.reset()
        for pid in self._pids_in_room(room_id):
            world.spawn_player(pid)

    async def _handshake(self, ws: Any) -> tuple[int, str, int, bool] | None:
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

        token = msg["data"].get("token", "")
        if not isinstance(token, str) or token not in self.allowed_tokens:
            await self._reject_and_close(ws, "unauthorized")
            return None

        room_id = msg["data"].get("room_id", 0)
        if not isinstance(room_id, int) or isinstance(room_id, bool):
            await self._reject_and_close(ws, "invalid_room")
            return None
        if room_id not in self.worlds:
            await self._reject_and_close(ws, "invalid_room")
            return None

        is_spectator = bool(msg["data"].get("spectator", False))
        if (
            not is_spectator
            and len(self._player_pids_in_room(room_id)) >= C.MAX_PLAYERS
        ):
            await self._reject_and_close(ws, "room_full")
            return None

        player_id = self._next_player_id
        self._next_player_id += 1

        raw_name = msg["data"].get("name", "")
        name = (raw_name if isinstance(raw_name, str) else "").strip()[:16]
        if not name:
            name = f"P{player_id}"

        await ws.send(
            envelope(WELCOME, self.tick, 0, {"player_id": player_id})
        )
        return player_id, name, room_id, is_spectator

    async def _reject_and_close(self, ws: Any, reason: str) -> None:
        await ws.send(envelope(REJECT, self.tick, 0, {"reason": reason}))
        await ws.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="server",
        description="Asteroids multiplayer server (LAN deathmatch).",
    )
    parser.add_argument(
        "--host", default="0.0.0.0", help="bind address (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", default=8765, type=int, help="bind port (default: 8765)"
    )
    parser.add_argument(
        "--rooms",
        default=C.DEFAULT_ROOMS,
        type=int,
        help=f"number of concurrent rooms (default: {C.DEFAULT_ROOMS})",
    )
    parser.add_argument(
        "--tokens-file",
        default="tokens.txt",
        type=Path,
        help="path to token allowlist file (default: tokens.txt)",
    )
    parser.add_argument(
        "--profile-broadcast",
        action="store_true",
        help="log ms and bytes per broadcast to stderr",
    )
    args = parser.parse_args()

    try:
        allowed_tokens = load_tokens(args.tokens_file)
    except (FileNotFoundError, ValueError) as exc:
        print(f"failed to load tokens: {exc}", file=sys.stderr)
        sys.exit(2)

    server = Server(
        args.host,
        args.port,
        allowed_tokens=allowed_tokens,
        rooms=args.rooms,
        profile_broadcast=args.profile_broadcast,
    )
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
