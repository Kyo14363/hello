import unittest
from hello import farewell, greet


class TestHello(unittest.TestCase):
    def test_greet(self):
        result = greet()
        self.assertIn("Hello, Gitmy!", result)

    def test_farewell_normal_name(self):
        result = farewell("Gitmy")
        self.assertIn("Goodbye, Gitmy!", result)


if __name__ == "__main__":
    unittest.main()
