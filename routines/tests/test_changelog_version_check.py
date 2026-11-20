"""Offline tests for the changelog version check."""

import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import changelog_version_check


FIXTURE = (
    pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "changelog_sample.html"
)
REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "routines" / "changelog_version_check.py"
PAGE_VERSION = "v2.10.0"
PAGE_DATE = "2026-01-20"
SUMMARY = "Changelog 最新：" + PAGE_VERSION + "（" + PAGE_DATE + "，本次讀網頁確認）"
FAIL_LINE = "Changelog 本次未能讀取"
NEW_210 = (
    {
        "version": "v2.10.0",
        "section": "New",
        "text": "Calendar sync now runs every 5 minutes.",
    },
    {
        "version": "v2.10.0",
        "section": "New",
        "text": "Search & filters load twice as fast. Beta",
    },
    {
        "version": "v2.10.0",
        "section": "Fixed",
        "text": "Fixed a crash when a list was empty.",
    },
)
NEW_291 = (
    {
        "version": "v2.9.1",
        "section": "Improved",
        "text": "Settings page remembers the last tab.",
    },
    {
        "version": "v2.9.1",
        "section": "Fixed",
        "text": "Fixed dates showing in the wrong order.",
    },
)
FIVE = NEW_210 + NEW_291
A_KEYS = {"version", "date", "changed", "new_entries", "error"}
ENTRY_KEYS = {"version", "section", "text"}


def invoke(argv):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
        code = changelog_version_check.main(list(argv))
    return code, stdout.getvalue(), stderr.getvalue()


def fixture_args(previous, extra=()):
    return [
        "--input-file",
        str(FIXTURE),
        "--previous-version",
        previous,
        *extra,
    ]


