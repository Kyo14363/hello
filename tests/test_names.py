import unittest
from names import join_names


class TestJoinNames(unittest.TestCase):
    def test_zero_names(self):
        self.assertEqual(join_names([]), "")

    def test_one_name(self):
        self.assertEqual(join_names(["Kyo"]), "Kyo")

    def test_two_names(self):
        self.assertEqual(join_names(["Kyo", "Gitmy"]), "Kyo and Gitmy")

    def test_two_names_tuple(self):
        self.assertEqual(join_names(("Kyo", "Gitmy")), "Kyo and Gitmy")

    def test_three_or_more_names(self):
        self.assertEqual(join_names(["Kyo", "Gitmy", "Ami"]), "Kyo, Gitmy and Ami")
        self.assertEqual(join_names(["A", "B", "C", "D"]), "A, B, C and D")

    def test_strip_and_drop_empty(self):
        self.assertEqual(join_names(["  Kyo ", "", "   ", "Gitmy"]), "Kyo and Gitmy")
        self.assertEqual(join_names(["", " "]), "")

    def test_duplicate_names_kept(self):
        self.assertEqual(join_names(["Kyo", "Kyo"]), "Kyo and Kyo")

    def test_str_raises_typeerror(self):
        with self.assertRaises(TypeError):
            join_names("Kyo")

    def test_bytes_raises_typeerror(self):
        with self.assertRaises(TypeError):
            join_names(b"Kyo")

    def test_non_str_element_raises_typeerror(self):
        with self.assertRaises(TypeError):
            join_names(["Kyo", 3])
        with self.assertRaises(TypeError):
            join_names(["Kyo", None])

    def test_does_not_mutate_input_list(self):
        names = ["  Kyo ", "", "   ", "Gitmy"]
        snapshot = ["  Kyo ", "", "   ", "Gitmy"]
        self.assertEqual(join_names(names), "Kyo and Gitmy")
        self.assertEqual(names, snapshot)


if __name__ == "__main__":
    unittest.main()
