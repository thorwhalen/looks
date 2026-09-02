"""The hand-rolled pyproject reader, checked against the real parser.

:mod:`looks.tests._pyproject` exists because ``tomllib`` is 3.11+ and this
package supports 3.10, so two guards had no reader on the older leg. A
hand-rolled reader is normally a liability — it agrees with the real parser
until the day it quietly does not, and the guards built on it go on reporting
green.

What removes that liability is this file: on every interpreter that HAS
``tomllib`` (which includes one of CI's two legs), the reader is run against it
over the **real** ``pyproject.toml``, comparing every table and every key. So
the reader is never trusted — it is checked, against the same bytes the 3.10 leg
will read, on every single run.

The comparison is deliberately two-directional. Missing a table would make a
guard read an empty declaration and pass vacuously; inventing one would make it
read something nobody wrote.
"""

import pytest

from looks.tests import _pyproject

try:  # pragma: no cover - version dependent
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10
    tomllib = None


def _comparable(value) -> bool:
    """Strings and arrays of strings — the reader's declared scope."""
    if isinstance(value, str):
        return True
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


def _flatten(doc, prefix=""):
    """``tomllib``'s nested dicts, dotted the way the reader names tables."""
    out = {}
    here = {}
    for key, value in doc.items():
        if isinstance(value, dict):
            out.update(_flatten(value, f"{prefix}.{key}" if prefix else key))
        else:
            here[key] = value
    out[prefix] = here
    return out


needs_tomllib = pytest.mark.skipif(
    tomllib is None, reason="no tomllib before 3.11 — this is the leg that checks it"
)


class TestTheReaderAgreesWithTomllib:
    """Over the real file, which is the only file it will ever read."""

    @needs_tomllib
    def test_every_value_tomllib_reports_the_reader_reports_identically(self):
        doc = tomllib.loads(_pyproject.PYPROJECT.read_text(encoding="utf-8"))
        got = _pyproject.tables()
        checked = 0
        for name, keys in _flatten(doc).items():
            for key, value in keys.items():
                if not _comparable(value):
                    continue
                assert name in got, f"the reader missed the table [{name}]"
                assert got[name].get(key) == value, (
                    f"[{name}] {key}: reader read {got[name].get(key)!r}, "
                    f"tomllib read {value!r}"
                )
                checked += 1
        assert checked > 20, (
            f"only {checked} values compared — the cross-check has stopped "
            "covering the file it is supposed to cover"
        )

    @needs_tomllib
    def test_the_reader_invents_no_table(self):
        """The other direction. A table nobody wrote is a declaration nobody
        made, and a guard reading one would be reading fiction."""
        doc = tomllib.loads(_pyproject.PYPROJECT.read_text(encoding="utf-8"))
        expected = set(_flatten(doc)) | {""}
        assert set(_pyproject.tables()) - expected == set()

    @needs_tomllib
    def test_the_two_readings_of_the_extras_are_the_same_object(self):
        """The specific question both consumers ask, asserted directly rather
        than left to follow from the general comparison."""
        doc = tomllib.loads(_pyproject.PYPROJECT.read_text(encoding="utf-8"))
        assert _pyproject.optional_dependencies() == doc["project"].get(
            "optional-dependencies", {}
        )
        assert _pyproject.tables()["project"]["dependencies"] == doc["project"][
            "dependencies"
        ]


class TestTheShapesTheRealFileUses:
    """Pinned separately, because they are the ones that break a naive reader
    and each has a live instance in the file."""

    def test_a_bracket_inside_a_string_does_not_open_an_array(self):
        assert _pyproject._open_brackets('marker = "[skip ci]"') == 0
        assert _pyproject._open_brackets('deps = ["looks[cli]"]') == 0

    def test_an_apostrophe_in_a_comment_does_not_open_a_string(self):
        assert _pyproject.uncommented("  # CI's publish job runs it") == ""
        assert (
            _pyproject.uncommented('  name = "x"  # and CI\'s comment')
            == '  name = "x"'
        )

    def test_a_quoted_key_is_read_unquoted(self):
        """`[tool.ruff.lint.per-file-ignores]` keys are glob strings."""
        ignores = _pyproject.tables()["tool.ruff.lint.per-file-ignores"]
        assert any("tests" in key for key in ignores)
        assert not any(key.startswith('"') for key in ignores)

    def test_a_multiline_array_is_read_whole(self):
        dev = _pyproject.optional_dependencies()["dev"]
        assert len(dev) >= 4 and "cw" in dev
