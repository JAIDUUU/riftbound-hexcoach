"""Command line entrypoint for the HexCoach backend."""

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="backend",
        description="HexCoach backend: Riftbound rules coach.",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    print("HexCoach backend")
    return 0
