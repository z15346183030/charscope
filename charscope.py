#!/usr/bin/env python3
"""charscope - see exactly which characters are in a text file.

Paste text from a web page, a PDF or a chat and something can look wrong in a
way a hex dump makes hard to see: a space that is not a space, a hyphen that is
not a hyphen, a Latin "a" that is actually Cyrillic.  charscope reads the text
once and reports what every character really is, where the unusual ones sit,
and which ones are worth fixing.

Input:  one or more text files, or standard input when no file is given.
Output: a category breakdown, a script breakdown and a list of characters that
        do not look like what they imitate.  Nothing is ever written back.

Standard library only.  No configuration file.  Exit codes: 0 clean, 1 alert,
2 error.
"""

import argparse
import bisect
import json
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# Static knowledge tables
# ---------------------------------------------------------------------------

CATEGORY_LABELS = {
    "Lu": "uppercase letter", "Ll": "lowercase letter",
    "Lt": "titlecase letter", "Lm": "modifier letter",
    "Lo": "other letter",
    "Mn": "nonspacing mark", "Mc": "spacing mark", "Me": "enclosing mark",
    "Nd": "decimal digit", "Nl": "letter number", "No": "other number",
    "Pc": "connector punctuation", "Pd": "dash punctuation",
    "Ps": "open punctuation", "Pe": "close punctuation",
    "Pi": "initial punctuation", "Pf": "final punctuation",
    "Po": "other punctuation",
    "Sm": "math symbol", "Sc": "currency symbol",
    "Sk": "modifier symbol", "So": "other symbol",
    "Zs": "space separator", "Zl": "line separator", "Zp": "paragraph separator",
    "Cc": "control", "Cf": "format", "Cs": "surrogate",
    "Co": "private use", "Cn": "unassigned",
}

# Non-overlapping ranges, sorted by first code point for binary search.
_SCRIPT_RANGE_RAW = (
    (0x0041, 0x005A, "Latin"),
    (0x0061, 0x007A, "Latin"),
    (0x00C0, 0x024F, "Latin"),
    (0x0250, 0x02AF, "Latin"),
    (0x1E00, 0x1EFF, "Latin"),
    (0x0370, 0x03FF, "Greek"),
    (0x1F00, 0x1FFF, "Greek"),
    (0x0400, 0x052F, "Cyrillic"),
    (0x2DE0, 0x2DFF, "Cyrillic"),
    (0xA640, 0xA69F, "Cyrillic"),
    (0x0590, 0x05FF, "Hebrew"),
    (0xFB1D, 0xFB4F, "Hebrew"),
    (0x0600, 0x06FF, "Arabic"),
    (0x0750, 0x077F, "Arabic"),
    (0xFB50, 0xFDFF, "Arabic"),
    (0xFE70, 0xFEFF, "Arabic"),
    (0x0900, 0x097F, "Devanagari"),
    (0x0980, 0x09FF, "Bengali"),
    (0x0B80, 0x0BFF, "Tamil"),
    (0x0E00, 0x0E7F, "Thai"),
    (0x10A0, 0x10FF, "Georgian"),
    (0x2D00, 0x2D2F, "Georgian"),
    (0x1100, 0x11FF, "Hangul"),
    (0x3130, 0x318F, "Hangul"),
    (0xAC00, 0xD7AF, "Hangul"),
    (0x3040, 0x309F, "Hiragana"),
    (0x30A0, 0x30FF, "Katakana"),
    (0x31F0, 0x31FF, "Katakana"),
    (0x3400, 0x4DBF, "CJK"),
    (0x4E00, 0x9FFF, "CJK"),
    (0xF900, 0xFAFF, "CJK"),
    (0xFF01, 0xFF5E, "Latin"),       # fullwidth forms imitate Latin
    (0x20000, 0x2FA1F, "CJK"),
)
SCRIPT_RANGES = tuple(sorted(_SCRIPT_RANGE_RAW, key=lambda item: item[0]))
SCRIPT_STARTS = tuple(item[0] for item in SCRIPT_RANGES)

