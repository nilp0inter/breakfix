import unittest
from argparse import Namespace
from graph import run_graph, start_node, NodeErrored, NodeFailed

class TestGraph(unittest.TestCase):
    def setUp(self):
        # Mock randomint to always return 3 for consistent testing
        self.fixed_random = lambda *_: 3

    def create_input_mock(self, *inputs):
        """Creates a mock input function that yields values from the provided arguments."""
        iterator = iter(inputs)
        def mock_input(prompt):
            try:
                return next(iterator)
            except StopIteration:
                raise RuntimeError("Not enough inputs provided for test case")
        return mock_input

    def test_guess_correctly_first_try(self):
        """Test guessing the correct number on the first attempt."""
        deps = Namespace(input=self.create_input_mock("3"), randomint=self.fixed_random)
        result = run_graph(start_node, deps=deps)
        self.assertEqual(result, "Congratulations! You've guessed the number.")

    def test_guess_correctly_second_try(self):
        """Test guessing the correct number on the second attempt."""
        # First guess "1" (wrong), second guess "3" (correct)
        deps = Namespace(input=self.create_input_mock("1", "3"), randomint=self.fixed_random)
        result = run_graph(start_node, deps=deps)
        self.assertEqual(result, "Congratulations! You've guessed the number.")

    def test_game_over(self):
        """Test running out of tries."""
        # 3 wrong guesses: "1", "2", "4". Secret is 3.
        deps = Namespace(input=self.create_input_mock("1", "2", "4"), randomint=self.fixed_random)
        result = run_graph(start_node, deps=deps)
        self.assertEqual(result, "Game over! The secret number was 3.")

    def test_invalid_input(self):
        """Test that invalid input raises NodeErrored."""
        deps = Namespace(input=self.create_input_mock("not a number"), randomint=self.fixed_random)
        with self.assertRaises(NodeErrored) as cm:
            run_graph(start_node, deps=deps)
        self.assertIn("Invalid input", str(cm.exception))

if __name__ == "__main__":
    unittest.main()
