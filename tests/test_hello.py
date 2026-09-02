import unittest
from hello import greet


class TestHello(unittest.TestCase):
    def test_greet(self):
        result = greet()
        self.assertIn("Hello, Gitmy!", result)


if __name__ == "__main__":
    unittest.main()
