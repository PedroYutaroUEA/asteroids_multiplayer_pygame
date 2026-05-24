"""Tests for server.protocol envelope and parsing."""

import json

from core.entities import UFO, Bullet, Particle
from core.utils import Vec
from core.world import World
from server.protocol import HELLO, WELCOME, envelope, parse, world_to_snapshot


def test_envelope_roundtrip_preserves_fields():
    raw = envelope(HELLO, tick=42, seq=7, data={"name": "alice"})
    msg = parse(raw)

    assert msg is not None
    assert msg["type"] == HELLO
    assert msg["tick"] == 42
    assert msg["seq"] == 7
    assert msg["data"] == {"name": "alice"}


def test_envelope_returns_str():
    raw = envelope(WELCOME, tick=0, seq=0, data={})
    assert isinstance(raw, str)


def test_parse_rejects_invalid_json():
    assert parse("not json {") is None


def test_parse_rejects_non_object_payload():
    assert parse('"just a string"') is None
    assert parse("42") is None
    assert parse("[1, 2, 3]") is None


def test_parse_rejects_missing_type():
    assert parse('{"tick": 0, "seq": 0, "data": {}}') is None


def test_parse_rejects_missing_tick():
    assert parse('{"type": "hello", "seq": 0, "data": {}}') is None


def test_parse_rejects_missing_seq():
    assert parse('{"type": "hello", "tick": 0, "data": {}}') is None


def test_parse_rejects_missing_data():
    assert parse('{"type": "hello", "tick": 0, "seq": 0}') is None


def test_parse_rejects_wrong_tick_type():
    assert parse('{"type": "hello", "tick": "0", "seq": 0, "data": {}}') is None


def test_parse_rejects_bool_as_int_for_tick():
    # JSON booleans are also ints in Python; protocol must not accept them
    # as a substitute for the numeric tick counter.
    assert parse('{"type": "hello", "tick": true, "seq": 0, "data": {}}') is None


def test_parse_rejects_non_dict_data():
    assert parse('{"type": "hello", "tick": 0, "seq": 0, "data": []}') is None
    assert parse('{"type": "hello", "tick": 0, "seq": 0, "data": "x"}') is None


def test_parse_accepts_bytes_payload():
    raw = envelope(HELLO, 0, 0, {})
    msg = parse(raw.encode())
    assert msg is not None
    assert msg["type"] == HELLO


def test_world_to_snapshot_has_required_keys():
    snap = world_to_snapshot(World())
    assert set(snap.keys()) == {
        "ships",
        "bullets",
        "asteroids",
        "ufos",
        "scores",
        "lives",
        "wave",
        "game_over",
    }


def test_snapshot_excludes_particles():
    w = World()
    w.particles.append(Particle(Vec(0, 0), Vec(0, 0), 1.0))
    snap = world_to_snapshot(w)
    assert "particles" not in snap


def test_snapshot_ship_fields_match_renderer_needs():
    snap = world_to_snapshot(World())
    assert len(snap["ships"]) == 1
    ship = snap["ships"][0]
    assert set(ship.keys()) == {
        "player_id",
        "x",
        "y",
        "angle",
        "vx",
        "vy",
        "shield_active",
        "invuln_active",
        "shield_cd_remaining",
    }
    assert ship["player_id"] == 1


def test_snapshot_asteroid_carries_position_velocity_and_size():
    w = World()
    w.spawn_asteroid(Vec(100, 200), Vec(10, 20), "L")
    snap = world_to_snapshot(w)
    spawned = [a for a in snap["asteroids"] if a["x"] == 100 and a["y"] == 200]
    assert len(spawned) == 1
    assert spawned[0] == {"x": 100, "y": 200, "vx": 10, "vy": 20, "size": "L"}


def test_snapshot_bullet_fields():
    w = World()
    w.bullets.append(Bullet(7, Vec(50, 60), Vec(5, 6)))
    snap = world_to_snapshot(w)
    assert snap["bullets"][0] == {
        "owner_id": 7,
        "x": 50,
        "y": 60,
        "vx": 5,
        "vy": 6,
    }


def test_snapshot_ufo_carries_small_flag():
    w = World()
    w.ufos.append(UFO(Vec(100, 100), small=True))
    snap = world_to_snapshot(w)
    assert any(u["small"] is True for u in snap["ufos"])


def test_snapshot_scores_and_lives_use_string_keys():
    snap = world_to_snapshot(World())
    # JSON object keys are strings; making this explicit keeps the wire
    # format stable across Python's int-key-to-string coercion.
    assert all(isinstance(k, str) for k in snap["scores"])
    assert all(isinstance(k, str) for k in snap["lives"])


def test_snapshot_is_json_serializable_end_to_end():
    w = World()
    w.spawn_asteroid(Vec(100, 200), Vec(10, 20), "L")
    w.bullets.append(Bullet(1, Vec(50, 60), Vec(5, 6)))
    w.ufos.append(UFO(Vec(100, 100), small=False))
    snap = world_to_snapshot(w)
    json.dumps(snap)  # must not raise
