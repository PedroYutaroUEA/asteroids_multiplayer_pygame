# Asteroids Multiplayer

LAN deathmatch multiplayer for up to 8 players. Didactic client-server project in Python with `asyncio` and WebSockets. Fork of [asteroids_single-player](https://github.com/jucimarjr/asteroids_single-player) — the parent repository is frozen at `v0.1.0` and this fork starts from the same state.

A single-player mode runs from this repository too: every multiplayer-prep refactor leaves `python main.py` working as in the parent repo.

## Quick start

Requires Python 3.10 or newer (3.13 recommended via `.python-version`).

```
pip install -r requirements.txt
python main.py
```

### Run multiplayer (one player)

```
# Terminal 1
python -m server --port 8765

# Terminal 2
python -m multiplayer.player --host localhost --port 8765 --name P1
```

The server is authoritative and runs the `World` headlessly at 60 Hz; the player client connects, receives snapshots at 30 Hz, sends input every frame, and renders through the same client renderer used by single-player.

## Controls

| Key       | Action |
| --------- | ------ |
| `←` `→`   | Rotate |
| `↑`       | Thrust |
| `↓`       | Shield (3 s active, 10 s cooldown) |
| `Space`   | Shoot  |
| `L Shift` | Hyperspace (costs 250 points) |
| `Esc`     | Quit |

## How it works

Four top-level packages, each with a single concern:

- [`core/`](core/) holds game state, entities, collisions, and the per-frame update. Plain Python, no pygame. Emits string events (`"player_shoot"`, `"asteroid_explosion"`) that consumers react to.
- [`client/`](client/) wires pygame to the simulation. Maps input, runs the 60 FPS loop, renders polygons, plays audio from `world.events`.
- [`server/`](server/) hosts the authoritative `World`. Runs the simulation at 60 Hz and broadcasts a snapshot to every connected client at 30 Hz over a single WebSocket per client.
- [`multiplayer/`](multiplayer/) is the networked player. Connects to a server, applies snapshots to a local read-only `World`, sends input every frame, renders through the existing `client/` renderer.

The single-player path (`python main.py`) uses `core/` + `client/` directly and is preserved across every phase. The multiplayer path (server + multiplayer client) layers `server/` + `multiplayer/` on top without touching the others.

See [`docs/teaching/`](docs/teaching/) for the lecture material that walks through each phase.

Key files:

- [`core/world.py`](core/world.py): simulation tick, wave spawning, score and lives.
- [`core/entities.py`](core/entities.py): `Ship`, `Asteroid`, `Bullet`, `UFO`, `Particle`.
- [`core/collisions.py`](core/collisions.py): `CollisionManager` resolves every collision in a single pass and returns a `CollisionResult`.
- [`client/game.py`](client/game.py): game loop and scene transitions (menu, play, game over).

## Roadmap

| Phase | Content | Status |
|---|---|---|
| F1 — Foundation | Decouple `core/` from pygame, viewport vs world split, camera, testing infra | done |
| F2 — Server lonely | WebSocket asyncio server, single player connects and sees own state | done |
| F3 — Multi-player 1 room | N players in deathmatch, respawn, frag/score | planned |
| F4 — Match lifecycle | Timer / frag limit / match end, spectator client | planned |
| F5 — Multi-room | Token-based rooms, parallel matches, per-room logs | planned |

## Project layout

```
asteroids_multiplayer/
├── main.py                   # single-player entrypoint (preserved)
├── pyproject.toml
├── core/                     # game state, rules, entities, collisions
├── client/                   # pygame loop, renderer, input, audio
├── server/                   # authoritative World + WebSocket broadcast
├── multiplayer/              # networked player client
├── assets/                   # WAV sound effects
├── tests/                    # pytest suite (snapshot, protocol, vec, ...)
└── docs/
    ├── ARCHITECTURE.md
    ├── DEVELOPMENT_WORKFLOW.md
    └── teaching/             # PT-BR lecture material per phase
```

## Contributing

Read [`docs/DEVELOPMENT_WORKFLOW.md`](docs/DEVELOPMENT_WORKFLOW.md) before opening a PR. It defines branch prefixes, commit conventions in en-US, and the review checklist. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) walks through module dependencies.
