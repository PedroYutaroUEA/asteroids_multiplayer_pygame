"""Single-player Asteroids entry point."""

import argparse

from client.game import Game


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="asteroids",
        description="Asteroids single-player client.",
    )
    parser.add_argument(
        "--profile-frames",
        action="store_true",
        help="log frame-time percentiles (p50/p95/max) to stderr",
    )
    args = parser.parse_args()
    Game(profile_frames=args.profile_frames).run()


if __name__ == "__main__":
    main()
