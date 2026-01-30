import asyncio
from functools import partial
from dataclasses import dataclass
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


async def run_graph(start_node: Callable, *args, deps, **kwargs) -> Any:
    try:
        logging.info(f"--- Starting new graph execution context [{start_node.__name__}] ---")
        node_result = await start_node(*args, **kwargs, deps=deps)
        logging.info(f"Initial node executed. Result: {node_result}")
    except Exception as e:
        raise NodeFailed("Initial node failed") from e
    else:
        while node_result:
            match node_result:
                case MoveToNode(fn=fn):
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
