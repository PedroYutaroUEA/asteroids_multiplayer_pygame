"""Unit tests for client-side prediction (no pygame, no network)."""

from core import config as C
from core.commands import PlayerCommand
from core.entities import Ship
from core.utils import Vec
from core.world import World
from multiplayer.prediction import (
    PredictedInput,
    ShipPredictor,
    ease_toward,
    simulate_from_authority,
    toroidal_delta,
    toroidal_distance,
)

DT = 1.0 / 60.0


def _ship(pid=1, pos=(1000, 1000), vel=(0, 0), angle=0.0):
    s = Ship(pid, Vec(pos))
    s.vel = Vec(vel)
    s.angle = angle
    return s


def _running_world(*ships):
    w = World(spawn_default_player=False, deathmatch=True)
    w.match_state = "running"
    for s in ships:
        w.ships[s.player_id] = s
    return w


# --- simulate_from_authority --------------------------------------------


def test_simulate_empty_history_is_identity():
    auth = _ship(vel=(30, -10), angle=45.0)
    out = simulate_from_authority(auth, [])
    assert (out.pos.x, out.pos.y) == (auth.pos.x, auth.pos.y)
    assert (out.vel.x, out.vel.y) == (auth.vel.x, auth.vel.y)
    assert out.angle == auth.angle


def test_simulate_does_not_mutate_authority():
    auth = _ship(vel=(30, -10), angle=45.0)
    hist = [PredictedInput(0, PlayerCommand(thrust=True), DT)]
    simulate_from_authority(auth, hist)
    assert (auth.pos.x, auth.pos.y) == (1000, 1000)
    assert (auth.vel.x, auth.vel.y) == (30, -10)
    assert auth.angle == 45.0


def test_simulate_matches_real_ship_physics():
    # The predictor must reuse the real Ship methods (single source of
    # truth): replaying one thrust input must equal calling the Ship
    # methods directly.
    auth = _ship(vel=(0, 0), angle=0.0)
    ref = _ship(vel=(0, 0), angle=0.0)
    cmd = PlayerCommand(thrust=True)

    out = simulate_from_authority(auth, [PredictedInput(0, cmd, DT)])

    ref.apply_command(cmd, DT, [])
    ref.update(DT)
    assert out.pos.x == ref.pos.x
    assert out.pos.y == ref.pos.y
    assert out.vel.x == ref.vel.x
    assert out.vel.y == ref.vel.y


def test_simulate_rotation_accumulates():
    auth = _ship(angle=0.0)
    hist = [
        PredictedInput(i, PlayerCommand(rotate_left=True), DT)
        for i in range(5)
    ]
    out = simulate_from_authority(auth, hist)
    assert out.angle == 0.0 - 5 * C.SHIP_TURN_SPEED * DT


def test_simulate_hyperspace_does_not_move_locally():
    # Hyperspace is handled at the World level, not in Ship.apply_command,
    # so the predictor must never teleport on its own.
    auth = _ship(vel=(0, 0))
    hist = [PredictedInput(0, PlayerCommand(hyperspace=True), DT)]
    out = simulate_from_authority(auth, hist)
    assert (out.pos.x, out.pos.y) == (1000, 1000)


# --- toroidal helpers ----------------------------------------------------


def test_toroidal_delta_plain():
    d = toroidal_delta(Vec(100, 100), Vec(250, 130))
    assert (d.x, d.y) == (150, 30)


def test_toroidal_delta_wraps_seam():
    d = toroidal_delta(Vec(C.WORLD_WIDTH - 5, 10), Vec(5, 10))
    assert d.x == 10
    assert d.y == 0


def test_toroidal_distance_uses_short_way():
    dist = toroidal_distance(Vec(C.WORLD_WIDTH - 5, 0), Vec(5, 0))
    assert dist == 10


# --- ease_toward ---------------------------------------------------------


def test_ease_toward_dt_zero_is_identity():
    out = ease_toward(Vec(100, 100), Vec(500, 500), C.PREDICTION_SMOOTH, 0.0)
    assert (out.x, out.y) == (100, 100)


def test_ease_toward_converges():
    cur = Vec(0, 0)
    goal = Vec(100, 0)
    for _ in range(120):
        cur = ease_toward(cur, goal, C.PREDICTION_SMOOTH, DT)
    assert abs(cur.x - 100) < 0.5
    assert abs(cur.y) < 1e-9


def test_ease_toward_partial_step():
    out = ease_toward(Vec(0, 0), Vec(100, 0), C.PREDICTION_SMOOTH, DT)
    assert 0 < out.x < 100


