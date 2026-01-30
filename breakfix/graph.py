import asyncio
import pickle
from functools import partial
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any
import logging


@dataclass
class MoveToNode:
    fn: Callable

    @classmethod
    def with_parameters(cls, fn, *args, **kwargs):
        return cls(partial(fn, *args, **kwargs))


@dataclass
class NodeError:
    error: str


@dataclass
class FinalResult:
    result: Any


class NodeErrored(Exception):
    pass


class NodeFailed(Exception):
    pass


def _load_checkpoints(checkpoint_dir: Path) -> tuple[list[tuple[int, Any]], int]:
    """Load existing checkpoints and return (checkpoints, next_number)."""
    checkpoint_files = list(checkpoint_dir.glob("*.pickle"))
    if not checkpoint_files:
        return [], 1

    checkpoints = []
    for f in checkpoint_files:
        try:
            num = int(f.stem)
            with open(f, "rb") as fp:
                obj = pickle.load(fp)
            checkpoints.append((num, obj))
        except (ValueError, pickle.PickleError):
            continue

    checkpoints.sort(key=lambda x: x[0])
    next_num = max(c[0] for c in checkpoints) + 1 if checkpoints else 1
    return checkpoints, next_num


def _save_checkpoint(checkpoint_dir: Path, num: int, obj: Any) -> None:
    """Save a checkpoint to disk."""
    checkpoint_path = checkpoint_dir / f"{num}.pickle"
    with open(checkpoint_path, "wb") as fp:
        pickle.dump(obj, fp)


async def run_graph(
    start_node: Callable,
    *args,
    deps,
    checkpoint_dir: str | Path | None = None,
    **kwargs
) -> Any:
    checkpoint_path = Path(checkpoint_dir) if checkpoint_dir else None
    next_checkpoint_num = 1

    # Try to resume from checkpoints
    if checkpoint_path and checkpoint_path.exists():
        checkpoints, next_checkpoint_num = _load_checkpoints(checkpoint_path)

        if checkpoints:
            # Log skipped checkpoints (all but last)
            for num, obj in checkpoints[:-1]:
                logging.info(f"Skipping checkpoint {num}: {repr(obj)}")

            # Resume from last checkpoint
            last_num, last_obj = checkpoints[-1]
            logging.info(f"Resuming from checkpoint {last_num}: {repr(last_obj)}")
            node_result = last_obj
        else:
            # No valid checkpoints, start fresh
            try:
                logging.info(f"--- Starting new graph execution context [{start_node.__name__}] ---")
                node_result = await start_node(*args, **kwargs, deps=deps)
                logging.info(f"Initial node executed. Result: {node_result}")
            except Exception as e:
                raise NodeFailed("Initial node failed") from e
    else:
        # No checkpoint directory or doesn't exist, start fresh
        try:
            logging.info(f"--- Starting new graph execution context [{start_node.__name__}] ---")
            node_result = await start_node(*args, **kwargs, deps=deps)
            logging.info(f"Initial node executed. Result: {node_result}")
        except Exception as e:
            raise NodeFailed("Initial node failed") from e

    while node_result:
        match node_result:
            case MoveToNode(fn=fn):
                # Save checkpoint before moving to next node
                if checkpoint_path:
                    _save_checkpoint(checkpoint_path, next_checkpoint_num, node_result)
                    next_checkpoint_num += 1

                logging.info(f"Moving to next node: {fn}")
                try:
                    node_result = await fn(deps=deps)
                except Exception as e:
                    raise NodeFailed("Node execution failed") from e
            case FinalResult(result=res):
                logging.info("Final result reached for current graph context.")
                return res
            case NodeError(error=err):
                logging.error(f"Node returned an error: {err}")
                raise NodeErrored(err)
