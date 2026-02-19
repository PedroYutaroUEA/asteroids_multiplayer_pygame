"""Configurações do jogo (constantes)."""

import os

WIDTH = 960
HEIGHT = 720
FPS = 60

MAX_PLAYERS = 8
LOCAL_PLAYER_ID = 1

START_LIVES = 3
SAFE_SPAWN_TIME = 2.0
WAVE_DELAY = 2.0

SHIP_RADIUS = 15
SHIP_TURN_SPEED = 220.0
SHIP_THRUST = 220.0
SHIP_FRICTION = 0.995
SHIP_FIRE_RATE = 0.2
SHIP_BULLET_SPEED = 420.0
HYPERSPACE_COST = 250

AST_VEL_MIN = 30.0
AST_VEL_MAX = 90.0
AST_SIZES = {
    "L": {"r": 46, "score": 20, "split": ["M", "M"]},
    "M": {"r": 24, "score": 50, "split": ["S", "S"]},
    "S": {"r": 12, "score": 100, "split": []},
}

BULLET_RADIUS = 2
BULLET_TTL = 1.0
MAX_BULLETS_PER_PLAYER = 4

UFO_SPAWN_EVERY = 12.0
UFO_SPEED_BIG = 95.0
UFO_SPEED_SMALL = 120.0
UFO_BIG = {"r": 18, "score": 200}
UFO_SMALL = {"r": 12, "score": 1000}

UFO_FIRE_RATE_BIG = 0.8
UFO_FIRE_RATE_SMALL = 0.55
UFO_BULLET_SPEED = 360.0
UFO_BULLET_TTL = 1.3

# Mira: pequena mais precisa, grande mais "burra".
UFO_AIM_JITTER_DEG_BIG = 28.0
UFO_AIM_JITTER_DEG_SMALL = 6.0
UFO_BIG_MISS_CHANCE = 0.35

WHITE = (240, 240, 240)
BLACK = (0, 0, 0)

RANDOM_SEED = None

# Paths (funcionam de qualquer diretório de execução).
# `config.py` fica em `core/`, então subimos um nível para a raiz.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOUND_PATH = os.path.join(BASE_DIR, "assets", "sounds")

# Sounds
PLAYER_SHOOT = "player_shoot.wav"
UFO_SHOOT = "ufo_shoot.wav"
ASTEROID_EXPLOSION = "asteroid_explosion.wav"
SHIP_EXPLOSION = "ship_explosion.wav"
THRUST_LOOP = "thrust_loop.wav"
UFO_SIREN_BIG = "ufo_siren_big.wav"
UFO_SIREN_SMALL = "ufo_siren_small.wav"
