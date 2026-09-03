"""The package's structural safety property, enforced rather than documented.

    **Every ffmpeg process ``looks`` starts ends in ``-f null -``.**

The kickoff states this as prose: a convenience ``looks.render(clip, look)``
*will* get used and *will* rebuild one big ``-filter_complex``, undoing the
bounded-memory invariant `muvid.footage.assemble` won after 30-cut OOM kills on
a 3.7 GB box. That is a 2.3 GB regression, not a style preference.

Prose does not survive a future contributor with a good reason. These tests do.

Two independent guards, deliberately not one:

1. **The chokepoint refuses.** :func:`looks._run.check_analysis_only` rejects
   any argv that could produce media.
2. **Nothing bypasses the chokepoint.** Every module in the package is scanned
   for a direct ``subprocess`` call and for encoder flags. This is the guard
   that matters, because guard 1 protects only the code that goes through it —
   and the way this invariant will actually be broken is by someone importing
   ``subprocess`` and not knowing guard 1 exists.

Guard 2 is the weaker instrument on its own (it is a list of known spellings),
which is why guard 1 is the one with teeth. Neither alone is enough.
"""

import ast
import pathlib

import pytest

from looks import _run
from looks._run import InvariantViolation, check_analysis_only, run

PACKAGE_ROOT = pathlib.Path(_run.__file__).parent

#: Modules allowed to import ``subprocess``. Exactly one: the chokepoint. A
#: second entry here is a decision to weaken the invariant and should be argued
#: for in a PR, not added to make a test pass.
SUBPROCESS_ALLOWED = {"_run.py"}

#: Argv fragments that only appear when something is being encoded. Not
#: exhaustive — a list of spellings never is — but every one of these is a
#: definite tell.
ENCODER_TELLS = (
    "-c:v",
    "-vcodec",
    "-crf",
    "-preset",
    "libx264",
    "libx265",
    "-b:v",
    "-movflags",
)


def _python_files():
    return sorted(
        p for p in PACKAGE_ROOT.rglob("*.py") if "tests" not in p.parts
    )


class TestTheChokepointRefuses:
    """Guard 1: an argv that could produce media does not run."""

    def test_a_plain_render_is_refused(self):
        with pytest.raises(InvariantViolation, match="produce media"):
            check_analysis_only(["ffmpeg", "-i", "a.mp4", "out.mp4"])

    def test_a_render_after_a_null_sink_is_refused(self):
        """ffmpeg takes the LAST output specification, so an earlier `-f null`
        followed by a real output is a render. The sink has to be the tail."""
        with pytest.raises(InvariantViolation, match="produce media"):
            check_analysis_only(
                ["ffmpeg", "-i", "a.mp4", "-f", "null", "-", "sneaky.mp4"]
            )

    def test_an_encode_to_a_pipe_is_refused(self):
        """The Que Calor stylizer piped raw frames to a second ffmpeg that
        encoded them. That is exactly the shape `looks` must not grow."""
        with pytest.raises(InvariantViolation, match="produce media"):
            check_analysis_only(
                ["ffmpeg", "-i", "-", "-c:v", "libx264", "-f", "rawvideo", "-"]
            )

    def test_a_foreign_binary_is_refused(self):
        with pytest.raises(InvariantViolation, match="only ffmpeg and ffprobe"):
            check_analysis_only(["python", "-c", "print(1)"])

    def test_an_empty_argv_is_refused(self):
        with pytest.raises(InvariantViolation):
            check_analysis_only([])

    def test_run_itself_enforces_it(self):
        """The check is not something a caller opts into."""
        with pytest.raises(InvariantViolation):
            run(["ffmpeg", "-i", "a.mp4", "out.mp4"])

    @pytest.mark.parametrize(
        "argv",
        [
            ["ffmpeg", "-i", "a.mp4", "-vf", "lut3d=x.cube", "-f", "null", "-"],
            ["ffprobe", "-v", "error", "-show_entries", "stream=width"],
            ["ffmpeg", "-hide_banner", "-L"],
            ["ffmpeg", "-hide_banner", "-filters"],
            ["/opt/homebrew/bin/ffmpeg", "-i", "a.mp4", "-f", "null", "-"],
        ],
    )
    def test_analysis_shapes_are_permitted(self, argv):
        check_analysis_only(argv)


