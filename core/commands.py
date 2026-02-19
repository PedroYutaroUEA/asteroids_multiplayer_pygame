"""Comandos de jogador (input agnóstico)."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlayerCommand:
    """Comando aplicado a uma nave em um frame."""

    rotate_left: bool = False
    rotate_right: bool = False
    thrust: bool = False
    shoot: bool = False
    hyperspace: bool = False
