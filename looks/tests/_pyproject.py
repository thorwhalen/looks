"""Read this package's own ``pyproject.toml``, on every Python it claims to run.

``tomllib`` arrived in 3.11 and this package's floor is 3.10. Two of the guards
that matter most read the declaration — the extras-ledger coverage test and the
zero-dependency scan — and on the 3.10 leg one of them **skipped itself** while
the other raised. A licence guard that reports "skipped" on one of the two
interpreters CI runs is the worse of those, because a skip reads as a pass.

So this is a small reader for the shapes this one file actually uses: table
headers, string values, and arrays of strings. It is **not** a TOML parser and
must not be described as one. What makes it trustworthy is not its coverage of
the grammar but :mod:`looks.tests.test_pyproject_reader`, which runs it against
``tomllib`` on every interpreter that has one — over the real file, comparing
every table and every key. The fallback is therefore never trusted, only
checked, and it is checked against the same bytes the 3.10 leg will read.

A value that is neither a string nor an array of strings is returned as its raw
text (``"0"``, ``"true"``). Nothing here reads one, and the cross-check does not
compare them — which is a scope limit, not an oversight.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Union

#: The file. Two levels up from ``looks/tests/``.
PYPROJECT = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"

Value = Union[str, list]

_TABLE = re.compile(r"^\[([^\[\]]+)\]$")
_KEY = re.compile(r"^(\S.*?)\s*=\s*(.*)$")
#: A basic string (escapes honoured) or a literal string (escapes are literal).
_STRING = re.compile(r'"(?:[^"\\]|\\.)*"' + r"|'[^']*'")


def uncommented(line: str) -> str:
    """Drop a ``#`` comment — unless the ``#`` is inside a string.

    Both directions are load-bearing in the real file: a publish marker is
    spelled ``"[skip ci]"``, and a comment two lines above an array says
    "CI's publish job", whose apostrophe would open a string that never closes.

    >>> uncommented('name = "looks"  # the package')
    'name = "looks"'
    >>> uncommented('publish_marker = "[publish]"')
    'publish_marker = "[publish]"'
    >>> uncommented("    # ruff formats Python inside CI's Markdown fences")
    ''
    """
    out: list[str] = []
    quote = None
    i = 0
    while i < len(line):
        c = line[i]
        if quote is None:
            if c == "#":
                break
            if c in "\"'":
                quote = c
        elif c == quote:
            quote = None
        elif c == "\\" and quote == '"' and i + 1 < len(line):
            out.append(c)
            i += 1
            c = line[i]
        out.append(c)
        i += 1
    return "".join(out).rstrip()


def _unquote(token: str) -> str:
    """One quoted token to its value. A literal string keeps its backslashes.

    >>> _unquote('"a\\\\nb"')
    'a\\nb'
    >>> _unquote(r"'a\\nb'")
    'a\\\\nb'
    """
    body = token[1:-1]
    if token.startswith("'"):
        return body
    escapes = {"n": "\n", "t": "\t", "r": "\r"}
    return re.sub(r"\\(.)", lambda m: escapes.get(m.group(1), m.group(1)), body)


def _open_brackets(text: str) -> int:
    """Unclosed ``[`` outside of strings — how a multi-line array is detected.

    Counting them naively would be wrong: ``"[skip ci]"`` is balanced but
    ``"looks[cli]"`` is not, and an extra spelled that way would swallow the
    rest of the file.

    >>> _open_brackets('deps = [')
    1
    >>> _open_brackets('marker = "[skip ci]"')
    0
    >>> _open_brackets('deps = ["looks[cli]"]')
    0
    """
    masked = _STRING.sub("", text)
    return masked.count("[") - masked.count("]")


def _value(text: str) -> Value:
    text = text.strip()
    if text.startswith("["):
        return [_unquote(m.group(0)) for m in _STRING.finditer(text)]
    m = _STRING.match(text)
    if m and m.group(0) == text:
        return _unquote(text)
    return text


def tables(path: Path = PYPROJECT) -> dict[str, dict[str, Value]]:
    """``{table_name: {key: value}}``, table names dotted as they are written.

    A key outside any table lands under ``""``.

    >>> read = tables()
    >>> read["project"]["name"]
    'looks'
    >>> read["project"]["dependencies"]
    []
    >>> sorted(read["project.optional-dependencies"])
    ['cli', 'dev', 'docs']
    """
    result: dict[str, dict[str, Value]] = {"": {}}
    section = ""
    table: str | None = None
    key: str | None = None
    buf = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = uncommented(raw).strip()
        if key is None:
            if not line:
                continue
            header = _TABLE.match(line)
            if header:
                section = header.group(1).strip()
                result.setdefault(section, {})
                continue
            entry = _KEY.match(line)
            if not entry:
                continue
            # A DOTTED key defines a sub-table: `check.linux = "..."` inside
            # [tool.wads.ops.ffmpeg] is [tool.wads.ops.ffmpeg.check] with key
            # `linux`, which is what tomllib reports and therefore what this
            # reader must report. Keeping it as a literal `check.linux` key was
            # a silent disagreement, found by the cross-check test the first
            # time this file grew one.
            path_parts = _key_path(entry.group(1).strip())
            table = ".".join(filter(None, [section, *path_parts[:-1]]))
            key = path_parts[-1]
            result.setdefault(table, {})
            buf = entry.group(2)
        else:
            buf += " " + line
        if _open_brackets(buf) > 0:
            continue
        result[table][key] = _value(buf)
        table = key = None
        buf = ""
    return result


def _key_path(raw: str) -> list[str]:
    """Split a (possibly dotted, possibly quoted) key into its segments.

    A dot inside quotes is part of the name, not a separator.

    >>> _key_path("name")
    ['name']
    >>> _key_path("check.linux")
    ['check', 'linux']
    >>> _key_path('a."b.c".d')
    ['a', 'b.c', 'd']
    """
    parts: list[str] = []
    token = ""
    quote = ""
    for ch in raw:
        if quote:
            if ch == quote:
                quote = ""
            else:
                token += ch
        elif ch in "\"'":
            quote = ch
        elif ch == ".":
            parts.append(token.strip())
            token = ""
        else:
            token += ch
    parts.append(token.strip())
    return [p for p in parts if p != ""] or [raw]


def optional_dependencies(path: Path = PYPROJECT) -> dict[str, list[str]]:
    """The extras, ``{name: [requirement, ...]}``.

    The requirement strings are returned verbatim, version specifier and all, so
    this asserts the shape rather than the pin -- otherwise every pin bump in
    ``pyproject.toml`` breaks a test of the *reader*.

    >>> optional_dependencies()["cli"]  # doctest: +ELLIPSIS
    ['cw...']
    """
    got = tables(path).get("project.optional-dependencies", {})
    return {name: list(specs) for name, specs in got.items()}


def distribution_names(specs) -> set[str]:
    """The distribution named by each requirement, with version and extras cut.

    >>> sorted(distribution_names(["pytest>=7.0", "looks[cli]", "ruff"]))
    ['looks', 'pytest', 'ruff']
    """
    out = set()
    for spec in specs:
        name = re.split(r"[<>=!~;\[\s]", spec, maxsplit=1)[0].strip()
        if name:
            out.add(name)
    return out
