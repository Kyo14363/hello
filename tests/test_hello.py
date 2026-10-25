import contextlib
import io
import unittest
from hello import farewell, greet, greet_name, main


class TestHello(unittest.TestCase):
    def test_greet(self):
        result = greet()
        self.assertIn("Hello, Gitmy!", result)

    def test_farewell_normal_name(self):
        result = farewell("Gitmy")
        self.assertIn("Goodbye, Gitmy!", result)

    def test_greet_name(self):
        self.assertIn("Hello, Kyo!", greet_name("Kyo"))

    def test_main(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["Kyo"])
        self.assertIn("Hello, Kyo!", buf.getvalue())

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main([""])
        self.assertIn("Hello, Gitmy!", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