class TestNothingBypassesTheChokepoint:
    """Guard 2: the perimeter. This is the one a future change actually trips."""

    def test_only_the_chokepoint_imports_subprocess(self):
        offenders = []
        for path in _python_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                imported = None
                if isinstance(node, ast.Import):
                    imported = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imported = [node.module or ""]
                if imported and any(
                    m == "subprocess" or m.startswith("subprocess.")
                    for m in imported
                ):
                    if path.name not in SUBPROCESS_ALLOWED:
                        offenders.append(f"{path.relative_to(PACKAGE_ROOT)}:{node.lineno}")
        assert not offenders, (
            "these modules start processes outside the chokepoint, so the "
            f"`-f null -` invariant does not cover them: {offenders}. Route "
            "them through `looks._run.run`, or argue in the PR for adding them "
            "to SUBPROCESS_ALLOWED."
        )

    def test_no_module_names_an_encoder(self):
        offenders = []
        for path in _python_files():
            text = path.read_text()
            for tell in ENCODER_TELLS:
                # The tell may legitimately appear inside a docstring that is
                # explaining why it is forbidden, so require it in a string
                # literal that is not a docstring.
                tree = ast.parse(text, filename=str(path))
                docstrings = {
                    id(ast.get_docstring(n, clean=False))
                    for n in ast.walk(tree)
                    if isinstance(
                        n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                    )
                }
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Constant) or not isinstance(
                        node.value, str
                    ):
                        continue
                    if id(node.value) in docstrings:
                        continue
                    if tell in node.value and path.name not in SUBPROCESS_ALLOWED:
                        offenders.append(
                            f"{path.relative_to(PACKAGE_ROOT)}:{node.lineno} -> {tell!r}"
                        )
        assert not offenders, (
            f"encoder flags found outside the chokepoint: {offenders}. `looks` "
            "does not encode; it emits a chain someone else runs."
        )

    def test_there_is_no_render_function(self):
        """The single most likely way this invariant dies is somebody adding a
        helpful `render()`. Naming it here makes that a deliberate act."""
        import looks

        for name in ("render", "render_clip", "apply", "encode", "write_video"):
            assert not hasattr(looks, name), (
                f"`looks.{name}` exists. If this is deliberate, it needs to "
                f"explain how it does not reintroduce the 2.3 GB "
                f"whole-timeline filtergraph the kickoff measured."
            )


class TestTheGuardItself:
    """A guard nobody checks is a guard that has already stopped working."""

    def test_the_perimeter_scan_sees_every_module(self):
        found = {p.name for p in _python_files()}
        assert "_run.py" in found
        assert "environment.py" in found
        assert len(found) >= 4, f"the scan found only {found} — is the glob right?"

    def test_the_perimeter_scan_would_catch_a_violation(self, tmp_path):
        """Mutation-check the scanner: plant a module that imports subprocess
        and confirm the AST walk finds it. Without this, a scanner that silently
        matched nothing would pass forever."""
        planted = tmp_path / "sneaky.py"
        planted.write_text("import subprocess\nsubprocess.run(['ffmpeg'])\n")
        tree = ast.parse(planted.read_text())
        hits = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Import)
            and any(a.name == "subprocess" for a in n.names)
        ]
        assert hits, "the AST walk does not detect `import subprocess`"


class TestD1TheMultiOutputHole:
    """The hole that defeated the first version of the invariant.

    ffmpeg accepts MULTIPLE outputs, so a check that inspects only the argv
    tail is beaten by appending nine characters. Verified 2026-09-02: this argv
    passed `check_analysis_only` **and wrote a real 6170-byte H.264 file**.
    """

    SMUGGLED = [
        "ffmpeg", "-i", "a.mp4", "-c:v", "libx264", "out.mp4",
        "-map", "0:v", "-f", "null", "-",
    ]

    def test_the_smuggled_render_is_refused(self):
        with pytest.raises(InvariantViolation, match="output specification"):
            check_analysis_only(self.SMUGGLED)

    def test_an_output_after_the_sink_is_refused(self):
        with pytest.raises(InvariantViolation):
            check_analysis_only(
                ["ffmpeg", "-i", "a.mp4", "-f", "null", "-", "sneaky.mp4"]
            )

    def test_the_parser_sees_every_output(self):
        from looks._run import output_specs

        assert output_specs(self.SMUGGLED) == ["libx264", "out.mp4", "-"]
        assert output_specs(["ffmpeg", "-i", "a.mp4", "-f", "null", "-"]) == ["-"]
        assert output_specs(["ffmpeg", "-hide_banner", "-L"]) == []

    def test_an_encoder_option_is_deliberately_unrecognised(self):
        """`-c:v` is absent from VALUE_OPTIONS on purpose: `looks` never
        encodes, so an encoder option appearing at all is evidence something is
        being produced. Adding it to the value list would weaken the check."""
        from looks._run import VALUE_OPTIONS

        for encoder_option in ("-c:v", "-vcodec", "-crf", "-preset", "-b:v"):
            assert encoder_option not in VALUE_OPTIONS

    def test_a_legitimate_analysis_still_passes(self):
        check_analysis_only(
            ["ffmpeg", "-i", "a.mp4", "-vf", "lut3d=x.cube", "-f", "null", "-"]
        )