# code point -> (what it imitates, severity)
HOMOGLYPHS = {
    # Cyrillic letters that pass as Latin in most fonts
    0x0410: ("A", "alert"), 0x0415: ("E", "alert"),
    0x041E: ("O", "alert"), 0x0420: ("P", "alert"),
    0x0421: ("C", "alert"), 0x0425: ("X", "alert"),
    0x0430: ("a", "alert"), 0x0435: ("e", "alert"),
    0x043E: ("o", "alert"), 0x0440: ("p", "alert"),
    0x0441: ("c", "alert"), 0x0445: ("x", "alert"),
    0x0456: ("i", "alert"), 0x0458: ("j", "alert"),
    0x044B: ("y", "alert"), 0x0432: ("B", "alert"),
    0x0445: ("x", "alert"),
    # Greek confusables
    0x0391: ("A", "alert"), 0x0392: ("B", "alert"),
    0x0395: ("E", "alert"), 0x0396: ("Z", "alert"),
    0x0397: ("H", "alert"), 0x0399: ("I", "alert"),
    0x039A: ("K", "alert"), 0x039D: ("N", "alert"),
    0x039F: ("O", "alert"), 0x03A1: ("P", "alert"),
    0x03A4: ("T", "alert"), 0x03A5: ("Y", "alert"),
    0x03A7: ("X", "alert"), 0x03BF: ("o", "alert"),
    # spaces that are not ASCII space
    0x00A0: (" ", "alert"), 0x1680: (" ", "alert"),
    0x2000: (" ", "alert"), 0x2001: (" ", "alert"),
    0x2002: (" ", "alert"), 0x2003: (" ", "alert"),
    0x2004: (" ", "alert"), 0x2005: (" ", "alert"),
    0x2006: (" ", "alert"), 0x2007: (" ", "alert"),
    0x2008: (" ", "alert"), 0x2009: (" ", "alert"),
    0x200A: (" ", "alert"), 0x202F: (" ", "alert"),
    0x205F: (" ", "alert"), 0x3000: (" ", "alert"),
    # typography: usually deliberate, so only a notice
    0x2010: ("-", "notice"), 0x2011: ("-", "notice"),
    0x2012: ("-", "notice"), 0x2013: ("-", "notice"),
    0x2014: ("-", "notice"), 0x2212: ("-", "notice"),
    0x2018: ("'", "notice"), 0x2019: ("'", "notice"),
    0x201C: ('"', "notice"), 0x201D: ('"', "notice"),
}

BIDI_CODEPOINTS = frozenset(
    list(range(0x202A, 0x202F)) + list(range(0x2066, 0x206A))
)
ZERO_WIDTH_CODEPOINTS = frozenset((0x200B, 0x200C, 0x200D, 0xFEFF, 0x2060, 0x180E))
ASCII_CONTROL_OK = frozenset((0x09, 0x0A, 0x0D))


# ---------------------------------------------------------------------------
# Per-character classification
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CharClass:
    """What one character actually is."""

    category: str
    name: str
    script: str
    lookalike: str
    reasons: tuple
    severity: str          # ok / notice / alert


def script_of(ch):
    """Return a script name for ch, using a sorted range table and bisect."""
    cp = ord(ch)
    i = bisect.bisect_right(SCRIPT_STARTS, cp) - 1
    if i >= 0 and cp <= SCRIPT_RANGES[i][1]:
        return SCRIPT_RANGES[i][2]
    category = unicodedata.category(ch)
    if category[0] in ("N", "P", "S", "Z") or category in ("Cc", "Cf"):
        return "Common"
    return "Unknown"


@lru_cache(maxsize=4096)
def classify(ch):
    """Classify a single character.  Cached because input repeats characters."""
    cp = ord(ch)
    category = unicodedata.category(ch)
    name = unicodedata.name(ch, "")
    if not name:
        name = "<no Unicode name>"
    script = script_of(ch)
    reasons = []
    severities = []

    if category == "Cf":
        if cp in BIDI_CODEPOINTS:
            reasons.append("bidirectional control")
        elif cp in ZERO_WIDTH_CODEPOINTS:
            reasons.append("zero-width")
        else:
            reasons.append("format character")
        reasons.append("invisible")
        severities.append("alert")
    elif category == "Cc" and cp not in ASCII_CONTROL_OK:
        reasons.append("control character")
        reasons.append("invisible")
        severities.append("alert")
    elif category in ("Zl", "Zp"):
        reasons.append("non-standard line break")
        severities.append("alert")

    if cp in HOMOGLYPHS:
        lookalike, severity = HOMOGLYPHS[cp]
        reasons.append("looks like %s" % _quote(lookalike))
        severities.append(severity)
    elif 0xFF01 <= cp <= 0xFF5E:
        lookalike = chr(cp - 0xFEE0)
        reasons.append("fullwidth form of %s" % _quote(lookalike))
        severities.append("alert")
    else:
        lookalike = ""

    if "alert" in severities:
        severity = "alert"
    elif severities:
        severity = "notice"
    else:
        severity = "ok"

    return CharClass(category, name, script, lookalike, tuple(reasons), severity)


