# Asteroids Multiplayer

LAN deathmatch multiplayer for up to 8 players. Didactic client-server project in Python with `asyncio` and WebSockets. Fork of [asteroids_single-player](https://github.com/jucimarjr/asteroids_single-player) — the parent repository is frozen at `v0.1.0` and this fork starts from the same state.

A single-player mode runs from this repository too: every multiplayer-prep refactor leaves `python main.py` working as in the parent repo.

## Quick start

Requires Python 3.10 or newer (3.13 recommended via `.python-version`).

```
pip install -r requirements.txt
python main.py
```

### Run multiplayer deathmatch

```
# Terminal 0 — copy the example token file first
cp tokens.example.txt tokens.txt

# Terminal 1 — server with two rooms
python -m server --rooms 2 --port 8765

# Terminals 2-5 — players in two rooms
python -m multiplayer.player --host localhost --port 8765 --name Alice --room 0 --token dev-token-1
python -m multiplayer.player --host localhost --port 8765 --name Bob   --room 0 --token dev-token-2
python -m multiplayer.player --host localhost --port 8765 --name Carol --room 1 --token dev-token-3
python -m multiplayer.player --host localhost --port 8765 --name Dave  --room 1 --token dev-token-4

# Terminal 6 — spectator on room 0
python -m multiplayer.spectator --host localhost --port 8765 --room 0 --token dev-token-1 --width 1024 --height 768
```

The server prints one line per significant event to stdout, so the terminal doubles as a live transcript of the match:

```
asteroids server listening on ws://0.0.0.0:8765
ship spawned: Alice (pid=1, room=0)
ship spawned: Bob (pid=2, room=0)
match started: room=0
ship killed: Bob (pid=2, room=0)
match ended: room=0, winner=Alice
```

The server is authoritative and runs each room's `World` headlessly at 60 Hz; each client connects, receives snapshots at 30 Hz, sends input every frame (players only), and renders through the same client renderer used by single-player. The networked player client adds a local HUD with score, deaths and room id plus a scoreboard listing every connected player in the same room, with a `RESPAWN X.Xs` countdown shown next to anyone waiting to respawn. Audio starts **muted** on the networked client; press `R Shift` in any player window to toggle SFX on or off.

A match begins as soon as two players are connected to a room (`MIN_PLAYERS_TO_START`); it ends on the first to 5 frags or after 2 minutes of clock (`FRAG_LIMIT`, `MATCH_DURATION` in `core/config.py`). Any connected player presses `ENTER` on the match-end screen to reset that room's world and start the next match. Rooms are independent — matches in room 0 do not affect room 1.

The spectator client is read-only: it never spawns a ship, never sends input, and fits the entire 3840×2160 world into the configured `--width`/`--height` window via the `SpectatorCamera` (letterbox padding when the aspect ratio differs from the world's 16:9). Set `--rooms N` on the server to host N concurrent rooms; the default is 1, which matches the F4 single-room behavior.

**Hosting on a VPS?** To run the server as a managed `systemd` service on a Linux host — background, auto-restart, journald logs — see [`docs/DEPLOY.md`](docs/DEPLOY.md).

## Controls

| Key       | Action |
| --------- | ------ |
| `←` `→`   | Rotate |
| `↑`       | Thrust |
| `↓`       | Shield (3 s active, 10 s cooldown) |
| `Space`   | Shoot  |
| `L Shift` | Hyperspace (costs 250 points) |
| `R Shift` | Toggle audio (networked client only; muted at start) |
| `Enter`   | Restart match after `MATCH OVER` (networked client only) |
| `Esc` `Q` | Quit |

## How it works

Four top-level packages, each with a single concern:

- [`core/`](core/) holds game state, entities, collisions, and the per-frame update. Plain Python, no pygame. Emits string events (`"player_shoot"`, `"asteroid_explosion"`) that consumers react to.
- [`client/`](client/) wires pygame to the simulation. Maps input, runs the 60 FPS loop, renders polygons, plays audio from `world.events`.
- [`server/`](server/) hosts the authoritative `World`. Runs the simulation at 60 Hz and broadcasts a snapshot to every connected client at 30 Hz over a single WebSocket per client.
- [`multiplayer/`](multiplayer/) is the networked player. Connects to a server, applies snapshots to a local read-only `World`, sends input every frame, renders through the existing `client/` renderer.

The single-player path (`python main.py`) uses `core/` + `client/` directly and is preserved across every phase. The multiplayer path (server + multiplayer client) layers `server/` + `multiplayer/` on top without touching the others.

Key files:

- [`core/world.py`](core/world.py): simulation tick, wave spawning, score, lives, deathmatch flag, respawn loop, match lifecycle.
- [`core/entities.py`](core/entities.py): `Ship`, `Asteroid`, `Bullet`, `UFO`, `Particle`.
- [`core/collisions.py`](core/collisions.py): `CollisionManager` resolves every collision in a single pass and returns a `CollisionResult`.
- [`client/game.py`](client/game.py): game loop and scene transitions (menu, play, game over).
- [`client/spectator_camera.py`](client/spectator_camera.py): scaled fit-the-world-into-the-window camera used by the spectator client.
- [`multiplayer/hud.py`](multiplayer/hud.py): networked-client HUD and scoreboard.
- [`multiplayer/spectator.py`](multiplayer/spectator.py): read-only spectator client.
- [`server/auth.py`](server/auth.py): token allowlist loader.

## Architecture Overview

The project follows a client-server architecture where the server is authoritative over the game state and clients are responsible for input collection and rendering. The architecture is organized into independent modules with clear responsibilities, allowing the single-player and multiplayer modes to share the same simulation core.

### C4 — System Context

This diagram shows the system's external actors and its relationship with players and spectators.

![Asteroids Multiplayer Context Diagram](docs/asteroidsContextDiagram-dark.png)

### C4 — Container Diagram

This diagram presents the main containers that compose the application and how they communicate with each other.  

- **Server** hosts the authoritative game world.
- **Multiplayer Client** sends player inputs and receives snapshots.
- **Spectator Client** receives snapshots in read-only mode.
- **Core** contains the game simulation shared by all execution modes.

![Asteroids Multiplayer Container Diagram](docs/asteroidsContainerDiagram-dark.png)

### C4 — Component Diagram

This diagram details the internal organization of the main modules and their responsibilities.

- `core/` manages entities, collisions, rules, and world updates.
- `server/` handles room management, networking, and snapshot generation.
- `multiplayer/` applies snapshots, prediction, reconciliation, and HUD rendering.
- `client/` provides rendering, input handling, camera management, and audio.

![Asteroids Multiplayer Component Diagram](docs/ComponentDiagram-dark.png)

## Roadmap

| Phase | Content | Status |
|---|---|---|
| F1 — Foundation | Decouple `core/` from pygame, viewport vs world split, camera, testing infra | done |
| F2 — Server lonely | WebSocket asyncio server, single player connects and sees own state | done |
| F3 — Multi-player 1 room | N players in deathmatch, respawn, frag/score, scoreboard HUD | done |
| F4 — Match lifecycle | Timer / frag limit / match end, ENTER-to-restart, lobby gate | done |
| F5 — Multi-room | Token allowlist, N concurrent rooms, dedicated spectator client | done |
| F6 — Netcode | Client-side prediction, server reconciliation (input ack), remote-ship interpolation | done |
| F7 — Performance | Client frame-time profiling (`--profile-frames`); a measured baseline found no hotspot worth optimizing | done |

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
    └── DEVELOPMENT_WORKFLOW.md
```

## Contributing

Read [`docs/DEVELOPMENT_WORKFLOW.md`](docs/DEVELOPMENT_WORKFLOW.md) before opening a PR. It defines branch prefixes, commit conventions in en-US, and the review checklist. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) walks through module dependencies.