class TestTheCuratedNamespace:
    """`looks.__all__` is the surface a caller uses, not everything defined."""

    def test_every_exported_name_exists(self):
        import looks

        missing = [n for n in looks.__all__ if not hasattr(looks, n)]
        assert not missing, f"__all__ names that do not exist: {missing}"

    def test_nothing_leaks_beyond_all_and_the_submodules(self):
        """A bare `from looks import *` should not hand out `dataclass`,
        `Optional` or a transitively-imported helper.

        Submodules are allowed and identified **structurally** — anything that
        is a module whose name starts with ``looks.`` — rather than by a list.
        A hardcoded list goes stale the moment a module is added, which is a
        test that fails for the wrong reason; this one fails only when a
        non-module name has escaped.
        """
        import types

        import looks

        public = {n for n in dir(looks) if not n.startswith("_")}
        leaked = sorted(
            n
            for n in public - set(looks.__all__)
            if not (
                isinstance(getattr(looks, n), types.ModuleType)
                and getattr(getattr(looks, n), "__name__", "").startswith("looks")
            )
        )
        assert not leaked, f"names leaked into the namespace: {leaked}"

    def test_the_version_is_read_not_hardcoded(self):
        """CI bumps the version in pyproject.toml on every release, so a literal
        here would silently disagree. Reading from installed metadata also
        SURFACES the drift when an editable install goes stale, rather than
        hiding it behind a plausible-looking constant."""
        import looks

        assert looks.__version__
        assert not looks.__version__.startswith("0.0.0+"), (
            "looks is not installed; run `pip install -e . --no-deps`"
        )

    def test_the_classify_collision_is_resolved_deliberately(self):
        """Two modules define `classify`. At the top level the LICENCE one wins
        the bare name — a caller reaching for `looks.classify` wants the licence
        question — and the frame-dependency one is `classify_dependency`.

        Pinned because a silent re-export order change would swap them, and both
        return an object with a `.verdict`-ish shape, so the mistake would not
        announce itself.
        """
        import looks
        import looks.licence

        assert looks.classify is looks.licence.classify
        assert looks.classify_dependency is looks.frame_dependency.classify

    def test_the_headline_call_works_from_the_top_level(self):
        """The one call the README leads with."""
        import looks

        assert looks.needs_gpl(["scale", "eq", "lut3d"]) == ("eq",)


def test_no_module_doctest_needs_ffmpeg():
    """A doctest that needs a binary is a doctest CI does not run.

    This has now cost two red CI runs on two different modules — `materialize`'s
    example and `pipe_plan`'s — each calling `probe()` and `compile_look`, each
    green locally and each dying on the runner with
    ``CompileError: ... the probed binary is not usable: no 'ffmpeg' on PATH``.
    Documenting the rule did not stop the second one, so here is the rule as a
    mechanism.

    It runs the package's own module doctests in a subprocess whose PATH holds
    no ffmpeg — the CI condition exactly — rather than scanning the source for
    spellings, because the question is whether they RUN, not whether they
    mention a name.

    Tests under ``looks/tests`` are deliberately out of scope: they may and do
    require ffmpeg, and they say so with a skip.

    **What it catches, stated precisely, because the first mutation I wrote to
    check it was not representative and passed.** A bare ``probe()`` is harmless
    — it returns an env with ``available=False`` rather than raising, so a
    doctest may call it freely. What fails on a runner is *acting* on that env:
    ``compile_look(..., env=probe())`` raises ``CompileError`` for any ffmpeg
    step, because an unusable binary is a refusal. Mutation-tested with that
    shape: caught.
    """
    import os
    import pathlib
    import shutil
    import subprocess
    import sys

    import looks

    package = pathlib.Path(looks.__file__).parent
    modules = sorted(
        str(p) for p in package.glob("*.py") if not p.name.startswith("__")
    )
    assert len(modules) > 8, f"expected the package's modules, found {modules}"

    stripped = os.environ.copy()
    kept = [
        d
        for d in stripped.get("PATH", "").split(os.pathsep)
        if d and not shutil.which("ffmpeg", path=d)
    ]
    stripped["PATH"] = os.pathsep.join(kept)
    if shutil.which("ffmpeg", path=stripped["PATH"]):
        pytest.skip("could not construct a PATH without ffmpeg")

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--doctest-modules", "-q", "--no-header",
         "-p", "no:cacheprovider", *modules],
        capture_output=True, text=True, env=stripped, cwd=str(package.parent),
    )
    assert proc.returncode == 0, (
        "a module doctest needs ffmpeg, so CI will not run it:\n"
        + proc.stdout[-2500:]
    )



