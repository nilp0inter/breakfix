import argparse
import asyncio

from breakfix.runner import run


def main():
    parser = argparse.ArgumentParser(
        description="Agentic TDD Foundry: Transform ideas into production-grade software"
    )
    parser.add_argument(
        "working_dir",
        help="Working directory for the project"
    )
    args = parser.parse_args()
    asyncio.run(run(working_directory=args.working_dir))
