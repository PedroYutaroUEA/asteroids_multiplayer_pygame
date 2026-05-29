"""Tests for the multi-room server registry introduced in F5 PR 1.

Most of these cover plumbing that does not need a real WebSocket — the
``_handshake``/``_handle_connection`` flow exposes its decisions
through ``Server`` state (``self.worlds``, ``self.room_by_player_id``)
which can be probed directly with a tiny in-process fake.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from typing import Any

import pytest

from core import config as C
from core.commands import PlayerCommand
from server.main import Server


class FakeWebSocket:
    """Minimal async-iterable WebSocket double used by handshake tests.

    Replays a queue of incoming text frames through ``recv()``;
    captures everything sent by the server into ``sent``.
    """

    def __init__(self, incoming: list[str]) -> None:
        self._incoming = deque(incoming)
        self.sent: list[str] = []
        self.closed = False

    async def recv(self) -> str:
        if not self._incoming:
            raise asyncio.CancelledError("no more frames")
        return self._incoming.popleft()

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        if not self._incoming:
            raise StopAsyncIteration
        return self._incoming.popleft()


VALID_TOKEN = "t"


def _hello(name: str = "alice", **data: Any) -> str:
    payload = {"name": name, "token": VALID_TOKEN, **data}
    return json.dumps({"type": "hello", "tick": 0, "seq": 0, "data": payload})


def _last_reject_reason(ws: FakeWebSocket) -> str | None:
    for raw in reversed(ws.sent):
        msg = json.loads(raw)
        if msg["type"] == "reject":
            return msg["data"].get("reason")
    return None


def test_server_creates_n_worlds_on_boot():
    server = Server("127.0.0.1", 0, allowed_tokens={VALID_TOKEN}, rooms=3)
    assert set(server.worlds.keys()) == {0, 1, 2}
    for world in server.worlds.values():
        assert world.deathmatch is True
        assert world.match_state == "lobby"


def test_server_rejects_zero_or_negative_rooms():
    with pytest.raises(ValueError):
        Server("127.0.0.1", 0, allowed_tokens={VALID_TOKEN}, rooms=0)


def test_drain_inputs_pops_one_per_player_by_room():
    server = Server("127.0.0.1", 0, allowed_tokens={VALID_TOKEN}, rooms=2)
    cmd_a = PlayerCommand(thrust=True)
    cmd_b = PlayerCommand(shoot=True)
    server._input_queues = {
        1: deque([(10, cmd_a)]),
        2: deque([(20, cmd_b)]),
        3: deque([(30, cmd_a)]),
    }
    server.room_by_player_id = {1: 0, 2: 1, 3: 0}

    assert server._drain_inputs_for_room(0) == {1: cmd_a, 3: cmd_a}
    assert server._drain_inputs_for_room(1) == {2: cmd_b}
    # Consumed: queues now empty and the last seq recorded for the ack.
    assert server._last_processed_seq == {1: 10, 2: 20, 3: 30}
    assert all(len(q) == 0 for q in server._input_queues.values())


def test_drain_inputs_omits_starved_players():
    server = Server("127.0.0.1", 0, allowed_tokens={VALID_TOKEN}, rooms=1)
    cmd = PlayerCommand(thrust=True)
    server._input_queues = {1: deque([(5, cmd)]), 2: deque()}
    server.room_by_player_id = {1: 0, 2: 0}

    # Player 2 has no queued input -> omitted (its ship coasts).
    assert server._drain_inputs_for_room(0) == {1: cmd}
    # Player 1's queue is now empty too -> next tick both coast.
    assert server._drain_inputs_for_room(0) == {}
    assert server._last_processed_seq == {1: 5}


def test_enqueue_input_caps_queue_length():
    server = Server("127.0.0.1", 0, allowed_tokens={VALID_TOKEN}, rooms=1)
    cmd = PlayerCommand()
    for s in range(C.INPUT_QUEUE_CAP + 5):
        server._enqueue_input(1, s, cmd)

    q = server._input_queues[1]
    assert len(q) == C.INPUT_QUEUE_CAP
    # The five oldest (seqs 0..4) were dropped; newest is kept.
    assert q[0][0] == 5
    assert q[-1][0] == C.INPUT_QUEUE_CAP + 4


def test_broadcast_injects_per_player_ack():
    server = Server("127.0.0.1", 0, allowed_tokens={VALID_TOKEN}, rooms=1)
    ws = FakeWebSocket([])
    pid = 1
    server.connections[pid] = ws
    server.room_by_player_id[pid] = 0
    server._names_by_player_id[pid] = "alice"
    server.worlds[0].spawn_player(pid)
    server._last_processed_seq[pid] = 42

    asyncio.run(server._broadcast_snapshot())

    assert ws.sent, "expected a snapshot to be sent"
    msg = json.loads(ws.sent[-1])
    assert msg["type"] == "snapshot"
    assert msg["data"]["ack"] == 42


def test_broadcast_ack_defaults_to_negative_one():
    server = Server("127.0.0.1", 0, allowed_tokens={VALID_TOKEN}, rooms=1)
    ws = FakeWebSocket([])
    pid = 1
    server.connections[pid] = ws
    server.room_by_player_id[pid] = 0
    server._names_by_player_id[pid] = "alice"
    server.worlds[0].spawn_player(pid)
    # No input processed yet: the ack sentinel must be -1, never 0, so
    # the client does not prune its real seq-0 input.
    asyncio.run(server._broadcast_snapshot())

    msg = json.loads(ws.sent[-1])
    assert msg["data"]["ack"] == -1


def test_pids_in_room_returns_only_matching_players():
    server = Server("127.0.0.1", 0, allowed_tokens={VALID_TOKEN}, rooms=2)
    server.room_by_player_id = {1: 0, 2: 1, 3: 0, 4: 1}
    assert sorted(server._pids_in_room(0)) == [1, 3]
    assert sorted(server._pids_in_room(1)) == [2, 4]


def test_handshake_accepts_valid_room_id():
    server = Server("127.0.0.1", 0, allowed_tokens={VALID_TOKEN}, rooms=2)
    ws = FakeWebSocket([_hello(name="alice", room_id=1)])

    result = asyncio.run(server._handshake(ws))

    assert result is not None
    player_id, name, room_id, is_spectator = result
    assert name == "alice"
    assert room_id == 1
    assert is_spectator is False
    welcome = json.loads(ws.sent[-1])
    assert welcome["type"] == "welcome"
    assert welcome["data"]["player_id"] == player_id


def test_handshake_defaults_room_id_to_zero_when_missing():
    """Pre-F5 clients omit room_id; server falls back to room 0."""
    server = Server("127.0.0.1", 0, allowed_tokens={VALID_TOKEN}, rooms=1)
    ws = FakeWebSocket([_hello(name="legacy")])

    result = asyncio.run(server._handshake(ws))

    assert result is not None
    _, _, room_id, _ = result
    assert room_id == 0


def test_handshake_rejects_invalid_room_id():
    server = Server("127.0.0.1", 0, allowed_tokens={VALID_TOKEN}, rooms=2)
    ws = FakeWebSocket([_hello(name="x", room_id=99)])

    result = asyncio.run(server._handshake(ws))

    assert result is None
    assert _last_reject_reason(ws) == "invalid_room"
    assert ws.closed is True


def test_handshake_rejects_non_int_room_id():
    server = Server("127.0.0.1", 0, allowed_tokens={VALID_TOKEN}, rooms=2)
    ws = FakeWebSocket([_hello(name="x", room_id="zero")])

    result = asyncio.run(server._handshake(ws))

    assert result is None
    assert _last_reject_reason(ws) == "invalid_room"


def test_handshake_rejects_bool_as_room_id():
    """A JSON `true` is `int` in Python; explicit guard keeps it out."""
    server = Server("127.0.0.1", 0, allowed_tokens={VALID_TOKEN}, rooms=2)
    raw = json.dumps(
        {
            "type": "hello",
            "tick": 0,
            "seq": 0,
            "data": {"name": "x", "token": VALID_TOKEN, "room_id": True},
        }
    )
    ws = FakeWebSocket([raw])

    result = asyncio.run(server._handshake(ws))

    assert result is None
    assert _last_reject_reason(ws) == "invalid_room"


def test_handshake_rejects_when_room_is_full():
    server = Server("127.0.0.1", 0, allowed_tokens={VALID_TOKEN}, rooms=2)
    # Saturate room 0.
    server.room_by_player_id = {pid: 0 for pid in range(1, C.MAX_PLAYERS + 1)}
    ws = FakeWebSocket([_hello(name="x", room_id=0)])

    result = asyncio.run(server._handshake(ws))

    assert result is None
    assert _last_reject_reason(ws) == "room_full"


def test_handshake_accepts_when_target_room_has_space():
    """Room 0 is full but room 1 should still accept."""
    server = Server("127.0.0.1", 0, allowed_tokens={VALID_TOKEN}, rooms=2)
    server.room_by_player_id = {pid: 0 for pid in range(1, C.MAX_PLAYERS + 1)}
    ws = FakeWebSocket([_hello(name="x", room_id=1)])

    result = asyncio.run(server._handshake(ws))

    assert result is not None
    _, _, room_id, _ = result
    assert room_id == 1


def test_despawn_only_touches_correct_room():
    """Disconnect cleanup must not leak across rooms."""
    server = Server("127.0.0.1", 0, allowed_tokens={VALID_TOKEN}, rooms=2)
    server.worlds[0].spawn_player(1)
    server.worlds[1].spawn_player(2)
    server.room_by_player_id[1] = 0
    server.room_by_player_id[2] = 1

    # Mimic the finally branch of `_handle_connection` for pid=1.
    room_id = server.room_by_player_id.pop(1)
    server.worlds[room_id].despawn_player(1)

    assert 1 not in server.worlds[0].ships
    assert 2 in server.worlds[1].ships
    assert server.worlds[1].scores[2] == 0


def test_restart_request_only_resets_owning_room():
    server = Server("127.0.0.1", 0, allowed_tokens={VALID_TOKEN}, rooms=2)
    # Both rooms reach `ended`.
    for room_id, world in server.worlds.items():
        world.spawn_player(10 + room_id)
        world.match_state = "ended"
        world.winner_id = 10 + room_id
        world.frags[10 + room_id] = C.FRAG_LIMIT
        server.room_by_player_id[10 + room_id] = room_id

    server._handle_restart_request(10)  # restarts only room 0

    assert server.worlds[0].match_state == "lobby"
    assert server.worlds[0].winner_id is None
    assert server.worlds[1].match_state == "ended"
    assert server.worlds[1].winner_id == 11


def test_restart_request_noop_when_match_not_ended():
    server = Server("127.0.0.1", 0, allowed_tokens={VALID_TOKEN}, rooms=1)
    server.worlds[0].spawn_player(1)
    server.room_by_player_id[1] = 0
    # match_state is "lobby" right after spawn_player

    server._handle_restart_request(1)

    assert server.worlds[0].match_state == "lobby"  # unchanged


def test_restart_request_noop_for_unknown_player():
    """Idempotent — unknown pid (e.g. ghost connection) is a no-op."""
    server = Server("127.0.0.1", 0, allowed_tokens={VALID_TOKEN}, rooms=1)
    server._handle_restart_request(999)
    # nothing raised, no state mutated
    assert server.worlds[0].match_state == "lobby"
