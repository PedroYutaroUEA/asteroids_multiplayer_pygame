"""Tests for the match lifecycle: lobby -> running transition,
frag counter behavior, and single-player non-regression.

PR 1 covers only `lobby` -> `running`. The timer-driven transition to
`ended` (and the winner) lands in PR 2.
"""

from __future__ import annotations

import random

from core import config as C
from core.entities import Asteroid, Bullet
from core.utils import Vec
from core.world import World


def test_world_starts_in_lobby_when_deathmatch():
    w = World(spawn_default_player=False, deathmatch=True)
    assert w.match_state == "lobby"


def test_world_starts_running_when_not_deathmatch():
    """Single-player worlds must not see the lobby gate."""
    w = World()
    assert w.match_state == "running"


def test_lobby_update_is_noop_for_entities():
    random.seed(0)
    w = World(spawn_default_player=False, deathmatch=True)
    w.spawn_player(1)
    ast = Asteroid(Vec(100, 100), Vec(50, 0), "L")
    w.asteroids.append(ast)
    before = (ast.pos.x, ast.pos.y)

    w.update(1.0, {})

    assert w.match_state == "lobby"
    assert (ast.pos.x, ast.pos.y) == before, "asteroid must not move during lobby"


def test_lobby_update_ignores_player_commands():
    from core.commands import PlayerCommand

    w = World(spawn_default_player=False, deathmatch=True)
    w.spawn_player(1)
    ship = w.ships[1]
    before_vel = (ship.vel.x, ship.vel.y)

    w.update(0.5, {1: PlayerCommand(thrust=True)})

    assert (ship.vel.x, ship.vel.y) == before_vel, "thrust must not apply during lobby"


def test_lobby_transitions_to_running_at_min_players():
    w = World(spawn_default_player=False, deathmatch=True)
    for pid in range(1, C.MIN_PLAYERS_TO_START + 1):
        w.spawn_player(pid)

    w.update(0.01, {})

    assert w.match_state == "running"


def test_lobby_stays_when_below_min_players():
    w = World(spawn_default_player=False, deathmatch=True)
    w.spawn_player(1)

    w.update(0.01, {})

    assert w.match_state == "lobby"


def test_spawn_player_initializes_frags():
    w = World(spawn_default_player=False, deathmatch=True)
    w.spawn_player(7)
    assert w.frags[7] == 0


def test_handle_collisions_increments_world_frags():
    """End-to-end through _handle_collisions: a frag in CollisionResult
    must reach world.frags after the tick logic runs."""
    w = World(spawn_default_player=False, deathmatch=True)
    w.spawn_player(1)
    w.spawn_player(2)
    target = w.ships[2]
    target.invuln.reset(0.0)  # disable post-spawn invuln so the hit lands
    w.bullets.append(Bullet(1, Vec(target.pos.x, target.pos.y), Vec(0, 0)))

    w._handle_collisions()

    assert w.frags[1] == 1
    assert w.frags[2] == 0


def test_handle_collisions_ignores_self_bullet_frags():
    """A bullet whose owner matches the ship's player_id never registers
    a frag, even if the geometry would otherwise overlap."""
    w = World(spawn_default_player=False, deathmatch=True)
    w.spawn_player(1)
    ship = w.ships[1]
    ship.invuln.reset(0.0)
    w.bullets.append(Bullet(1, Vec(ship.pos.x, ship.pos.y), Vec(0, 0)))

    w._handle_collisions()

    assert w.frags[1] == 0
