"""Client-side prediction primitives (pygame-free, unit-testable).

The networked client never ran the authoritative simulation, so the
local ship lagged one round-trip behind the player's input. These
helpers re-run the *real* ship physics (`Ship.apply_command` +
`Ship.update`) on the client so the local ship responds immediately,
then ease the rendered position toward each authoritative correction.

There is exactly one source of truth for ship movement: the `Ship`
methods in core/entities.py. This module reuses them — it never
reimplements physics.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from core import config as C
from core.commands import PlayerCommand
from core.entities import Bullet, Ship
from core.utils import Vec, wrap_pos
from core.world import World


@dataclass(frozen=True, slots=True)
class PredictedInput:
    """One input the client sent, kept so it can be replayed locally.

    `dt` is the exact frame delta used when the command was sent; the
    physics is dt-scaled, so replaying with the real dt reproduces the
    trajectory the server will eventually confirm.
    """

    seq: int
    cmd: PlayerCommand
    dt: float


def _clone_for_prediction(ship: Ship) -> Ship:
    """Copy the fields prediction needs from an authoritative ship.

    Fire cooldown (`cool`) is not transmitted in the snapshot, so it
    starts inactive on the clone; that only affects fire gating during
    replay, never the ship's motion.
    """
    sim = Ship(ship.player_id, Vec(ship.pos))
    sim.vel = Vec(ship.vel)
    sim.angle = ship.angle
    sim.invuln.reset(ship.invuln.remaining)
    sim.shield.reset(ship.shield.remaining)
    sim.shield_cd.reset(ship.shield_cd.remaining)
    return sim


def simulate_from_authority(
    auth_ship: Ship, history: Sequence[PredictedInput]
) -> Ship:
    """Replay `history` on a clone of `auth_ship` using real physics.

    Reuses `Ship.apply_command` + `Ship.update` — the same code the
    server runs each tick — so there is no duplicated movement logic.
    The authoritative ship is not mutated. Fired bullets go into a
    scratch list and are discarded: prediction covers the local ship's
    motion, not authoritative bullets.
    """
    sim = _clone_for_prediction(auth_ship)
    scratch: list[Bullet] = []
    for entry in history:
        sim.apply_command(entry.cmd, entry.dt, scratch)
        sim.update(entry.dt)
    return sim


def toroidal_delta(frm: Vec, to: Vec) -> Vec:
    """Shortest vector from `frm` to `to` on the wrapping world.

    The world wraps at WORLD_WIDTH x WORLD_HEIGHT, so a naive
    subtraction would smear a correction across the whole map near a
    seam. This always takes the short way around each axis.
    """
    half_w = C.WORLD_WIDTH / 2
    half_h = C.WORLD_HEIGHT / 2
    dx = (to.x - frm.x + half_w) % C.WORLD_WIDTH - half_w
    dy = (to.y - frm.y + half_h) % C.WORLD_HEIGHT - half_h
    return Vec(dx, dy)


def toroidal_distance(a: Vec, b: Vec) -> float:
    return toroidal_delta(a, b).length()


def ease_toward(cur: Vec, goal: Vec, rate: float, dt: float) -> Vec:
    """Frame-rate-independent exponential ease along the shortest path.

    `rate` is the smoothing strength in 1/seconds. Easing over the
    toroidal delta keeps a correction from crossing the world seam.
    """
    t = 1.0 - math.exp(-rate * dt)
    return wrap_pos(cur + toroidal_delta(cur, goal) * t)


class ShipPredictor:
    """Tracks the predicted render position/angle of the local ship."""

    def __init__(self) -> None:
        self.history: list[PredictedInput] = []
        self.render_pos: Vec = Vec(0.0, 0.0)
        self.render_angle: float = 0.0
        self.has_render_state: bool = False

    def reset(self) -> None:
        self.history.clear()
        self.has_render_state = False

    def record_input(self, entry: PredictedInput) -> None:
        self.history.append(entry)

    def step(self, world: World, pid: int | None, dt: float) -> None:
        """Recompute the predicted target and ease render_pos toward it.

        The target is re-derived every frame from the latest
        authoritative ship plus the input history, so prediction never
        drifts unbounded — it is always anchored to the last snapshot.
        """
        ship = world.get_ship(pid) if pid is not None else None
        if ship is None or world.match_state != "running":
            self.has_render_state = False
            return
        target = simulate_from_authority(ship, self.history)
        # Angle is fully determined by the inputs we hold, so render it
        # directly; easing it would re-introduce rotation lag.
        self.render_angle = target.angle
        if not self.has_render_state:
            self.render_pos = Vec(target.pos)
            self.has_render_state = True
            return
        self.render_pos = ease_toward(
            self.render_pos, target.pos, C.PREDICTION_SMOOTH, dt
        )

    def rebase(
        self, world: World, pid: int | None, ack: int | None = None
    ) -> None:
        """Adopt a fresh authoritative snapshot.

        `ack` is the last input seq the server has processed (-1 if none
        yet). Discard the inputs it already reflects and keep the
        unconfirmed tail, so `step` replays exactly those onto the new
        authoritative state — classic prediction + reconciliation.
        Without an ack, drop the whole history (the snapshot is trusted
        as-is). Either way, snap on a large error between what we render
        and the reconciled target (hyperspace, respawn elsewhere)
        instead of smearing across it.
        """
        ship = world.get_ship(pid) if pid is not None else None
        if ship is None:
            self.reset()
            return
        if ack is None:
            self.history.clear()
        else:
            self.history = [e for e in self.history if e.seq > ack]
        if not self.has_render_state:
            return
        target = simulate_from_authority(ship, self.history)
        err = toroidal_distance(self.render_pos, target.pos)
        if err > C.PREDICTION_SNAP_DIST:
            self.render_pos = Vec(target.pos)
