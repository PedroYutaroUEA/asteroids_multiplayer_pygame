"""Utilitários comuns do jogo."""

import math
from random import random, uniform
from typing import Iterable

import pygame as pg

from core import config as C

Vec = pg.math.Vector2


def wrap_pos(pos: Vec) -> Vec:
    return Vec(pos.x % C.WIDTH, pos.y % C.HEIGHT)


def angle_to_vec(deg: float) -> Vec:
    rad = math.radians(deg)
    return Vec(math.cos(rad), math.sin(rad))


def rand_unit_vec() -> Vec:
    ang = uniform(0, math.tau)
    return Vec(math.cos(ang), math.sin(ang))


def rand_edge_pos() -> Vec:
    if random() < 0.5:
        x = uniform(0, C.WIDTH)
        y = 0 if random() < 0.5 else C.HEIGHT
    else:
        x = 0 if random() < 0.5 else C.WIDTH
        y = uniform(0, C.HEIGHT)
    return Vec(x, y)


def draw_poly(surface: pg.Surface, pts: Iterable[Vec]) -> None:
    points = [(int(p.x), int(p.y)) for p in pts]
    pg.draw.polygon(surface, C.WHITE, points, width=1)


def draw_circle(surface: pg.Surface, pos: Vec, r: int) -> None:
    pg.draw.circle(surface, C.WHITE, (int(pos.x), int(pos.y)), r, width=1)


def draw_text(
    surface: pg.Surface,
    font: pg.font.Font,
    text: str,
    x: int,
    y: int,
) -> None:
    label = font.render(text, True, C.WHITE)
    surface.blit(label, (x, y))