def _quote(text):
    """Render one character as a readable quoted token."""
    if text == " ":
        return "' ' (space)"
    if text == "'":
        return "\"'\""
    return "'%s'" % text


def cp_label(ch):
    """Canonical U+XXXX label for a character."""
    return "U+%04X" % ord(ch)


def display(ch):
    """A printable token for a character, even when it is invisible."""
    if ch.isprintable() and not unicodedata.category(ch).startswith("C"):
        return ch
    return "\\u%04X" % ord(ch)


# ---------------------------------------------------------------------------
# Whole-text report
# ---------------------------------------------------------------------------

@dataclass
class SuspiciousEntry:
    """All occurrences of one unusual code point."""

    ch: str
    info: CharClass
    count: int = 0
    locations: list = field(default_factory=list)

    @property
    def label(self):
        return cp_label(self.ch)

    def first_location(self):
        return self.locations[0] if self.locations else (0, 0)


@dataclass
class Report:
    """The complete result of reading one source."""

    source: str
    total_chars: int
    total_lines: int
    distinct: int
    categories: list                  # list of (code, count)
    category_examples: dict           # code -> list of (ch, count)
    scripts: list                     # list of (name, count)
    suspicious: list                  # list of SuspiciousEntry
    suspicious_occurrences: int
    alert_occurrences: int
    text: str

    @property
    def has_alert(self):
        return self.alert_occurrences > 0


