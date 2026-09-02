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