class ChangelogVersionCheckTests(unittest.TestCase):
    maxDiff = None

    def _doc(self, out, count):
        self.assertTrue(out.endswith("\n"))
        self.assertFalse(out.endswith("\n\n"))
        lines = out.splitlines()
        self.assertEqual(len(lines), count)
        first = lines[0]
        first.encode("ascii")
        doc = json.loads(first)
        self.assertEqual(
            first, json.dumps(doc, ensure_ascii=True, sort_keys=True)
        )
        self.assertEqual(set(doc), A_KEYS)
        return doc, lines

    def _assert_error(self, doc, prefix, previous):
        self.assertIsNone(doc["version"])
        self.assertNotEqual(doc["version"], previous)
        self.assertIsNone(doc["date"])
        self.assertIs(doc["changed"], False)
        self.assertEqual(doc["new_entries"], [])
        self.assertIsInstance(doc["error"], str)
        self.assertNotEqual(doc["error"], "")
        self.assertTrue(doc["error"].startswith(prefix))

    def _assert_entries(self, doc, entries):
        self.assertEqual(len(doc["new_entries"]), len(entries))
        for got, expect in zip(doc["new_entries"], entries):
            self.assertEqual(set(got), ENTRY_KEYS)
            self.assertEqual(got, expect)

    def _success(self, previous, code, changed, entries, text=None):
        argv = fixture_args(previous)
        count = 1
        if text is not None:
            argv.append("--text-line")
            count = 1 + len(text)
        exit_code, out, err = invoke(argv)
        self.assertEqual(err, "")
        self.assertEqual(exit_code, code)
        doc, lines = self._doc(out, count)
        self.assertEqual(doc["version"], PAGE_VERSION)
        self.assertEqual(doc["date"], PAGE_DATE)
        self.assertIs(doc["changed"], changed)
        self.assertIsNone(doc["error"])
        if changed:
            self._assert_entries(doc, entries)
        else:
            self.assertEqual(doc["new_entries"], [])
        if text is not None:
            self.assertEqual(lines[1:], list(text))
        return doc

    def test_same_version_exit_0(self):
        self._success("v2.10.0", 0, False, ())

    def test_previous_v291_exit_10_three_entries(self):
        self._success("v2.9.1", 10, True, NEW_210)

    def test_previous_290_without_v_exit_10_five_entries(self):
        self._success("2.9.0", 10, True, FIVE)

    def test_previous_v2910_uses_numeric_compare(self):
        doc = self._success("v2.9.10", 10, True, NEW_210)
        versions = [item["version"] for item in doc["new_entries"]]
        self.assertEqual(versions, ["v2.10.0", "v2.10.0", "v2.10.0"])

    def test_page_behind_previous_exit_0(self):
        doc = self._success("v3.0.0", 0, False, ())
        self.assertEqual(doc["version"], "v2.10.0")
        self.assertNotEqual(doc["version"], "v3.0.0")

    def test_text_line_exit_0(self):
        self._success("v2.10.0", 0, False, (), text=[SUMMARY])

    def test_text_line_exit_0_when_page_is_older(self):
        self._success("v3.0.0", 0, False, (), text=[SUMMARY])

    def test_text_line_exit_10(self):
        lines = [SUMMARY]
        for item in NEW_210:
            lines.append(
                "- [" + item["version"] + "] " + item["section"] + ": " + item["text"]
            )
        self._success("v2.9.1", 10, True, NEW_210, text=lines)

    def test_text_line_exit_2(self):
        code, out, err = invoke([
            "--input-file",
            str(FIXTURE),
            "--previous-version",
            "nope",
            "--text-line",
        ])
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        doc, lines = self._doc(out, 2)
        self._assert_error(doc, "bad_previous_version", "nope")
        self.assertEqual(lines[1], FAIL_LINE)

    def test_empty_page(self):
        self._html_error("", "parse_failed", "v1.0.0")

    def test_bait_h2_only(self):
        html = (
            "<!DOCTYPE html><html><body><h2 id=\"v9.9.9\">bait</h2>"
            "</body></html>\n"
        )
        self._html_error(html, "parse_failed", "v1.0.0")

    def test_articles_without_valid_date(self):
        html = (
            "<article><h2 id=\"v1.0.0\">One</h2><p>no time</p></article>"
            "<article><time datetime=\"yesterday\"></time>"
            "<h2 id=\"v1.0.1\">Two</h2></article>"
            "<article><time datetime=\"2026-02-31\"></time>"
            "<h2 id=\"v1.0.2\">Three</h2></article>"
            "<article><time datetime=\"yesterday\"></time>"
            "<time datetime=\"2026-01-20\"></time>"
            "<h2 id=\"v1.2.3\">Later time is ignored</h2></article>"
            "<article><time datetime=\"2026-01-20\"></time>"
            "<h2 id=\"latest\">Bad id</h2>"
            "<h2 id=\"v9.9.9\">Second heading</h2></article>"
        )
        self._html_error(html, "parse_failed", "v1.2.3")

    def test_duplicate_version(self):
        html = (
            "<article><time datetime=\"2026-01-01\"></time>"
            "<h2 id=\"v1.2.3\">A</h2><h3>New</h3><li>One.</li></article>"
            "<article><time datetime=\"2026-01-02\"></time>"
            "<h2 id=\"v1.2.3\">B</h2><h3>Fixed</h3><li>Two.</li></article>"
        )
        self._html_error(html, "parse_failed", "v0.1.0")

    def test_invalid_article_is_not_a_duplicate(self):
        html = (
            "<article><h2 id=\"v1.0.0\">Skip</h2>"
            "<time datetime=\"bogus\"></time></article>"
            "<article><time datetime=\"2026-03-01\"></time>"
            "<h2 id=\"v1.0.0\">Keep</h2><h3>New</h3><li>Only one.</li></article>"
        )
        code, out, err = self._html(html, "v0.0.1")
        self.assertEqual(code, 10)
        self.assertEqual(err, "")
        doc, _lines = self._doc(out, 1)
        self.assertEqual(doc["version"], "v1.0.0")
        self.assertIs(doc["changed"], True)
        self.assertEqual(doc["new_entries"], [
            {"version": "v1.0.0", "section": "New", "text": "Only one."},
        ])

    def test_latest_is_numeric_max_not_document_order(self):
        html = (
            "<article><time datetime=\"2026-04-01\"></time>"
            "<h2 id=\"v1.0.0\">Old</h2><h3>New</h3><li>First block.</li></article>"
            "<article><time datetime=\"2026-05-02\"></time>"
            "<h2 id=\"v1.2.0\">New</h2><h3>Fixed</h3><li>Second block.</li></article>"
            "<article><time datetime=\"2026-04-15\"></time>"
            "<h2 id=\"v1.1.0\">Mid</h2><h3>Improved</h3>"
            "<li>Third block.</li></article>"
        )
        code, out, err = self._html(html, "v1.0.0")
        self.assertEqual(code, 10)
        self.assertEqual(err, "")
        doc, _lines = self._doc(out, 1)
        self.assertEqual(doc["version"], "v1.2.0")
        self.assertEqual(doc["date"], "2026-05-02")
        self.assertEqual(doc["new_entries"], [
            {"version": "v1.2.0", "section": "Fixed", "text": "Second block."},
            {"version": "v1.1.0", "section": "Improved", "text": "Third block."},
        ])

    def test_bad_previous_version(self):
        samples = ("", "v1.2", "1", "v1.2.3.4", "vv1.2.3", "V1.2.3", "v1.2.3 ", "latest")
        for sample in samples:
            with self.subTest(sample=sample):
                code, out, err = invoke(fixture_args(sample))
                self.assertEqual(code, 2)
                self.assertEqual(err, "")
                doc, _lines = self._doc(out, 1)
                self._assert_error(doc, "bad_previous_version", sample)

    def test_bad_url_file_does_not_call_urlopen(self):
        url = "file://example.invalid/notes"
        with patch("urllib.request.urlopen") as mocked:
            code, out, err = invoke([
                "--url",
                url,
                "--previous-version",
                "v1.0.0",
                "--text-line",
            ])
        self.assertEqual(mocked.call_count, 0)
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        doc, lines = self._doc(out, 2)
        self._assert_error(doc, "bad_url", "v1.0.0")
        self.assertEqual(lines[1], FAIL_LINE)

    def test_bad_url_ftp_does_not_call_urlopen(self):
        url = "ftp://example.invalid/notes"
        with patch("urllib.request.urlopen") as mocked:
            code, out, err = invoke([
                "--url",
                url,
                "--previous-version",
                "v1.0.0",
            ])
        self.assertEqual(mocked.call_count, 0)
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        doc, _lines = self._doc(out, 1)
        self._assert_error(doc, "bad_url", "v1.0.0")

    def test_http_error_404(self):
        def boom(*_args, **_kwargs):
            raise urllib.error.HTTPError(
                "https://example.invalid/changelog",
                404,
                "Not Found",
                None,
                None,
            )

        with patch("urllib.request.urlopen", side_effect=boom) as mocked:
            code, out, err = invoke([
                "--url",
                "https://example.invalid/changelog",
                "--previous-version",
                "v1.2.3",
            ])
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        doc, _lines = self._doc(out, 1)
        self._assert_error(doc, "http_status", "v1.2.3")
        self.assertIn("404", doc["error"])
        self.assertFalse(doc["error"].startswith("fetch_failed"))

    def test_url_error(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("offline"),
        ):
            code, out, err = invoke([
                "--url",
                "https://example.invalid/changelog",
                "--previous-version",
                "v1.2.3",
            ])
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        doc, _lines = self._doc(out, 1)
        self._assert_error(doc, "fetch_failed", "v1.2.3")
        self.assertFalse(doc["error"].startswith("http_status"))

    def test_timeout_error_is_fetch_failed(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError("slow")):
            code, out, err = invoke([
                "--url",
                "https://example.invalid/changelog",
                "--previous-version",
                "v1.2.3",
            ])
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        doc, _lines = self._doc(out, 1)
        self._assert_error(doc, "fetch_failed", "v1.2.3")

    def test_urlopen_matches_input_file(self):
        payload = FIXTURE.read_bytes()

        class Body:
            def __init__(self, data):
                self.data = data

            def read(self, amount=-1):
                if amount is None or amount < 0:
                    return self.data
                return self.data[:amount]

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        url = "https://example.invalid/changelog"
        with patch("urllib.request.urlopen", return_value=Body(payload)) as mocked:
            remote_code, remote_out, remote_err = invoke([
                "--url",
                url,
                "--previous-version",
                "v2.9.1",
                "--timeout",
                "9",
            ])
        local_code, local_out, local_err = invoke(fixture_args("v2.9.1"))
        self.assertEqual(remote_err, "")
        self.assertEqual(local_err, "")
        self.assertEqual(remote_code, local_code)
        self.assertEqual(remote_out, local_out)
        self.assertEqual(remote_code, 10)
        request = mocked.call_args.args[0]
        self.assertIsInstance(request, urllib.request.Request)
        self.assertEqual(request.full_url, url)
        self.assertEqual(request.get_header("User-agent"), "hello-routines/1")
        if "timeout" in mocked.call_args.kwargs:
            seen = mocked.call_args.kwargs["timeout"]
        else:
            seen = mocked.call_args.args[1]
        self.assertEqual(seen, 9)

    def test_read_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = pathlib.Path(tmp) / "missing.html"
            code, out, err = invoke([
                "--input-file",
                str(missing),
                "--previous-version",
                "v1.2.3",
            ])
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        doc, _lines = self._doc(out, 1)
        self._assert_error(doc, "read_failed", "v1.2.3")
        self.assertNotIn(str(missing), out)

    def test_too_large(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "big.html"
            path.write_bytes(b"x" * (8000000 + 1))
            code, out, err = invoke([
                "--input-file",
                str(path),
                "--previous-version",
                "v1.0.0",
            ])
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        doc, _lines = self._doc(out, 1)
        self._assert_error(doc, "too_large", "v1.0.0")

    def test_fixture_shape(self):
        text = FIXTURE.read_text(encoding="utf-8")
        self.assertEqual(text.lower().count("<article"), 3)
        self.assertIn('dateTime="2026-01-20"', text)
        self.assertIn(">January 20, 2026<", text)
        self.assertIn('<h2 id="v9.9.9">', text)
        self.assertIn("<p>Also includes <!-- -->2.9.2</p>", text)
        self.assertIn('<a href="#v2.10.0">v<!-- -->2.10.0</a>', text)
        self.assertIn('<a href="#v2.9.1">v<!-- -->2.9.1</a>', text)
        self.assertIn('<a href="#v2.9.0">v<!-- -->2.9.0</a>', text)
        self.assertIn(
            "<li><span aria-hidden=\"true\" class=\"dot\"></span><span>"
            "Search &amp; filters load twice as fast."
            "<span class=\"badge\">Beta</span></span></li>",
            text,
        )

    def test_script_source_has_no_scheme_separator(self):
        source = pathlib.Path(changelog_version_check.__file__).read_text(
            encoding="utf-8"
        )
        self.assertNotIn(":" + "//", source)

    def test_import_is_silent(self):
        env = os.environ.copy()
        env.pop("PYTHONSTARTUP", None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = str(REPO / "routines")
        proc = subprocess.run(
            [sys.executable, "-c", "import changelog_version_check"],
            cwd=str(REPO),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")
        self.assertEqual(proc.stderr, "")

    def test_text_line_subprocess(self):
        env = os.environ.copy()
        env.pop("PYTHONSTARTUP", None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--input-file",
                str(FIXTURE),
                "--previous-version",
                "v2.10.0",
                "--text-line",
            ],
            cwd=str(REPO),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr, "")
        lines = proc.stdout.splitlines()
        self.assertEqual(lines[1], SUMMARY)

    def _html(self, html, previous):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "page.html"
            path.write_text(html, encoding="utf-8")
            return invoke([
                "--input-file",
                str(path),
                "--previous-version",
                previous,
            ])

    def _html_error(self, html, prefix, previous):
        code, out, err = self._html(html, previous)
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        doc, _lines = self._doc(out, 1)
        self._assert_error(doc, prefix, previous)


if __name__ == "__main__":
    unittest.main()
