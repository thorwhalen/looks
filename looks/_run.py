"""The single place ``looks`` starts a process — and the invariant it enforces.

    **Every ffmpeg process ``looks`` starts ends in ``-f null -``.**

That sentence is the boundary between this package and the one it must not
become. It admits every measurement, every probe and every diagnostic. It
excludes — structurally, not by convention — every render, every encode, every
mux, every concat, and therefore ``looks.render()``, which cannot be written
without violating it.

The kickoff states the rule in prose: a convenience ``looks.render(clip, look)``
*will* get used and *will* rebuild one big ``-filter_complex``, undoing the
bounded-memory invariant `muvid.footage.assemble` won after 30-cut OOM kills on
a 3.7 GB box. Prose does not survive contact with a future contributor who has
a good reason. This does, because it is checkable two ways: a test that
intercepts :func:`run` and asserts the argv of every invocation, and a grep over
the package for encoder flags.

**The invariant is only enforceable because there is exactly one chokepoint.**
Every subprocess in ``looks`` goes through :func:`run`. A module that calls
``subprocess`` directly has left the perimeter, and
``looks/tests/test_invariant.py`` fails on it.

Three shapes are permitted, and nothing else:

- ``ffmpeg …  -f null -`` — analysis. Frames are decoded, filters run, and the
  output is discarded. This is how a probe measures what an effect *does*
  without producing anything.
- ``ffprobe …`` — inspection. ffprobe cannot write media at all, so it needs no
  terminator; the constraint is structural in the binary rather than in the
  argv.
- ``ffmpeg … -version`` / ``-L`` / ``-filters`` / ``-buildconf`` — the
  environment probe. No input, no output, no decoding.

A caller that wants pixels on disk takes the compiled chain from ``looks`` and
runs it themselves. That is the whole architecture in one sentence.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Optional, Sequence

#: How long any single analysis call may take before it is abandoned. Probes are
#: short by construction (a handful of frames), so exceeding this means
#: something is wrong rather than slow.
DFLT_TIMEOUT_S = 120.0

#: The argv tail that makes an ffmpeg invocation an analysis rather than a
#: render. ``-f null -`` selects the null muxer writing to stdout, so every
#: frame is decoded and filtered and none is encoded or stored.
NULL_SINK: tuple[str, ...] = ("-f", "null", "-")

#: ffmpeg options that ask a question and exit without touching media. An
#: invocation whose argv contains one of these needs no null sink.
INFO_FLAGS = frozenset(
    {"-version", "-L", "-filters", "-buildconf", "-h", "-formats", "-codecs"}
)


class InvariantViolation(AssertionError):
    """An attempt to start a process that would produce media.

    Deliberately an :class:`AssertionError` rather than a ``ValueError``: this
    is not a bad argument a caller might reasonably pass and recover from, it is
    a statement that the package has stopped being what it claims to be.
    """


@dataclass(frozen=True)
class Completed:
    """The result of one analysis call.

    Attributes:
        argv: Exactly what was run, kept so a caller can report or reproduce it.
        returncode: The process's exit status.
        stdout: Captured standard output.
        stderr: Captured standard error — where ffmpeg puts everything
            interesting, including filter metadata.
        timed_out: Whether the call was abandoned at :data:`DFLT_TIMEOUT_S`.
        error: A description when the process could not be started at all.
    """

    argv: tuple[str, ...]
    returncode: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        """Whether the process ran and exited zero.

        Examples:
            >>> Completed(argv=('ffprobe',), returncode=0).ok
            True
            >>> Completed(argv=('ffprobe',), returncode=1).ok
            False
            >>> Completed(argv=('ffprobe',), error='not found').ok
            False
        """
        return self.error is None and not self.timed_out and self.returncode == 0


def _binary(argv: Sequence[str]) -> str:
    """The bare binary name, ignoring any directory it was found in."""
    head = argv[0] if argv else ""
    return head.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]


def check_analysis_only(argv: Sequence[str]) -> None:
    """Raise unless ``argv`` is one of the three permitted shapes.

    This is the invariant, as a function. It is called by :func:`run` on every
    invocation, so violating it requires bypassing the chokepoint entirely —
    which is what the perimeter test looks for.

    Examples:
        An analysis call terminated by the null sink is fine:

        >>> check_analysis_only(['ffmpeg', '-i', 'a.mp4', '-vf', 'lut3d=x.cube',
        ...                      '-f', 'null', '-'])

        ffprobe needs no terminator — it cannot write media:

        >>> check_analysis_only(['ffprobe', '-show_entries', 'frame_tags=lavfi.blur'])

        So does an environment question:

        >>> check_analysis_only(['ffmpeg', '-hide_banner', '-L'])

        A render is refused, and the message says what the rule is:

        >>> check_analysis_only(['ffmpeg', '-i', 'a.mp4', 'out.mp4'])
        Traceback (most recent call last):
        ...
        looks._run.InvariantViolation: looks starts no process that can produce
        media...

        So is a render dressed as an analysis — the sink has to be the *tail*,
        because ffmpeg takes the last output specification, and an earlier
        ``-f null`` would be overridden by a later real one:

        >>> check_analysis_only(['ffmpeg', '-i', 'a.mp4', '-f', 'null', '-',
        ...                      'sneaky.mp4'])
        Traceback (most recent call last):
        ...
        looks._run.InvariantViolation: looks starts no process that can produce
        media...

        A binary that is neither ffmpeg nor ffprobe is refused outright:

        >>> check_analysis_only(['python', '-c', 'print(1)'])
        Traceback (most recent call last):
        ...
        looks._run.InvariantViolation: looks starts only ffmpeg and ffprobe, not
        'python'
    """
    if not argv:
        raise InvariantViolation("looks starts no process with an empty argv")

    name = _binary(argv)
    if name.startswith("ffprobe"):
        return
    if not name.startswith("ffmpeg"):
        raise InvariantViolation(f"looks starts only ffmpeg and ffprobe, not {name!r}")
    if INFO_FLAGS.intersection(argv):
        return
    if tuple(argv[-3:]) == NULL_SINK:
        return
    raise InvariantViolation(
        "looks starts no process that can produce media: an ffmpeg call must "
        "end in `-f null -` (analysis) or ask an environment question. Got:\n"
        f"    {' '.join(argv)}\n"
        "If you want pixels on disk, take the compiled chain from looks and run "
        "it yourself — that is the architecture, not an inconvenience. See "
        "looks/_run.py."
    )


def run(
    argv: Sequence[str],
    *,
    timeout: float = DFLT_TIMEOUT_S,
) -> Completed:
    """Start one analysis process, after checking the invariant.

    Never raises for an environment reason — a missing binary, a timeout or a
    permission error are facts about the machine that the caller wants back as
    data. It **does** raise :class:`InvariantViolation`, because that is a fact
    about *this package* and there is nothing to recover from.

    Examples:
        >>> run(['ffmpeg', '-i', 'x.mp4', 'out.mp4'])
        Traceback (most recent call last):
        ...
        looks._run.InvariantViolation: looks starts no process that can produce
        media...

        >>> run(['ffprobe-that-does-not-exist']).error is not None
        True
    """
    argv = list(argv)
    check_analysis_only(argv)
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        return Completed(argv=tuple(argv), timed_out=True, error="timed out")
    except (OSError, subprocess.SubprocessError) as e:
        return Completed(argv=tuple(argv), error=f"{type(e).__name__}: {e}")
    return Completed(
        argv=tuple(argv),
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )
