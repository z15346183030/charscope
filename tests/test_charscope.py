"""Tests for charscope.  Standard library unittest, no fixtures needed."""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import charscope as cs  # noqa: E402

PY = sys.executable
TOOL = os.path.join(REPO, "charscope.py")


class TestScriptOf(unittest.TestCase):
    def test_basic_latin(self):
        self.assertEqual(cs.script_of("a"), "Latin")
        self.assertEqual(cs.script_of("Z"), "Latin")

    def test_latin_extended(self):
        self.assertEqual(cs.script_of("é"), "Latin")
        self.assertEqual(cs.script_of("ß"), "Latin")

    def test_greek(self):
        self.assertEqual(cs.script_of("α"), "Greek")
        self.assertEqual(cs.script_of("Ω"), "Greek")

    def test_cyrillic(self):
        self.assertEqual(cs.script_of("д"), "Cyrillic")
        self.assertEqual(cs.script_of("Я"), "Cyrillic")

    def test_cjk(self):
        self.assertEqual(cs.script_of("中"), "CJK")
        self.assertEqual(cs.script_of("文"), "CJK")

    def test_kana(self):
        self.assertEqual(cs.script_of("あ"), "Hiragana")
        self.assertEqual(cs.script_of("カ"), "Katakana")

    def test_hangul(self):
        self.assertEqual(cs.script_of("한"), "Hangul")

    def test_other_scripts(self):
        self.assertEqual(cs.script_of("א"), "Hebrew")
        self.assertEqual(cs.script_of("ب"), "Arabic")
        self.assertEqual(cs.script_of("क"), "Devanagari")
        self.assertEqual(cs.script_of("ก"), "Thai")

    def test_fullwidth_is_latin(self):
        self.assertEqual(cs.script_of("ａ"), "Latin")

    def test_digits_are_common(self):
        for ch in "0123456789":
            self.assertEqual(cs.script_of(ch), "Common")

    def test_punctuation_is_common(self):
        for ch in ".,!?-—":
            self.assertEqual(cs.script_of(ch), "Common")

    def test_whitespace_is_common(self):
        self.assertEqual(cs.script_of(" "), "Common")
        self.assertEqual(cs.script_of("\n"), "Common")

    def test_emoji_is_common(self):
        self.assertEqual(cs.script_of("😀"), "Common")

    def test_range_boundaries(self):
        self.assertEqual(cs.script_of(chr(0x0040)), "Common")   # @
        self.assertEqual(cs.script_of(chr(0x0041)), "Latin")
        self.assertEqual(cs.script_of(chr(0x005A)), "Latin")
        self.assertEqual(cs.script_of(chr(0x005B)), "Common")   # [
        self.assertEqual(cs.script_of(chr(0x043F)), "Cyrillic")  # п

    def test_non_bmp_cjk(self):
        self.assertEqual(cs.script_of(chr(0x20000)), "CJK")

    def test_unassigned_is_unknown(self):
        self.assertEqual(cs.script_of(chr(0x2065)), "Unknown")


class TestClassify(unittest.TestCase):
    def test_plain_ascii(self):
        info = cs.classify("a")
        self.assertEqual(info.category, "Ll")
        self.assertEqual(info.severity, "ok")
        self.assertEqual(info.reasons, ())
        self.assertEqual(info.lookalike, "")

    def test_space(self):
        info = cs.classify(" ")
        self.assertEqual(info.category, "Zs")
        self.assertEqual(info.severity, "ok")

    def test_tab_newline_cr_are_ok(self):
        for ch in "\t\n\r":
            self.assertEqual(cs.classify(ch).severity, "ok", repr(ch))

    def test_zero_width_space(self):
        info = cs.classify("\u200b")
        self.assertEqual(info.category, "Cf")
        self.assertEqual(info.severity, "alert")
        self.assertIn("zero-width", info.reasons)
        self.assertIn("invisible", info.reasons)

    def test_zero_width_joiner(self):
        info = cs.classify("\u200d")
        self.assertIn("zero-width", info.reasons)
        self.assertEqual(info.severity, "alert")

    def test_bom_in_middle(self):
        info = cs.classify("\ufeff")
        self.assertEqual(info.category, "Cf")
        self.assertIn("zero-width", info.reasons)

    def test_bidi_override(self):
        info = cs.classify("\u202e")
        self.assertIn("bidirectional control", info.reasons)
        self.assertEqual(info.severity, "alert")

    def test_bidi_embed(self):
        self.assertIn("bidirectional control", cs.classify("\u202a").reasons)
        self.assertIn("bidirectional control", cs.classify("\u2066").reasons)

    def test_soft_hyphen_is_format(self):
        info = cs.classify("\u00ad")
        self.assertEqual(info.category, "Cf")
        self.assertIn("invisible", info.reasons)

    def test_nul_control(self):
        info = cs.classify("\x00")
        self.assertEqual(info.category, "Cc")
        self.assertIn("control character", info.reasons)
        self.assertEqual(info.severity, "alert")

    def test_escape_control(self):
        self.assertEqual(cs.classify("\x1b").severity, "alert")

    def test_line_separator(self):
        info = cs.classify("\u2028")
        self.assertEqual(info.category, "Zl")
        self.assertIn("non-standard line break", info.reasons)

    def test_nbsp(self):
        info = cs.classify("\u00a0")
        self.assertEqual(info.category, "Zs")
        self.assertEqual(info.lookalike, " ")
        self.assertEqual(info.severity, "alert")

    def test_ideographic_space(self):
        info = cs.classify("\u3000")
        self.assertEqual(info.lookalike, " ")
        self.assertEqual(info.severity, "alert")

    def test_cyrillic_a(self):
        info = cs.classify("\u0430")
        self.assertEqual(info.lookalike, "a")
        self.assertEqual(info.severity, "alert")
        self.assertEqual(info.script, "Cyrillic")

    def test_greek_o(self):
        info = cs.classify("\u03bf")
        self.assertEqual(info.lookalike, "o")
        self.assertEqual(info.severity, "alert")

    def test_fullwidth_a(self):
        info = cs.classify("\uff41")
        self.assertEqual(info.lookalike, "a")
        self.assertIn("fullwidth", " ".join(info.reasons))
        self.assertEqual(info.severity, "alert")

    def test_fullwidth_digit(self):
        info = cs.classify("\uff11")
        self.assertEqual(info.lookalike, "1")
        self.assertEqual(info.severity, "alert")

    def test_em_dash_is_notice(self):
        info = cs.classify("\u2014")
        self.assertEqual(info.lookalike, "-")
        self.assertEqual(info.severity, "notice")

    def test_curly_quote_is_notice(self):
        self.assertEqual(cs.classify("\u2019").severity, "notice")
        self.assertEqual(cs.classify("\u201c").severity, "notice")

    def test_real_emoji_clean(self):
        self.assertEqual(cs.classify("😀").severity, "ok")

    def test_combining_mark_clean(self):
        self.assertEqual(cs.classify("\u0301").category, "Mn")
        self.assertEqual(cs.classify("\u0301").severity, "ok")

    def test_name_present(self):
        self.assertEqual(cs.classify("a").name, "LATIN SMALL LETTER A")

    def test_unnamed_character(self):
        info = cs.classify("\u0378")
        self.assertIn("no Unicode name", info.name)

    def test_classify_is_deterministic(self):
        self.assertEqual(cs.classify("a"), cs.classify("a"))
        self.assertEqual(cs.classify("\u200b"), cs.classify("\u200b"))

    def test_every_homoglyph_classifies(self):
        for cp in cs.HOMOGLYPHS:
            info = cs.classify(chr(cp))
            self.assertNotEqual(info.severity, "ok", hex(cp))
            self.assertTrue(info.lookalike, hex(cp))

    def test_no_duplicate_homoglyph_keys_losing_data(self):
        # Every declared Cyrillic entry must still survive after dict creation.
        for cp in (0x0410, 0x0430, 0x043E, 0x0445):
            self.assertIn(cp, cs.HOMOGLYPHS)


class TestLabels(unittest.TestCase):
    def test_cp_label(self):
        self.assertEqual(cs.cp_label("a"), "U+0061")
        self.assertEqual(cs.cp_label("\u200b"), "U+200B")

    def test_display_printable(self):
        self.assertEqual(cs.display("a"), "a")

    def test_display_invisible(self):
        self.assertEqual(cs.display("\u200b"), "\\u200B")

    def test_display_newline(self):
        self.assertEqual(cs.display("\n"), "\\u000A")

    def test_quote_space(self):
        self.assertIn("space", cs._quote(" "))

    def test_quote_apostrophe(self):
        self.assertEqual(cs._quote("'"), "\"'\"")

    def test_all_categories_have_labels(self):
        for ch in "aA1.,()— \t\n\u200b":
            self.assertIn(cs.classify(ch).category, cs.CATEGORY_LABELS)


class TestAnalyze(unittest.TestCase):
    def test_empty_text(self):
        a = cs.analyze("")
        self.assertEqual(a.total_chars, 0)
        self.assertEqual(a.total_lines, 0)
        self.assertEqual(a.distinct, 0)
        self.assertFalse(a.has_alert)

    def test_ascii_text(self):
        a = cs.analyze("abc")
        self.assertEqual(a.total_chars, 3)
        self.assertEqual(a.total_lines, 1)
        self.assertEqual(a.distinct, 3)
        self.assertEqual(a.categories[0][0], "Ll")
        self.assertEqual(a.categories[0][1], 3)
        self.assertFalse(a.has_alert)
        self.assertEqual(a.suspicious, [])

    def test_distinct_counts_codepoints(self):
        self.assertEqual(cs.analyze("aaa").distinct, 1)
        self.assertEqual(cs.analyze("aA").distinct, 2)

    def test_lines(self):
        self.assertEqual(cs.analyze("a\nb").total_lines, 2)
        self.assertEqual(cs.analyze("a\n").total_lines, 2)
        self.assertEqual(cs.analyze("a\nb\n").total_lines, 3)

    def test_category_counts(self):
        a = cs.analyze("aA1 ")
        codes = dict(a.categories)
        self.assertEqual(codes["Ll"], 1)
        self.assertEqual(codes["Lu"], 1)
        self.assertEqual(codes["Nd"], 1)
        self.assertEqual(codes["Zs"], 1)

    def test_categories_sorted_by_count(self):
        a = cs.analyze("aab")
        self.assertEqual(a.categories[0], ("Ll", 3))

    def test_examples_top_five(self):
        a = cs.analyze("abcdefghij")
        examples = a.category_examples["Ll"]
        self.assertEqual(len(examples), 5)
        self.assertEqual(examples[0][1], 1)

    def test_script_counts(self):
        a = cs.analyze("abc中")
        scripts = dict(a.scripts)
        self.assertEqual(scripts["Latin"], 3)
        self.assertEqual(scripts["CJK"], 1)

    def test_scripts_sorted(self):
        a = cs.analyze("aa中")
        self.assertEqual(a.scripts[0], ("Latin", 2))

    def test_suspicious_grouped(self):
        a = cs.analyze("a\u200bb\u200bc")
        self.assertEqual(len(a.suspicious), 1)
        self.assertEqual(a.suspicious[0].count, 2)
        self.assertEqual(a.suspicious_occurrences, 2)

    def test_suspicious_locations(self):
        a = cs.analyze("x\na\u200b")
        entry = a.suspicious[0]
        self.assertEqual(entry.first_location(), (2, 2))

    def test_locations_capped_at_five(self):
        a = cs.analyze("\u200b" * 10)
        self.assertEqual(len(a.suspicious[0].locations), 5)
        self.assertEqual(a.suspicious[0].count, 10)

    def test_alert_first_in_order(self):
        a = cs.analyze("\u2014\u200b")   # notice then alert
        self.assertEqual(a.suspicious[0].info.severity, "alert")

    def test_alert_occurrences(self):
        a = cs.analyze("a\u200b\u2014")
        self.assertEqual(a.alert_occurrences, 1)
        self.assertEqual(a.suspicious_occurrences, 2)

    def test_notice_only_is_not_alert(self):
        a = cs.analyze("a\u2014b")
        self.assertFalse(a.has_alert)
        self.assertEqual(a.suspicious_occurrences, 1)

    def test_unicode_name_in_entry(self):
        a = cs.analyze("\u200b")
        self.assertEqual(a.suspicious[0].info.name, "ZERO WIDTH SPACE")

    def test_source_is_kept(self):
        self.assertEqual(cs.analyze("a", source="x.txt").source, "x.txt")

    def test_source_default(self):
        self.assertEqual(cs.analyze("a").source, "<stdin>")

    def test_column_counts_characters_not_bytes(self):
        a = cs.analyze("中\u200b")
        self.assertEqual(a.suspicious[0].first_location(), (1, 2))

    def test_crlf_column(self):
        a = cs.analyze("a\r\nb\u200b")
        self.assertEqual(a.suspicious[0].first_location(), (2, 2))

    def test_empty_reasons_clean(self):
        a = cs.analyze("hello world")
        self.assertEqual(a.suspicious, [])
        self.assertEqual(a.alert_occurrences, 0)


class TestRenderText(unittest.TestCase):
    def test_header(self):
        out = cs.render_text(cs.analyze("abc", "f.txt"))
        self.assertIn("== charscope: f.txt ==", out)

    def test_totals(self):
        out = cs.render_text(cs.analyze("abc"))
        self.assertIn("chars: 3   lines: 1   distinct: 3", out)

    def test_category_section(self):
        out = cs.render_text(cs.analyze("aA"))
        self.assertIn("Category breakdown", out)
        self.assertIn("lowercase letter", out)
        self.assertIn("uppercase letter", out)

    def test_percent(self):
        out = cs.render_text(cs.analyze("aa"))
        self.assertIn("100.0%", out)

    def test_scripts_hidden_by_default(self):
        out = cs.render_text(cs.analyze("abc中"))
        self.assertNotIn("Script breakdown", out)

    def test_scripts_shown(self):
        out = cs.render_text(cs.analyze("abc中"), show_scripts=True)
        self.assertIn("Script breakdown", out)
        self.assertIn("Latin", out)
        self.assertIn("CJK", out)

    def test_unusual_section(self):
        out = cs.render_text(cs.analyze("a\u200b"))
        self.assertIn("Unusual characters (1 distinct, 1 occurrences, 1 alerts)", out)
        self.assertIn("U+200B", out)
        self.assertIn("L1:C2", out)

    def test_none_section(self):
        out = cs.render_text(cs.analyze("abc"))
        self.assertIn("Unusual characters: none", out)

    def test_verdict_clean(self):
        self.assertIn("Verdict: clean", cs.render_text(cs.analyze("abc")))

    def test_verdict_alert(self):
        self.assertIn("Verdict: alert", cs.render_text(cs.analyze("\u200b")))

    def test_more_marker(self):
        out = cs.render_text(cs.analyze("\u200b\u200b"))
        self.assertIn("(+1 more)", out)

    def test_empty_text_render(self):
        out = cs.render_text(cs.analyze(""))
        self.assertIn("chars: 0", out)
        self.assertNotIn("nan", out)
        self.assertNotIn("ZeroDivisionError", out)


class TestRenderJson(unittest.TestCase):
    def test_valid_json(self):
        data = json.loads(cs.render_json(cs.analyze("abc")))
        self.assertEqual(data["chars"], 3)

    def test_keys(self):
        data = json.loads(cs.render_json(cs.analyze("a")))
        for key in ("source", "chars", "lines", "distinct", "categories",
                    "scripts", "suspicious", "verdict"):
            self.assertIn(key, data)

    def test_category_fields(self):
        data = json.loads(cs.render_json(cs.analyze("aaa")))
        cat = data["categories"][0]
        self.assertEqual(cat["code"], "Ll")
        self.assertEqual(cat["count"], 3)
        self.assertEqual(cat["percent"], 100.0)
        self.assertEqual(len(cat["examples"]), 1)

    def test_suspicious_fields(self):
        data = json.loads(cs.render_json(cs.analyze("a\u200b")))
        item = data["suspicious"][0]
        self.assertEqual(item["codepoint"], "U+200B")
        self.assertEqual(item["severity"], "alert")
        self.assertEqual(item["locations"], [{"line": 1, "column": 2}])

    def test_unicode_output(self):
        data = json.loads(cs.render_json(cs.analyze("中")))
        self.assertEqual(data["categories"][0]["examples"][0]["char"], "中")

    def test_verdict(self):
        self.assertEqual(json.loads(cs.render_json(cs.analyze("\u200b")))["verdict"], "alert")
        self.assertEqual(json.loads(cs.render_json(cs.analyze("a")))["verdict"], "clean")

    def test_empty_json(self):
        data = json.loads(cs.render_json(cs.analyze("")))
        self.assertEqual(data["categories"], [])
        self.assertEqual(data["verdict"], "clean")


class TestFind(unittest.TestCase):
    def test_find_by_category(self):
        out, status = cs.render_find(cs.analyze("a1b"), "Nd")
        self.assertEqual(status, 0)
        self.assertIn("matches: 1", out)
        self.assertIn("U+0031", out)

    def test_find_by_codepoint(self):
        out, status = cs.render_find(cs.analyze("a\u200bb\u200b"), "U+200B")
        self.assertEqual(status, 0)
        self.assertIn("matches: 2", out)

    def test_find_lowercase_codepoint(self):
        out, status = cs.render_find(cs.analyze("\u200b"), "u+200b")
        self.assertEqual(status, 0)
        self.assertIn("matches: 1", out)

    def test_find_zero_matches(self):
        out, status = cs.render_find(cs.analyze("abc"), "Nd")
        self.assertIn("matches: 0", out)
        self.assertEqual(status, 0)

    def test_find_bad_category(self):
        out, status = cs.render_find(cs.analyze("a"), "XX")
        self.assertEqual(status, 2)
        self.assertIn("unknown category", out)

    def test_find_bad_codepoint(self):
        out, status = cs.render_find(cs.analyze("a"), "U+ZZZZ")
        self.assertEqual(status, 2)
        self.assertIn("bad code point", out)

    def test_find_codepoint_too_large(self):
        out, status = cs.render_find(cs.analyze("a"), "U+110000")
        self.assertEqual(status, 2)

    def test_find_location(self):
        out, _ = cs.render_find(cs.analyze("a\nb\u200b"), "U+200B")
        self.assertIn("L2:C2", out)

    def test_find_cap(self):
        out, status = cs.render_find(cs.analyze("a" * 600), "Ll")
        self.assertIn("showing first 500", out)
        self.assertEqual(status, 0)

    def test_find_reason_column(self):
        out, _ = cs.render_find(cs.analyze("\u200b"), "U+200B")
        self.assertIn("zero-width", out)


class TestExplain(unittest.TestCase):
    def test_has_rules(self):
        out = cs.render_explain()
        self.assertIn("classification rules", out)
        self.assertIn("binary search", out)
        self.assertIn("exit code", out)


class TestReadText(unittest.TestCase):
    def test_read_plain(self):
        with tempfile.NamedTemporaryFile("wb", delete=False, suffix=".txt") as f:
            f.write("hello\n".encode("utf-8"))
            path = f.name
        try:
            self.assertEqual(cs.read_text(path), "hello\n")
        finally:
            os.unlink(path)

    def test_bom_stripped(self):
        with tempfile.NamedTemporaryFile("wb", delete=False, suffix=".txt") as f:
            f.write(b"\xef\xbb\xbfhello")
            path = f.name
        try:
            self.assertEqual(cs.read_text(path), "hello")
        finally:
            os.unlink(path)

    def test_inner_bom_kept(self):
        with tempfile.NamedTemporaryFile("wb", delete=False, suffix=".txt") as f:
            f.write("a\ufeffb".encode("utf-8"))
            path = f.name
        try:
            self.assertEqual(cs.read_text(path), "a\ufeffb")
        finally:
            os.unlink(path)

    def test_crlf_kept(self):
        with tempfile.NamedTemporaryFile("wb", delete=False, suffix=".txt") as f:
            f.write(b"a\r\nb")
            path = f.name
        try:
            self.assertEqual(cs.read_text(path), "a\r\nb")
        finally:
            os.unlink(path)

    def test_bad_utf8(self):
        with tempfile.NamedTemporaryFile("wb", delete=False, suffix=".txt") as f:
            f.write(b"abc\xff")
            path = f.name
        try:
            with self.assertRaises(ValueError):
                cs.read_text(path)
        finally:
            os.unlink(path)

    def test_missing_file(self):
        with self.assertRaises(OSError):
            cs.read_text(os.path.join(os.path.dirname(__file__), "does-not-exist.txt"))