def test_ease_toward_frame_rate_independent():
    one = ease_toward(Vec(0, 0), Vec(100, 0), C.PREDICTION_SMOOTH, DT)
    half = ease_toward(Vec(0, 0), Vec(100, 0), C.PREDICTION_SMOOTH, DT / 2)
    two_halves = ease_toward(half, Vec(100, 0), C.PREDICTION_SMOOTH, DT / 2)
    assert abs(one.x - two_halves.x) < 1e-9


# --- ShipPredictor -------------------------------------------------------


def test_predictor_step_first_frame_adopts_target():
    w = _running_world(_ship(1, pos=(500, 500)))
    p = ShipPredictor()
    p.record_input(PredictedInput(0, PlayerCommand(), DT))
    p.step(w, 1, DT)
    assert p.has_render_state
    # No thrust/rotation and zero velocity -> target is the authority.
    assert (p.render_pos.x, p.render_pos.y) == (500, 500)


def test_predictor_step_without_ship_clears_state():
    w = _running_world()
    p = ShipPredictor()
    p.has_render_state = True
    p.step(w, 1, DT)
    assert not p.has_render_state


def test_predictor_step_not_running_clears_state():
    w = _running_world(_ship(1))
    w.match_state = "lobby"
    p = ShipPredictor()
    p.has_render_state = True
    p.step(w, 1, DT)
    assert not p.has_render_state


def test_predictor_rebase_clears_history():
    w = _running_world(_ship(1, pos=(500, 500)))
    p = ShipPredictor()
    p.record_input(PredictedInput(0, PlayerCommand(), DT))
    p.record_input(PredictedInput(1, PlayerCommand(), DT))
    p.rebase(w, 1)
    assert p.history == []


def test_predictor_rebase_snaps_on_large_error():
    w = _running_world(_ship(1, pos=(500, 500)))
    p = ShipPredictor()
    p.render_pos = Vec(2000, 2000)
    p.has_render_state = True
    p.rebase(w, 1)
    assert (p.render_pos.x, p.render_pos.y) == (500, 500)


def test_predictor_rebase_keeps_small_error_for_smoothing():
    w = _running_world(_ship(1, pos=(500, 500)))
    p = ShipPredictor()
    p.render_pos = Vec(510, 500)  # 10 px error < snap distance
    p.has_render_state = True
    p.rebase(w, 1)
    assert (p.render_pos.x, p.render_pos.y) == (510, 500)


def test_predictor_rebase_without_ship_resets():
    w = _running_world()
    p = ShipPredictor()
    p.has_render_state = True
    p.record_input(PredictedInput(0, PlayerCommand(), DT))
    p.rebase(w, 1)
    assert not p.has_render_state
    assert p.history == []


# --- reconciliation (ack-based pruning + replay) -------------------------


def test_predictor_rebase_prunes_acked_keeps_unacked():
    w = _running_world(_ship(1, pos=(500, 500)))
    p = ShipPredictor()
    for s in range(5):  # seqs 0..4
        p.record_input(PredictedInput(s, PlayerCommand(), DT))
    p.render_pos = Vec(500, 500)
    p.has_render_state = True
    p.rebase(w, 1, ack=2)
    # Inputs the server confirmed (seq <= 2) are dropped; 3, 4 replay.
    assert [e.seq for e in p.history] == [3, 4]


def test_predictor_rebase_ack_negative_keeps_all():
    w = _running_world(_ship(1, pos=(500, 500)))
    p = ShipPredictor()
    p.record_input(PredictedInput(0, PlayerCommand(), DT))
    p.record_input(PredictedInput(1, PlayerCommand(), DT))
    p.render_pos = Vec(500, 500)
    p.has_render_state = True
    p.rebase(w, 1, ack=-1)  # nothing acked yet
    assert [e.seq for e in p.history] == [0, 1]


def test_reconciliation_replays_unacked_thrust():
    # The reconciled prediction is authority replayed with the unacked
    # inputs, so kept thrust inputs move the target ahead of authority.
    w = _running_world(_ship(1, pos=(500, 500), angle=0.0))
    p = ShipPredictor()
    p.record_input(PredictedInput(0, PlayerCommand(thrust=True), DT))
    p.record_input(PredictedInput(1, PlayerCommand(thrust=True), DT))
    p.render_pos = Vec(500, 500)
    p.has_render_state = True
    p.rebase(w, 1, ack=-1)  # keep both
    target = simulate_from_authority(w.get_ship(1), p.history)
    assert (target.pos.x, target.pos.y) != (500, 500)


def test_predictor_rebase_ack_snaps_on_large_error():
    w = _running_world(_ship(1, pos=(500, 500)))
    p = ShipPredictor()
    p.record_input(PredictedInput(0, PlayerCommand(), DT))  # no movement
    p.render_pos = Vec(2000, 2000)
    p.has_render_state = True
    p.rebase(w, 1, ack=-1)  # target stays at authority -> snap
    assert (p.render_pos.x, p.render_pos.y) == (500, 500)
