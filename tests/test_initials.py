import unittest
from initials import initials


class TestInitials(unittest.TestCase):
    def test_two_words(self):
        self.assertEqual(initials("Kyo Gitmy"), "KG")

    def test_lowercase_to_uppercase(self):
        self.assertEqual(initials("kyo gitmy"), "KG")

    def test_one_word(self):
        self.assertEqual(initials("Kyo"), "K")

    def test_extra_whitespace(self):
        self.assertEqual(initials("  Kyo   Gitmy  Ami "), "KGA")

    def test_tabs_and_newlines(self):
        self.assertEqual(initials("Kyo\tGitmy\nAmi"), "KGA")

    def test_hyphen_stays_one_word(self):
        self.assertEqual(initials("Jean-Luc Picard"), "JP")

    def test_empty_string(self):
        self.assertEqual(initials(""), "")

    def test_whitespace_only(self):
        self.assertEqual(initials("   "), "")

    def test_bytes_raises_typeerror(self):
        with self.assertRaises(TypeError):
            initials(b"Kyo")

    def test_none_raises_typeerror(self):
        with self.assertRaises(TypeError):
            initials(None)

    def test_list_raises_typeerror(self):
        with self.assertRaises(TypeError):
            initials(["Kyo"])

    def test_does_not_mutate_input_list(self):
        name = ["Kyo"]
        snapshot = ["Kyo"]
        with self.assertRaises(TypeError):
            initials(name)
        self.assertEqual(name, snapshot)


if __name__ == "__main__":
    unittest.main()