def _guarded_imports(tree) -> set:
    """Import nodes sitting inside a `try` with an `ImportError` handler.

    Identity, not position: the same import written twice in one file is two
    nodes, and only the guarded one should be excused.
    """
    guarded = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        catches_import = any(
            h.type is not None
            and (
                (isinstance(h.type, ast.Name) and h.type.id in _IMPORT_ERRORS)
                or (
                    isinstance(h.type, ast.Tuple)
                    and any(
                        isinstance(e, ast.Name) and e.id in _IMPORT_ERRORS
                        for e in h.type.elts
                    )
                )
            )
            for h in node.handlers
        )
        if not catches_import:
            continue
        for stmt in node.body:
            for inner in ast.walk(stmt):
                if isinstance(inner, (ast.Import, ast.ImportFrom)):
                    guarded.add(inner)
    return guarded


_IMPORT_ERRORS = {"ImportError", "ModuleNotFoundError", "Exception"}


class TestZeroDependencyIsEnforcedNotDeclared:
    """`looks` declares `dependencies = []`, and that is only true if nothing
    in the package — tests included — imports a third-party module.

    A developer machine in this federation has every sibling package installed,
    so an accidental `from burns import Rect` in a test passes locally and fails
    only in CI, where it reads as a broken package rather than a stray import.
    That happened: three motion tests imported `burns` and went red on 3.10 and
    Windows alike. An AST scan is the cheap way to catch it before the push.
    """

    @staticmethod
    def _declared() -> set:
        """Every distribution this package declares, in any extra.

        DERIVED from pyproject rather than listed here, so adding a dependency
        permits it automatically and removing one starts failing — a hand-kept
        allowlist beside a declaration is a second source of truth that drifts.
        Uses the package's own small reader, which is also what the licence
        guards use on 3.10.
        """
        from looks.tests import _pyproject

        names = set()
        for specs in _pyproject.optional_dependencies().values():
            names |= _pyproject.distribution_names(specs)
        return {n.replace("-", "_") for n in names}

    @staticmethod
    def _stdlib() -> set:
        import sys

        # 3.10 has `sys.stdlib_module_names`; nothing older is supported.
        return set(sys.stdlib_module_names)

    def test_no_module_imports_an_undeclared_package(self):
        allowed = self._stdlib() | self._declared() | {"looks"}
        offenders = []
        scanned = 0
        # TESTS INCLUDED — `_python_files()` excludes them, and the tests are
        # exactly where the stray import was.
        for path in sorted(PACKAGE_ROOT.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            scanned += 1
            guarded = _guarded_imports(tree)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    # A relative import names no package.
                    names = [node.module] if node.level == 0 and node.module else []
                else:
                    continue
                if node in guarded:
                    # `try: import x / except ImportError: pytest.skip(...)` is
                    # the sanctioned pattern for an OPTIONAL cross-check — the
                    # test skips where the package is absent instead of
                    # reddening the run. A bare import has no such fallback and
                    # is what this guard is for.
                    continue
                for name in names:
                    root = name.split(".")[0]
                    if root not in allowed:
                        offenders.append(f"{path.name}:{node.lineno} imports {name}")
        assert not offenders, (
            "`looks` declares no dependencies, so every import must be the "
            "standard library, `looks` itself, or an allowed dev extra. These "
            "pass on a machine that happens to have the package installed and "
            f"fail in CI:\n  " + "\n  ".join(offenders)
        )
        assert scanned > 20, (
            f"the scan only read {scanned} files — it has stopped covering the "
            "package it is supposed to cover"
        )

    def test_the_scan_would_catch_one(self):
        """The positive control. Without it the sweep above proves nothing on
        the day it stops finding files."""
        tree = ast.parse("from burns import Rect\nimport numpy as np\n")
        allowed = self._stdlib() | self._declared() | {"looks"}
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module.split(".")[0])
        assert {n for n in found if n not in allowed} == {"burns", "numpy"}