def analyze(text, source="<stdin>"):
    """Build a Report from decoded text."""
    category_counts = Counter()
    category_chars = {}
    script_counts = Counter()
    suspicious = {}
    total_lines = 0
    line = 1
    col = 1

    for ch in text:
        info = classify(ch)
        category_counts[info.category] += 1
        chars_seen = category_chars.setdefault(info.category, Counter())
        chars_seen[ch] += 1
        script_counts[info.script] += 1

        if info.severity != "ok":
            entry = suspicious.get(ch)
            if entry is None:
                entry = SuspiciousEntry(ch=ch, info=info)
                suspicious[ch] = entry
            entry.count += 1
            if len(entry.locations) < 5:
                entry.locations.append((line, col))

        col += 1
        if ch == "\n":
            line += 1
            col = 1

    total_lines = text.count("\n") + 1 if text else 0

    categories = sorted(category_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    examples = {}
    for code, _ in categories:
        seen = category_chars[code]
        top = sorted(seen.items(), key=lambda kv: (-kv[1], ord(kv[0])))[:5]
        examples[code] = top
    scripts = sorted(script_counts.items(), key=lambda kv: (-kv[1], kv[0]))

    ordered = sorted(
        suspicious.values(),
        key=lambda e: (
            0 if e.info.severity == "alert" else 1,
            -e.count,
            ord(e.ch),
        ),
    )
    suspicious_occurrences = sum(e.count for e in ordered)
    alert_occurrences = sum(e.count for e in ordered if e.info.severity == "alert")

    return Report(
        source=source,
        total_chars=len(text),
        total_lines=total_lines,
        distinct=len(set(text)),
        categories=categories,
        category_examples=examples,
        scripts=scripts,
        suspicious=ordered,
        suspicious_occurrences=suspicious_occurrences,
        alert_occurrences=alert_occurrences,
        text=text,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _examples_text(items):
    parts = []
    for ch, count in items:
        token = display(ch)
        parts.append(token if count == 1 else "%s×%d" % (token, count))
    return " ".join(parts)


def render_text(report, show_scripts=False):
    """Render the human-readable report."""
    lines = []
    lines.append("== charscope: %s ==" % report.source)
    lines.append(
        "chars: %d   lines: %d   distinct: %d"
        % (report.total_chars, report.total_lines, report.distinct)
    )
    lines.append("")

    lines.append("Category breakdown")
    for code, count in report.categories:
        pct = 100.0 * count / report.total_chars if report.total_chars else 0.0
        label = CATEGORY_LABELS.get(code, code)
        lines.append(
            "  %-3s %-22s %6d  %5.1f%%  %s"
            % (code, label, count, pct, _examples_text(report.category_examples[code]))
        )
    lines.append("")

    if show_scripts:
        lines.append("Script breakdown")
        for name, count in report.scripts:
            pct = 100.0 * count / report.total_chars if report.total_chars else 0.0
            lines.append("  %-12s %6d  %5.1f%%" % (name, count, pct))
        lines.append("")

    if report.suspicious:
        lines.append(
            "Unusual characters (%d distinct, %d occurrences, %d alerts)"
            % (len(report.suspicious), report.suspicious_occurrences,
               report.alert_occurrences)
        )
        for entry in report.suspicious:
            line_no, col_no = entry.first_location()
            more = "" if entry.count == 1 else "  (+%d more)" % (entry.count - 1)
            reason_text = "; ".join(entry.info.reasons)
            lines.append(
                "  L%d:C%-3d %s  %-30s %-3s  [%s] %s%s"
                % (line_no, col_no, entry.label, entry.info.name,
                   entry.info.category, entry.info.severity, reason_text, more)
            )
        lines.append("")
    else:
        lines.append("Unusual characters: none")
        lines.append("")

    lines.append(
        "Verdict: %s" % ("alert" if report.has_alert else "clean")
    )
    return "\n".join(lines)


def render_json(report):
    """Render a machine-readable report."""
    data = {
        "source": report.source,
        "chars": report.total_chars,
        "lines": report.total_lines,
        "distinct": report.distinct,
        "categories": [
            {
                "code": code,
                "label": CATEGORY_LABELS.get(code, code),
                "count": count,
                "percent": round(
                    100.0 * count / report.total_chars, 2
                ) if report.total_chars else 0.0,
                "examples": [
                    {"char": ch, "label": cp_label(ch), "count": n}
                    for ch, n in report.category_examples[code]
                ],
            }
            for code, count in report.categories
        ],
        "scripts": [
            {"name": name, "count": count} for name, count in report.scripts
        ],
        "suspicious": [
            {
                "codepoint": entry.label,
                "char": entry.ch,
                "name": entry.info.name,
                "category": entry.info.category,
                "script": entry.info.script,
                "severity": entry.info.severity,
                "reasons": list(entry.info.reasons),
                "count": entry.count,
                "locations": [
                    {"line": ln, "column": col} for ln, col in entry.locations
                ],
            }
            for entry in report.suspicious
        ],
        "suspicious_occurrences": report.suspicious_occurrences,
        "alert_occurrences": report.alert_occurrences,
        "verdict": "alert" if report.has_alert else "clean",
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def render_explain():
    """Describe the rules the tool applies."""
    return "\n".join([
        "== charscope: classification rules ==",
        "",
        "1. Unicode general category comes from the interpreter's character database.",
        "   Category labels are looked up in a fixed table, never guessed from shape.",
        "2. Script is found by binary search over sorted code point ranges.",
        "   Characters outside every range are Common when they are punctuation,",
        "   digits, symbols or separators, and Unknown otherwise.",
        "3. A character is unusual when it is invisible or imitates another one.",
        "   Format characters, non-ASCII control characters and line/paragraph",
        "   separators are always alerts. Tab, LF and CR are ordinary controls.",
        "4. Directional controls and zero-width characters are marked by name.",
        "   Both can change how text is displayed without changing its bytes.",
        "5. Known lookalikes are matched by code point, not by pixel shape.",
        "   Cyrillic and Greek letters, non-ASCII spaces and fullwidth forms are",
        "   alerts; typographic dashes and quotes are notices.",
        "6. Severity is the highest severity among the reasons for one character.",
        "   Only alerts affect the verdict and the exit code.",
        "7. Occurrences are grouped by code point; up to five positions are kept.",
        "   Reading is read-only: no source file is ever modified.",
    ])


def render_find(report, spec):
    """Show every occurrence matching a category code or a U+ code point."""
    spec = spec.strip()
    matches = []
    if spec.upper().startswith("U+"):
        try:
            target = chr(int(spec[2:], 16))
        except (ValueError, OverflowError):
            return "error: bad code point %r (use U+200B form)" % spec, 2
        for index, ch in enumerate(report.text):
            if ch == target:
                matches.append((index, ch))
    else:
        wanted = next(
            (code for code in CATEGORY_LABELS if code.upper() == spec.upper()),
            None,
        )
        if wanted is None:
            return "error: unknown category %r" % spec, 2
        for index, ch in enumerate(report.text):
            if classify(ch).category == wanted:
                matches.append((index, ch))

    lines = []
    lines.append("== charscope: find %s in %s ==" % (spec, report.source))
    lines.append("matches: %d" % len(matches))
    shown = matches[:500]
    for index, ch in shown:
        info = classify(ch)
        line_no = report.text.count("\n", 0, index) + 1
        last_nl = report.text.rfind("\n", 0, index)
        col_no = index - last_nl
        lines.append(
            "  L%d:C%-3d %s  %-30s %-3s  %s"
            % (line_no, col_no, cp_label(ch), info.name, info.category,
               "; ".join(info.reasons) if info.reasons else "-")
        )
    if len(matches) > len(shown):
        lines.append("  ... %d more (showing first 500)" % (len(matches) - len(shown)))
    return "\n".join(lines), 0


# ---------------------------------------------------------------------------
# Input and command line
# ---------------------------------------------------------------------------

def read_text(path):
    """Read one file as UTF-8, stripping a leading byte order mark."""
    with open(path, "rb") as handle:
        raw = handle.read()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(
            "%s: not valid UTF-8 at byte %d" % (path, exc.start)
        ) from exc


def build_parser():
    parser = argparse.ArgumentParser(
        prog="charscope",
        description="See exactly which characters are in a text file.",
    )
    parser.add_argument("files", nargs="*", metavar="FILE",
                        help="text file(s); reads standard input when omitted")
    parser.add_argument("--json", action="store_true",
                        help="emit a machine-readable JSON report")
    parser.add_argument("--scripts", action="store_true",
                        help="include the script distribution")
    parser.add_argument("--invisible", action="store_true",
                        help="only list unusual characters")
    parser.add_argument("--find", metavar="SPEC",
                        help="list occurrences of a category (Cf) or code point (U+200B)")
    parser.add_argument("--explain", action="store_true",
                        help="print the classification rules and exit")
    parser.add_argument("--version", action="version", version="charscope " + __version__)
    return parser


def main(argv=None):
    """Command line entry point.  Returns an exit status."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.explain:
        sys.stdout.write(render_explain() + "\n")
        return 0

    if args.json and args.find:
        sys.stderr.write("error: --json and --find cannot be combined\n")
        return 2

    try:
        if args.files:
            chunks = []
            for path in args.files:
                chunks.append(read_text(path))
            text = "\n".join(chunks)
            source = ", ".join(args.files)
        else:
            raw = sys.stdin.buffer.read()
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                sys.stderr.write("error: stdin is not valid UTF-8 at byte %d\n" % exc.start)
                return 2
            source = "<stdin>"
    except (OSError, ValueError) as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 2

    report = analyze(text, source=source)

    if args.find:
        output, status = render_find(report, args.find)
        sys.stdout.write(output + "\n")
        return status

    if args.json:
        sys.stdout.write(render_json(report) + "\n")
    elif args.invisible:
        subset = Report(
            source=report.source,
            total_chars=report.total_chars,
            total_lines=report.total_lines,
            distinct=report.distinct,
            categories=report.categories,
            category_examples=report.category_examples,
            scripts=report.scripts,
            suspicious=report.suspicious,
            suspicious_occurrences=report.suspicious_occurrences,
            alert_occurrences=report.alert_occurrences,
            text=report.text,
        )
        sys.stdout.write(render_invisible(subset) + "\n")
    else:
        sys.stdout.write(render_text(report, show_scripts=args.scripts) + "\n")

    return 1 if report.has_alert else 0


def render_invisible(report):
    """A terse listing of only the unusual characters."""
    lines = ["== charscope: unusual characters in %s ==" % report.source]
    if not report.suspicious:
        lines.append("none")
        return "\n".join(lines)
    for entry in report.suspicious:
        line_no, col_no = entry.first_location()
        lines.append(
            "  L%d:C%-3d %s  %-30s  [%s]  %s  (%d occurrence%s)"
            % (line_no, col_no, entry.label, entry.info.name,
               entry.info.severity, "; ".join(entry.info.reasons),
               entry.count, "" if entry.count == 1 else "s")
        )
    return "\n".join(lines)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    except AttributeError:
        pass
    sys.exit(main())
