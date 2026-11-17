# charscope

**See exactly which characters are in a text file.**

Text copied from a web page, a PDF or a chat message can look right while being
subtly wrong: a space that is a no-break space, a hyphen that is an em dash, a
Latin `a` that is actually Cyrillic. A hex dump tells you the bytes but not
where they sit or why they matter. `charscope` reads the text once and tells you
what every character really is, where the unusual ones are, and which ones are
worth fixing.

One tool, one job: describe characters. It never rewrites a file.

## Install / run

Single file, Python 3, standard library only. No install step.

```bash
python charscope.py examples/mixed.txt
python charscope.py < some-file.txt          # standard input when no file given
```

## Default report

`examples/mixed.txt` contains a zero-width space inside a key, a no-break space
in a value, a Cyrillic `а` standing in for a Latin `a`, and an em dash in a path:

```bash
python charscope.py examples/mixed.txt
```

```
== charscope: examples/mixed.txt ==
chars: 55   lines: 4   distinct: 33

Category breakdown
  Ll  lowercase letter           28   50.9%  p×4 e×3 t×3 a×2 h×2
  Lu  uppercase letter           10   18.2%  C×2 E×2 A K M
  Zs  space separator             7   12.7%   ×6 \u00A0
  Cc  control                     3    5.5%  \u000A×3
  Sm  math symbol                 3    5.5%  =×3
  Cf  format                      1    1.8%  \u200B
  Nd  decimal digit               1    1.8%  2
  Pd  dash punctuation            1    1.8%  —
  Po  other punctuation           1    1.8%  :

Unusual characters (4 distinct, 4 occurrences, 3 alerts)
  L1:C15  U+00A0  NO-BREAK SPACE                 Zs   [alert] looks like ' ' (space)
  L2:C2   U+0430  CYRILLIC SMALL LETTER A        Ll   [alert] looks like 'a'
  L1:C4   U+200B  ZERO WIDTH SPACE               Cf   [alert] zero-width; invisible
  L3:C10  U+2014  EM DASH                        Pd   [notice] looks like '-'

Verdict: alert
```

Exit status is `1` here: three characters are alerts. The em dash is only a
notice — usually deliberate typography, so it does not fail a CI check.

## Views

```bash
python charscope.py --scripts examples/mixed.txt       # add script distribution
python charscope.py --invisible examples/mixed.txt     # only unusual characters
python charscope.py --find U+200B examples/mixed.txt   # every one code point
python charscope.py --find Cf examples/mixed.txt       # every format character
python charscope.py --json examples/mixed.txt          # machine-readable report
python charscope.py --explain                          # print the rules
```

`--find U+200B` output:

```
== charscope: find U+200B in examples/mixed.txt ==
matches: 1
  L1:C4   U+200B  ZERO WIDTH SPACE               Cf   zero-width; invisible
```

`--invisible` output:

```
== charscope: unusual characters in examples/mixed.txt ==
  L1:C15  U+00A0  NO-BREAK SPACE                  [alert]  looks like ' ' (space)  (1 occurrence)
  L2:C2   U+0430  CYRILLIC SMALL LETTER A         [alert]  looks like 'a'  (1 occurrence)
  L1:C4   U+200B  ZERO WIDTH SPACE                [alert]  zero-width; invisible  (1 occurrence)
  L3:C10  U+2014  EM DASH                         [notice]  looks like '-'  (1 occurrence)
```

`--json` emits one object with `chars`, `lines`, `distinct`, a `categories` list,
a `scripts` list, a `suspicious` list (each with `codepoint`, `severity`,
`reasons`, `count` and `locations`), and a `verdict`.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Read completed, no alert-level characters (notices may still be listed) |
| 1 | Read completed, at least one alert-level character |
| 2 | Bad input: file not found, invalid UTF-8, or an invalid `--find` argument |

## Multiple files

Paths are joined in order with one newline between them, so positions refer to
the combined stream:

```bash
python charscope.py examples/clean.txt examples/mixed.txt
```

## Design choices

- **Category and name come from the interpreter's Unicode database**, not from
  a hand-written character list. The tool decides what a character *is* using
  the same table Python uses.
- **Script is a sorted range table searched by binary search.** That keeps the
  lookup in a handful of comparisons per distinct character and needs no data
  files. Characters outside every range become `Common` when they are digits,
  punctuation, symbols or separators, and `Unknown` otherwise.
- **Lookalikes are matched by code point, never by rendered shape.** Deciding
  similarity from pixels would depend on the installed font. A fixed map of
  confusable Cyrillic, Greek, space and fullwidth code points is deterministic
  and testable.
- **Two severities keep signal high.** Invisible controls, cross-script
  letters and non-ASCII spaces are alerts; typographic dashes and quotes are
  notices. Only alerts change the exit code, so the tool can guard CI without
  rejecting ordinary prose.
- **Occurrences are grouped by code point with up to five positions each.** A
  file with ten thousand zero-width spaces produces one readable line, not ten
  thousand.
- **Classification is memoised per character.** Real text has a small alphabet,
  so a 400,000-character file classifies a few dozen distinct values and reuses
  the results.

## Tests

```bash
python -m unittest discover -s tests
```

126 tests cover script ranges and boundaries, every reason for an unusual
character, grouping and line/column positions, all output formats, exit codes,
file and standard-input reading, and the command line.

## License

MIT. See [LICENSE](LICENSE).
