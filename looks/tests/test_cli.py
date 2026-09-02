"""Tests for :mod:`looks.cli`.

The **exit codes** are the contract. A build script gates on `looks check`, so a
refusal that exits 0 is a warning wearing a refusal's clothes — and the two ways
to get that wrong (a clean chain exiting non-zero, a gated one exiting zero) are
both silent.

`cw` is an optional extra, so every test that dispatches skips when it is
absent — from inside the test body, never at module scope.
"""

import importlib.util
import subprocess
import sys

import pytest

from looks import cli

CHAIN_LGPL = ["curves", "colorlevels", "lut3d"]
CHAIN_GATED = ["scale", "eq", "lut3d"]


def _cw_or_skip():
    if importlib.util.find_spec("cw") is None:
        pytest.skip("the CLI extra (`cw`) is not installed")


def run(*args):
    """Run the CLI as a subprocess and return (returncode, stdout+stderr)."""
    p = subprocess.run(
        [sys.executable, "-m", "looks", *args], capture_output=True, text=True
    )
    return p.returncode, p.stdout + p.stderr


class TestTheHeadlineCommand:
    """`looks check` — the one a build script calls."""

    def test_a_gated_filter_is_named_and_exits_non_zero(self):
        _cw_or_skip()
        code, out = run("check", *CHAIN_GATED)
        assert code != 0, "a refusal that exits 0 cannot be gated on"
        assert "eq" in out

    def test_an_lgpl_clean_chain_exits_zero(self):
        _cw_or_skip()
        code, out = run("check", *CHAIN_LGPL)
        assert code == 0, out

    def test_the_refusal_names_the_substitutions(self):
        """A refusal that only says no is the one people remove."""
        _cw_or_skip()
        _, out = run("check", *CHAIN_GATED)
        assert "curves" in out and "colorlevels" in out

    def test_quiet_prints_only_the_names(self):
        """So it pipes: `looks check ... --quiet | xargs ...`"""
        _cw_or_skip()
        code, out = run("check", "--quiet", *CHAIN_GATED)
        assert code != 0
        assert out.strip() == "eq"

    def test_a_typo_is_a_message_and_not_a_traceback(self):
        """A user error should not print a stack trace — and it must still exit
        non-zero, because an unrecognised name is a refusal."""
        _cw_or_skip()
        code, out = run("check", "scale", "eqq")
        assert code != 0
        assert "Traceback" not in out
        assert "eqq" in out

    def test_several_filters_bind_as_several_arguments(self):
        """`cw`'s argh-compatible default reads `list` and nothing else, so
        `filters: Sequence[str]` bound ONE token and reported the rest as
        unrecognised. `main` dispatches under `cw.MODERN`; i2mint/cw#36 is the
        upstream half."""
        _cw_or_skip()
        code, out = run("check", *CHAIN_GATED)
        assert "unrecognized arguments" not in out, out


class TestTheOtherCommands:
    def test_env_reports_the_licence_and_the_filter_count(self):
        _cw_or_skip()
        code, out = run("env")
        assert code == 0, out
        assert "licence" in out and "filters" in out

    def test_place_emits_a_chain(self):
        _cw_or_skip()
        code, out = run("place", "480x850", "1920x1080", "--mode", "fill")
        assert code == 0, out
        assert out.strip().startswith("scale=")

    def test_place_accepts_a_preset_name(self):
        _cw_or_skip()
        code, out = run("place", "1920x1080", "shorts")
        assert code == 0, out

    def test_terms_shows_the_dated_observation(self):
        """The evidence is the point: a tier you cannot check is a label."""
        _cw_or_skip()
        code, out = run("terms", "ffmpeg")
        assert code == 0, out
        assert "observed" in out and "tier" in out

    def test_unverified_is_reachable(self):
        """What the ledger could NOT verify, printed rather than buried."""
        _cw_or_skip()
        code, out = run("unverified")
        assert code == 0, out
        assert out.strip()

    def test_disclaimer_says_it_is_not_a_legal_conclusion(self):
        _cw_or_skip()
        code, out = run("disclaimer")
        assert code == 0
        assert "not legal conclusions" in out or "not a legal determination" in out


class TestTheCliIsThin:
    """No logic here. A refusal that only fires on the command line is not a
    refusal — every rule must hold for a library caller too."""

    def test_every_command_is_a_thin_adapter(self):
        """Each one imports inside its body and calls the library. The guard is
        crude — a line count — but it fails loudly the day someone starts
        writing policy in a CLI wrapper."""
        import inspect

        for name, fn in cli.COMMANDS.items():
            body = inspect.getsource(fn)
            code = [
                ln for ln in body.splitlines()
                if ln.strip() and not ln.strip().startswith(("#", '"', "'"))
            ]
            assert len(code) < 45, f"{name} is too big to be an adapter"

    def test_importing_looks_does_not_import_cw(self):
        """`cw` is an optional extra, so the library must not reach it."""
        out = subprocess.run(
            [sys.executable, "-c", "import sys, looks; print('cw' in sys.modules)"],
            capture_output=True, text=True,
        )
        assert out.stdout.strip() == "False", out.stdout

    def test_help_does_not_probe_ffmpeg(self):
        """`--help` must answer from the signatures alone. A CLI that shells out
        before printing its own usage is slow for no reason, and it fails on a
        machine with no ffmpeg — which is exactly the machine most likely to be
        reading `--help`."""
        _cw_or_skip()
        code, out = run("--help")
        assert code == 0
        # If a command body had run, its output would be in there.
        assert "licence  :" not in out and "path     :" not in out

    def test_importing_looks_starts_no_process(self):
        """The chokepoint is only reached by a caller who asks for something."""
        probe_src = (
            "import subprocess, sys\n"
            "calls = []\n"
            "subprocess.run = lambda *a, **k: calls.append(a)\n"
            "import looks\n"
            "print(len(calls))\n"
        )
        out = subprocess.run(
            [sys.executable, "-c", probe_src], capture_output=True, text=True
        )
        assert out.stdout.strip() == "0", out.stdout + out.stderr

    def test_the_version_is_not_read_at_import(self):
        """Reading it eagerly cost 50 ms — `importlib.metadata` pulls in
        `email.parser` — for a value most callers never look at. It resolves on
        first access instead (PEP 562), which keeps both the honest version and
        a cheap import."""
        out = subprocess.run(
            [sys.executable, "-c",
             "import sys, looks; print('email.parser' in sys.modules)"],
            capture_output=True, text=True,
        )
        assert out.stdout.strip() == "False", (
            "importing looks pulled in email.parser, so __version__ is being "
            "read eagerly again"
        )

    def test_the_version_still_resolves_on_access(self):
        """Lazy must not mean absent."""
        import looks

        assert looks.__version__
        assert looks.__version__ != "0.0.0+unknown"
