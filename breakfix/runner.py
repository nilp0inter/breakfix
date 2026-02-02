"""Entry point for running the BreakFix pipeline with Prefect."""

import asyncio
import logging

from breakfix.flows import breakfix_project_flow
from breakfix.blocks import BreakFixConfig, get_config


async def run(working_directory: str, config: BreakFixConfig | None = None):
    """Run the BreakFix pipeline.

    Args:
        working_directory: The directory to create the project in.
        config: Optional BreakFixConfig. If not provided, uses defaults.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    config = config or await get_config()

    try:
        result = await breakfix_project_flow(
            working_directory=working_directory,
            config=config,
        )
        print(f"\nFinal Result: {result}")

    except Exception as e:
        print(f"Pipeline failed: {e}")
        raise


def run_sync(working_directory: str, config: BreakFixConfig | None = None):
    """Synchronous wrapper for run().

    This is useful for calling from non-async contexts.
    """
    asyncio.run(run(working_directory, config))