class TestMainInProcess(unittest.TestCase):
    def call(self, argv, stdin_bytes=b""):
        old_in = sys.stdin
        out = io.StringIO()
        err = io.StringIO()
        try:
            sys.stdin = type("S", (), {"buffer": io.BytesIO(stdin_bytes)})()
            with redirect_stdout(out), redirect_stderr(err):
                status = cs.main(argv)
        finally:
            sys.stdin = old_in
        return status, out.getvalue(), err.getvalue()

    def test_stdin_ascii(self):
        status, out, err = self.call([], b"hello")
        self.assertEqual(status, 0)
        self.assertIn("Verdict: clean", out)
        self.assertEqual(err, "")

    def test_stdin_alert_exit(self):
        status, out, _ = self.call([], "a\u200b".encode("utf-8"))
        self.assertEqual(status, 1)
        self.assertIn("Verdict: alert", out)

    def test_explain_exit(self):
        status, out, _ = self.call(["--explain"])
        self.assertEqual(status, 0)
        self.assertIn("classification rules", out)

    def test_json_flag(self):
        status, out, _ = self.call(["--json"], b"abc")
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(out)["chars"], 3)

    def test_scripts_flag(self):
        _, out, _ = self.call(["--scripts"], "abc中".encode("utf-8"))
        self.assertIn("Script breakdown", out)

    def test_invisible_flag(self):
        status, out, _ = self.call(["--invisible"], "a\u200b".encode("utf-8"))
        self.assertEqual(status, 1)
        self.assertIn("unusual characters in", out)
        self.assertNotIn("Category breakdown", out)

    def test_find_flag(self):
        status, out, _ = self.call(["--find", "U+200B"], "a\u200b".encode("utf-8"))
        self.assertEqual(status, 0)
        self.assertIn("matches: 1", out)

    def test_json_and_find_conflict(self):
        status, _, err = self.call(["--json", "--find", "Ll"], b"a")
        self.assertEqual(status, 2)
        self.assertIn("cannot be combined", err)

    def test_bad_stdin_utf8(self):
        status, _, err = self.call([], b"a\xff")
        self.assertEqual(status, 2)
        self.assertIn("not valid UTF-8", err)

    def test_file_argument(self):
        with tempfile.NamedTemporaryFile("wb", delete=False, suffix=".txt") as f:
            f.write("hello".encode("utf-8"))
            path = f.name
        try:
            status, out, _ = self.call([path])
            self.assertEqual(status, 0)
            self.assertIn(path, out)
        finally:
            os.unlink(path)

    def test_missing_file_exit(self):
        status, _, err = self.call([os.path.join(REPO, "nope.txt")])
        self.assertEqual(status, 2)
        self.assertIn("error:", err)

    def test_multiple_files(self):
        paths = []
        for content in ("abc", "中"):
            f = tempfile.NamedTemporaryFile("wb", delete=False, suffix=".txt")
            f.write(content.encode("utf-8"))
            f.close()
            paths.append(f.name)
        try:
            status, out, _ = self.call(paths)
            self.assertEqual(status, 0)
            self.assertIn("chars: 5", out)  # "abc" + "\n" + "中"
        finally:
            for path in paths:
                os.unlink(path)


class TestCommandLine(unittest.TestCase):
    def run_tool(self, args, stdin_bytes=b""):
        return subprocess.run(
            [PY, TOOL] + args, input=stdin_bytes,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def test_help(self):
        p = self.run_tool(["--help"])
        self.assertEqual(p.returncode, 0)
        self.assertIn(b"usage: charscope", p.stdout)

    def test_version(self):
        p = self.run_tool(["--version"])
        self.assertEqual(p.returncode, 0)
        self.assertIn(b"charscope 1.0.0", p.stdout)

    def test_stdin_clean(self):
        p = self.run_tool([], b"hello world")
        self.assertEqual(p.returncode, 0)
        self.assertIn(b"Verdict: clean", p.stdout)

    def test_stdin_alert(self):
        p = self.run_tool([], "a\u200b".encode("utf-8"))
        self.assertEqual(p.returncode, 1)
        self.assertIn(b"U+200B", p.stdout)

    def test_json_cli(self):
        p = self.run_tool(["--json"], "abc中".encode("utf-8"))
        self.assertEqual(p.returncode, 0)
        data = json.loads(p.stdout.decode("utf-8"))
        self.assertEqual(data["chars"], 4)

    def test_unicode_output_not_crashed(self):
        p = self.run_tool([], "中\u200b".encode("utf-8"))
        self.assertEqual(p.returncode, 1)
        self.assertIn("ZERO WIDTH SPACE".encode(), p.stdout)

    def test_no_traceback(self):
        p = self.run_tool([], b"anything")
        self.assertNotIn(b"Traceback", p.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
