"""Offline tests for the daily file presence check."""

import datetime
import hashlib
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import daily_file_presence


REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "routines" / "daily_file_presence.py"
STAMP = 1768900000
MTIME = "2026-01-20T18:06:40+09:00"
DATE = "2026-01-20"
PAT_A = "a/report-{YYYY-MM-DD}.json"
PAT_B = "b/report_{YYYYMMDD}.md"
REL_A = "a/report-2026-01-20.json"
REL_B = "b/report_20260120.md"
YREL_A = "a/report-2026-01-19.json"
YREL_B = "b/report_20260119.md"
MTIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+09:00$")
B_KEYS = {"date", "files", "status", "first_present", "missing", "error"}
FILE_KEYS = {"order", "path", "exists", "mtime"}
JST = datetime.timezone(datetime.timedelta(hours=9))


def invoke(argv):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
        code = daily_file_presence.main(list(argv))
    return code, stdout.getvalue(), stderr.getvalue()


class DailyFilePresenceTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _plant(self, rel, stamp=STAMP, body=b"x\n"):
        path = self.root.joinpath(*rel.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        os.utime(path, (stamp, stamp))
        return path

    def _argv(self, patterns, date=DATE):
        argv = ["--root", str(self.root)]
        if date is not None:
            argv.extend(["--date", date])
        for pattern in patterns:
            argv.extend(["--pattern", pattern])
        return argv

    def _run(self, patterns, date=DATE):
        code, out, err = invoke(self._argv(patterns, date=date))
        self.assertNotIn(str(self.root), out)
        return code, out, err

    def _doc(self, out):
        self.assertTrue(out.endswith("\n"))
        self.assertFalse(out.endswith("\n\n"))
        lines = out.splitlines()
        self.assertEqual(len(lines), 1)
        first = lines[0]
        first.encode("ascii")
        doc = json.loads(first)
        self.assertEqual(first, json.dumps(doc, ensure_ascii=True, sort_keys=True))
        self.assertEqual(set(doc), B_KEYS)
        return doc

    def _assert_files(self, doc, rows):
        self.assertEqual(len(doc["files"]), len(rows))
        for got, expect in zip(doc["files"], rows):
            self.assertEqual(set(got), FILE_KEYS)
            self.assertEqual(got, expect)

    def _assert_error(self, doc, prefix, date_text):
        self.assertEqual(doc["date"], date_text)
        self.assertEqual(doc["files"], [])
        self.assertEqual(doc["status"], "error")
        self.assertIsNone(doc["first_present"])
        self.assertEqual(doc["missing"], [])
        self.assertIsInstance(doc["error"], str)
        self.assertTrue(doc["error"].startswith(prefix))
        self.assertNotEqual(doc["error"], "")

    def _row(self, order, path, exists, mtime):
        return {"order": order, "path": path, "exists": exists, "mtime": mtime}

    def _state(self):
        found = {"": self.root.stat().st_mtime_ns}
        for dirpath, dirnames, filenames in os.walk(self.root):
            for name in dirnames:
                path = pathlib.Path(dirpath) / name
                rel = path.relative_to(self.root).as_posix() + "/"
                found[rel] = path.stat().st_mtime_ns
            for name in filenames:
                path = pathlib.Path(dirpath) / name
                rel = path.relative_to(self.root).as_posix()
                data = path.read_bytes()
                st = path.stat()
                found[rel] = (
                    hashlib.sha256(data).hexdigest(),
                    st.st_mtime_ns,
                    st.st_size,
                )
        return found

    def test_both_present(self):
        self._plant(REL_A)
        self._plant(REL_B)
        code, out, err = self._run((PAT_A, PAT_B))
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        doc = self._doc(out)
        self.assertEqual(doc["date"], DATE)
        self.assertEqual(doc["status"], "all")
        self.assertEqual(doc["first_present"], REL_A)
        self.assertEqual(doc["missing"], [])
        self.assertIsNone(doc["error"])
        self._assert_files(doc, [
            self._row(1, REL_A, True, MTIME),
            self._row(2, REL_B, True, MTIME),
        ])

    def test_only_first(self):
        self._plant(REL_A)
        code, out, err = self._run((PAT_A, PAT_B))
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        doc = self._doc(out)
        self.assertEqual(doc["status"], "partial")
        self.assertEqual(doc["first_present"], REL_A)
        self.assertEqual(doc["missing"], [REL_B])
        self._assert_files(doc, [
            self._row(1, REL_A, True, MTIME),
            self._row(2, REL_B, False, None),
        ])

    def test_only_second(self):
        self._plant(REL_B)
        code, out, err = self._run((PAT_A, PAT_B))
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        doc = self._doc(out)
        self.assertEqual(doc["status"], "partial")
        self.assertEqual(doc["first_present"], REL_B)
        self.assertEqual(doc["missing"], [REL_A])
        self._assert_files(doc, [
            self._row(1, REL_A, False, None),
            self._row(2, REL_B, True, MTIME),
        ])

    def test_none_present(self):
        code, out, err = self._run((PAT_A, PAT_B))
        self.assertEqual(code, 3)
        self.assertEqual(err, "")
        doc = self._doc(out)
        self.assertEqual(doc["status"], "missing")
        self.assertIsNone(doc["first_present"])
        self.assertEqual(doc["missing"], [REL_A, REL_B])
        self._assert_files(doc, [
            self._row(1, REL_A, False, None),
            self._row(2, REL_B, False, None),
        ])

    def test_single_pattern(self):
        self._plant(REL_B)
        code, out, err = self._run((PAT_B,))
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        doc = self._doc(out)
        self.assertEqual(doc["status"], "all")
        self.assertEqual(doc["first_present"], REL_B)
        self.assertEqual(doc["missing"], [])
        self._assert_files(doc, [self._row(1, REL_B, True, MTIME)])

    def test_missing_pattern_exits_2(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            with self.assertRaises(SystemExit) as caught:
                daily_file_presence.main([
                    "--root",
                    str(self.root),
                    "--date",
                    DATE,
                ])
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(stdout.getvalue().strip(), "")
        self.assertTrue(stderr.getvalue().strip())
        self.assertNotIn(str(self.root), stdout.getvalue())

    def test_missing_pattern_subprocess_exit_2(self):
        env = os.environ.copy()
        env.pop("PYTHONSTARTUP", None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--root",
                str(self.root),
                "--date",
                DATE,
            ],
            cwd=str(REPO),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout.strip(), "")
        self.assertTrue(proc.stderr.strip())
        self.assertNotIn(str(self.root), proc.stdout)

    def test_mtime_round_trip(self):
        self._plant(REL_A, stamp=STAMP)
        code, out, err = self._run((PAT_A,))
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        doc = self._doc(out)
        text = doc["files"][0]["mtime"]
        self.assertRegex(text, MTIME_RE)
        self.assertEqual(text, MTIME)
        parsed = datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%S%z")
        self.assertEqual(int(parsed.timestamp()), STAMP)

    def test_fractional_mtime_is_truncated(self):
        path = self._plant(REL_A, stamp=STAMP)
        os.utime(path, (STAMP + 0.9, STAMP + 0.9))
        actual = path.stat().st_mtime
        code, out, err = self._run((PAT_A,))
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        doc = self._doc(out)
        whole = int(actual)
        when = datetime.datetime.fromtimestamp(whole, tz=JST)
        expect = when.strftime("%Y-%m-%dT%H:%M:%S") + "+09:00"
        self.assertEqual(doc["files"][0]["mtime"], expect)
        if actual != int(actual) and actual - int(actual) >= 0.5:
            rounded = datetime.datetime.fromtimestamp(int(actual) + 1, tz=JST)
            rounded_text = rounded.strftime("%Y-%m-%dT%H:%M:%S") + "+09:00"
            self.assertNotEqual(doc["files"][0]["mtime"], rounded_text)

    def test_yesterday_only_is_missing(self):
        self._plant(YREL_A)
        self._plant(YREL_B)
        code, out, err = self._run((PAT_A, PAT_B))
        self.assertEqual(code, 3)
        self.assertEqual(err, "")
        doc = self._doc(out)
        self.assertEqual(doc["status"], "missing")
        self.assertIsNone(doc["first_present"])
        self.assertEqual(doc["missing"], [REL_A, REL_B])
        self._assert_files(doc, [
            self._row(1, REL_A, False, None),
            self._row(2, REL_B, False, None),
        ])

    def test_directory_same_name_is_absent(self):
        path = self.root.joinpath(*REL_A.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.mkdir()
        code, out, err = self._run((PAT_A,))
        self.assertEqual(code, 3)
        self.assertEqual(err, "")
        doc = self._doc(out)
        self.assertEqual(doc["status"], "missing")
        self.assertIs(doc["files"][0]["exists"], False)
        self.assertIsNone(doc["files"][0]["mtime"])

    def test_three_patterns_keep_order(self):
        pat_c = "c/note-{YYYYMMDD}.txt"
        rel_c = "c/note-20260120.txt"
        self._plant(rel_c)
        code, out, err = self._run((PAT_A, PAT_B, pat_c))
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        doc = self._doc(out)
        self.assertEqual(doc["status"], "partial")
        self.assertEqual(doc["first_present"], rel_c)
        self.assertEqual(doc["missing"], [REL_A, REL_B])
        self._assert_files(doc, [
            self._row(1, REL_A, False, None),
            self._row(2, REL_B, False, None),
            self._row(3, rel_c, True, MTIME),
        ])

    def test_bad_pattern_parent_segment(self):
        code, out, err = self._run(("../x",))
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        doc = self._doc(out)
        self._assert_error(doc, "bad_pattern", DATE)

    def test_bad_pattern_absolute(self):
        code, out, err = self._run(("/abs/report.json",))
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        doc = self._doc(out)
        self._assert_error(doc, "bad_pattern", DATE)

    def test_bad_pattern_unknown_placeholder(self):
        code, out, err = self._run(("a/{foo}.json",))
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        doc = self._doc(out)
        self._assert_error(doc, "bad_pattern", DATE)

    def test_bad_pattern_date_placeholder(self):
        code, out, err = self._run(("a/{date}.json",))
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        doc = self._doc(out)
        self._assert_error(doc, "bad_pattern", DATE)

    def test_bad_pattern_backslash(self):
        code, out, err = self._run(("a\\report.json",))
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        doc = self._doc(out)
        self._assert_error(doc, "bad_pattern", DATE)

    def test_bad_pattern_unbalanced(self):
        code, out, err = self._run(("a/{YYYY-MM-DD.json",))
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        doc = self._doc(out)
        self._assert_error(doc, "bad_pattern", DATE)

    def test_bad_date(self):
        samples = ("2026-02-31", "2026-1-20", "yesterday", "", "2026-01-20T00:00:00")
        for sample in samples:
            with self.subTest(sample=sample):
                code, out, err = self._run((PAT_A,), date=sample)
                self.assertEqual(code, 2)
                self.assertEqual(err, "")
                doc = self._doc(out)
                self._assert_error(doc, "bad_date", None)

    def test_bad_root_missing(self):
        missing = self.root / "missing-dir"
        code, out, err = invoke([
            "--root",
            str(missing),
            "--date",
            DATE,
            "--pattern",
            PAT_A,
        ])
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        self.assertNotIn(str(missing), out)
        self.assertNotIn(str(self.root), out)
        doc = self._doc(out)
        self._assert_error(doc, "bad_root", DATE)

    def test_bad_root_file(self):
        note = self.root / "note.txt"
        note.write_text("x\n", encoding="utf-8")
        code, out, err = invoke([
            "--root",
            str(note),
            "--date",
            DATE,
            "--pattern",
            PAT_A,
        ])
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        self.assertNotIn(str(note), out)
        doc = self._doc(out)
        self._assert_error(doc, "bad_root", DATE)

    def test_snapshot_unchanged(self):
        self._plant(REL_A)
        self._plant(YREL_B)
        before = self._state()
        code, out, err = self._run((PAT_A, PAT_B))
        after = self._state()
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self._doc(out)
        self.assertEqual(before, after)
        code, out, err = self._run((PAT_B,))
        self.assertEqual(code, 3)
        self.assertEqual(self._state(), before)

    def test_unreadable_file_still_exists(self):
        path = self._plant(REL_A)
        os.chmod(path, 0)
        try:
            mode = path.stat().st_mode & 0o777
            if mode != 0 and os.geteuid() != 0:
                self.skipTest("mode 000 did not stick")
            os.utime(path, (STAMP, STAMP))
            code, out, err = self._run((PAT_A, PAT_B))
        finally:
            os.chmod(path, 0o644)
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        doc = self._doc(out)
        self.assertIs(doc["files"][0]["exists"], True)
        self.assertEqual(doc["files"][0]["mtime"], MTIME)
        self.assertEqual(doc["status"], "partial")

    def test_default_date_is_jst_today(self):
        before = datetime.datetime.now(JST).date()
        rel = "a/report-" + before.isoformat() + ".json"
        self._plant(rel)
        code, out, err = self._run(
            ("a/report-{YYYY-MM-DD}.json",),
            date=None,
        )
        after = datetime.datetime.now(JST).date()
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        doc = self._doc(out)
        self.assertIn(doc["date"], {before.isoformat(), after.isoformat()})
        self.assertIs(doc["files"][0]["exists"], True)

    def test_script_source_has_no_scheme_or_dated_template(self):
        source = pathlib.Path(daily_file_presence.__file__).read_text(encoding="utf-8")
        self.assertNotIn(":" + "//", source)
        for line in source.splitlines():
            if "{YYYY-MM-DD}" in line or "{YYYYMMDD}" in line:
                self.assertNotIn("/", line)
                self.assertNotIn("\\", line)

    def test_import_is_silent(self):
        env = os.environ.copy()
        env.pop("PYTHONSTARTUP", None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = str(REPO / "routines")
        proc = subprocess.run(
            [sys.executable, "-c", "import daily_file_presence"],
            cwd=str(REPO),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")
        self.assertEqual(proc.stderr, "")


if __name__ == "__main__":
    unittest.main()
