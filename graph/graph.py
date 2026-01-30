from functools import partial
from dataclasses import dataclass
from typing import Callable, Any
from argparse import Namespace
import random
import logging



@dataclass
class MoveToNode:
    fn : Callable

    @classmethod
    def with_parameters(cls, fn, *args, **kwargs):
        return cls(partial(fn, *args, **kwargs))


@dataclass
class NodeError:
    error : str


@dataclass
class FinalResult:
    result : Any


class NodeErrored(Exception):
    """A NodeError was returned to the control loop."""
    pass


class NodeFailed(Exception):
    """A node raised an exception"""
    pass


def run_graph(start_node: Callable, *args, deps, **kwargs) -> Any:
    try:
        logging.info("Starting graph execution.")
        node_result = start_node(*args, **kwargs, deps=deps)
        logging.info(f"Initial node executed. Result: {node_result}")
    except Exception as e:
        raise NodeFailed("Initial node failed") from e
    else:
        while node_result:
            match node_result:
                case MoveToNode(fn=fn):
                    logging.info(f"Moving to next node: {fn}")
                    try:
                        node_result = fn(deps=deps)
                        logging.info(f"Node executed. Result: {node_result}")
                    except Exception as e:
                        raise NodeFailed("Node execution failed") from e
                case FinalResult(result=res):
                    logging.info("Final result reached.")
                    return res
                case NodeError(error=err):
                    logging.error(f"Node returned an error: {err}")
                    raise NodeErrored(err)

# Example graph

def start_node(deps):
    secret_number = deps.randomint(1, 10)
    tries = 3
    initial_guess = deps.input("Guess a number between 1 and 10: ")

    return MoveToNode.with_parameters(guess_node, (secret_number, tries, initial_guess))

def guess_node(data, *, deps):
    secret_number, tries, guess = data

    try:
        guess = int(guess)
    except ValueError:
        return NodeError(error="Invalid input. Please enter a number.")

    if guess == secret_number:
        return FinalResult(result="Congratulations! You've guessed the number.")
    else:
        tries -= 1
        if tries <= 0:
            return FinalResult(result=f"Game over! The secret number was {secret_number}.")
        else:
            next_guess = deps.input(f"Wrong guess. You have {tries} tries left. Try again: ")
            return MoveToNode.with_parameters(guess_node, (secret_number, tries, next_guess))


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    deps = Namespace(
        randomint=random.randint,
        input=input
    )

    try:
        result = run_graph(start_node, deps=deps)
    except NodeErrored as e:
        logging.error(f"Graph execution stopped due to an error: {e}")
    except NodeFailed as e:
        logging.critical(f"Graph execution failed due to an exception: {e}")
    else:
        print(result)
