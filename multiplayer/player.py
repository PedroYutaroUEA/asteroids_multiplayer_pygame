"""Networked Asteroids player client.

Connects to a server, handshakes for a `player_id`, then runs a single
asyncio loop that:

1. drains pending snapshots and applies them to a local shadow World;
2. polls pygame input and sends an INPUT message every frame;
3. predicts the local ship from that input so it responds instantly,
   extrapolates the remote ships, and renders through client/renderer.

Authoritative state still comes from server snapshots; prediction runs
the real ship physics ahead of them and eases back on each correction,
hiding the round-trip latency the player would otherwise feel.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from typing import Any

import pygame as pg
import websockets

from client.audio import load_sounds
from client.audio_manager import AudioManager
from client.camera import Camera
from client.controls import InputMapper
from client.renderer import Renderer
from core import config as C
from core.utils import Vec
from core.world import World
from multiplayer.command_codec import command_to_dict
from multiplayer.hud import (
    draw_local_hud,
    draw_match_end_screen,
    draw_match_overlay,
    draw_scoreboard,
    draw_waiting_screen,
)
from multiplayer.prediction import PredictedInput, ShipPredictor
from multiplayer.snapshot import snapshot_to_world
from server.protocol import (
    HELLO,
    INPUT,
    REJECT,
    RESTART_REQUEST,
    SNAPSHOT,
    WELCOME,
    envelope,
    parse,
)

HANDSHAKE_TIMEOUT = 5.0


class Player:
    def __init__(
        self,
        host: str,
        port: int,
        name: str,
        room: int,
        token: str,
    ) -> None:
        self.host = host
        self.port = port
        self.name = name
        self.room = room
        self.token = token
        self.player_id: int | None = None
        self.server_tick = 0
        self.seq = 0
        self.running = True

        self.world = World(spawn_default_player=False)
        self.predictor = ShipPredictor()

        pg.mixer.pre_init(
            C.AUDIO_FREQUENCY,
            C.AUDIO_SIZE,
            C.AUDIO_CHANNELS,
            C.AUDIO_BUFFER,
        )
        pg.init()
        pg.mixer.init()
        self.screen = pg.display.set_mode((C.WINDOW_WIDTH, C.WINDOW_HEIGHT))
        pg.display.set_caption(f"Asteroids — {name}")
        self.font = pg.font.SysFont(C.FONT_NAME, C.FONT_SIZE_SMALL)
        self.big = pg.font.SysFont(C.FONT_NAME, C.FONT_SIZE_LARGE)
        self.camera = Camera()
        self.renderer = Renderer(
            self.screen,
            self.camera,
            config=C,
            fonts={"font": self.font, "big": self.big},
        )
        self.input_mapper = InputMapper()
        self.audio = AudioManager(load_sounds(C.SOUND_PATH))
        # Audio starts muted; players toggle it with Right Shift.
        self.audio.set_muted(True)

    async def run(self) -> None:
        uri = f"ws://{self.host}:{self.port}"
        try:
            async with websockets.connect(uri) as ws:
                if not await self._handshake(ws):
                    return
                recv_task = asyncio.create_task(self._receive_loop(ws))
                try:
                    await self._game_loop(ws)
                finally:
                    recv_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await recv_task
        finally:
            pg.quit()

    async def _handshake(self, ws: Any) -> bool:
        hello_data = {
            "name": self.name,
            "room_id": self.room,
            "token": self.token,
        }
        await ws.send(envelope(HELLO, 0, 0, hello_data))
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=HANDSHAKE_TIMEOUT)
        except TimeoutError:
            print("handshake timed out", file=sys.stderr)
            return False

        msg = parse(raw)
        if msg is None:
            print("invalid handshake reply", file=sys.stderr)
            return False
        if msg["type"] == REJECT:
            print(
                f"server rejected connection: {msg['data'].get('reason')}",
                file=sys.stderr,
            )
            return False
        if msg["type"] != WELCOME:
            print(f"unexpected first message: {msg['type']}", file=sys.stderr)
            return False

        self.player_id = int(msg["data"]["player_id"])
        print(f"connected as player {self.player_id}")
        return True

    async def _receive_loop(self, ws: Any) -> None:
        try:
            async for raw in ws:
                msg = parse(raw)
                if msg is None:
                    continue
                if msg["type"] == SNAPSHOT:
                    snapshot_to_world(msg["data"], self.world)
                    self.server_tick = msg["tick"]
                    self.predictor.rebase(
                        self.world,
                        self.player_id,
                        ack=msg["data"].get("ack"),
                    )
        except websockets.ConnectionClosed:
            pass
        finally:
            self.running = False

    async def _game_loop(self, ws: Any) -> None:
        period = 1.0 / C.FPS
        loop = asyncio.get_running_loop()
        last_frame = loop.time()
        while self.running:
            frame_start = loop.time()
            dt = min(frame_start - last_frame, 0.1)
            last_frame = frame_start

            for event in pg.event.get():
                if event.type == pg.QUIT or (
                    event.type == pg.KEYDOWN
                    and event.key in (pg.K_ESCAPE, pg.K_q)
                ):
                    self.running = False
                elif event.type == pg.KEYDOWN and event.key == pg.K_RSHIFT:
                    self.audio.set_muted(not self.audio.muted)
                elif (
                    event.type == pg.KEYDOWN
                    and event.key == pg.K_RETURN
                    and self.world.match_state == "ended"
                ):
                    await ws.send(
                        envelope(
                            RESTART_REQUEST, self.server_tick, self.seq, {}
                        )
                    )
                    self.seq += 1
                else:
                    self.input_mapper.handle_event(event)

            keys = pg.key.get_pressed()
            cmd = self.input_mapper.build_command(keys)

            try:
                await ws.send(
                    envelope(
                        INPUT, self.server_tick, self.seq, command_to_dict(cmd)
                    )
                )
            except websockets.ConnectionClosed:
                self.running = False
                break

            self.predictor.record_input(PredictedInput(self.seq, cmd, dt))
            self.seq += 1

            self.world.update_local_visual(dt, local_player_id=self.player_id)
            self.predictor.step(self.world, self.player_id, dt)
            self.audio.update_thrust(cmd.thrust)
            self.audio.update_ufo_siren(list(self.world.ufos))
            self.audio.play_events(self.world.events)
            self.world.events.clear()

            self._draw()

            elapsed = loop.time() - frame_start
            await asyncio.sleep(max(0.0, period - elapsed))

    def _draw(self) -> None:
        state = self.world.match_state
        self.renderer.clear()

        if state == "running":
            ship = (
                self.world.get_ship(self.player_id)
                if self.player_id is not None
                else None
            )
            predicting = ship is not None and self.predictor.has_render_state
            if predicting:
                saved_pos = Vec(ship.pos)
                saved_angle = ship.angle
                ship.pos.xy = self.predictor.render_pos.xy
                ship.angle = self.predictor.render_angle

            if ship is not None:
                self.camera.update(ship.pos)
            else:
                self.camera.update(Vec(C.WORLD_WIDTH / 2, C.WORLD_HEIGHT / 2))
            self.renderer.draw_world(self.world)

            if predicting:
                ship.pos.xy = saved_pos.xy
                ship.angle = saved_angle
            draw_local_hud(
                self.screen,
                self.font,
                self.world,
                self.player_id,
                C.WHITE,
                room_id=self.room,
            )
            draw_scoreboard(
                self.screen, self.font, self.world, self.player_id, C.WHITE
            )
            draw_match_overlay(
                self.screen, self.font, self.world, self.player_id, C.WHITE
            )
        elif state == "lobby":
            self.camera.update(Vec(C.WORLD_WIDTH / 2, C.WORLD_HEIGHT / 2))
            self.renderer.draw_world(self.world)
            draw_waiting_screen(
                self.screen, self.font, self.big, self.world, C.WHITE
            )
        else:  # "ended"
            self.camera.update(Vec(C.WORLD_WIDTH / 2, C.WORLD_HEIGHT / 2))
            self.renderer.draw_world(self.world)
            draw_scoreboard(
                self.screen, self.font, self.world, self.player_id, C.WHITE
            )
            draw_match_end_screen(
                self.screen, self.font, self.big, self.world, C.WHITE
            )

        pg.display.flip()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="multiplayer.player",
        description="Asteroids networked player client.",
    )
    parser.add_argument(
        "--host", default="localhost", help="server host (default: localhost)"
    )
    parser.add_argument(
        "--port", default=8765, type=int, help="server port (default: 8765)"
    )
    parser.add_argument(
        "--name", default="player", help="display name (default: player)"
    )
    parser.add_argument(
        "--room",
        default=0,
        type=int,
        help="room id to join (default: 0)",
    )
    parser.add_argument(
        "--token",
        required=True,
        help="allowlist token issued by the server operator",
    )
    args = parser.parse_args()

    player = Player(args.host, args.port, args.name, args.room, args.token)
    try:
        asyncio.run(player.run())
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
