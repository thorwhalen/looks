"""What the ffmpeg on *this* machine actually is, and what it can actually do.

Two questions, two authorities, and they are not interchangeable:

- **What licence does this binary carry?** ``ffmpeg -L``. Nothing else.
- **Which filters does it have?** ``ffmpeg -filters``. Nothing else.

Both of those sentences are load-bearing, and both were established by
measurement rather than by reading documentation.

``ffmpeg -L`` prints a licence statement produced by a compile-time ``#if``
cascade in ``fftools/opt_common.c``. That matters because the more obvious
source — the ``configuration:`` line in ``ffmpeg -version`` — is *editable by
whoever built the binary*, and at least one widely-installed wheel does edit
the licence conclusion out of it. PyAV's bundled FFmpeg patches ``configure``
to move ``libx264``/``libx265`` out of ``EXTERNAL_LIBRARY_GPL_LIST``, so its
``avutil_license()`` reports "LGPL version 3 or later" while ``otool -L`` shows
GPL ``libx264`` and ``libx265`` actually linked. A licence check that trusts a
self-report is not a check; ``-L``'s cascade is the least-editable statement a
binary makes about itself, and even it is only evidence, not proof.

``ffmpeg -h filter=NAME`` looks like a capability probe and is not one: on
ffmpeg 8.1 an unknown filter prints ``Unknown filter 'x'.`` and then, verbatim,
``Exiting with exit code 0``. Every filter would test as present. So
availability comes from parsing the ``-filters`` table.

And the rule that ties them together: **anything this module cannot determine
is reported as unknown, and unknown is a refusal upstream.** A build whose
licence line matches nothing known is not "probably LGPL"; it is unknown. The
functions here never guess and never raise on a merely-absent ffmpeg — they
return a :class:`FfmpegEnv` that says so, because a caller diagnosing a missing
binary needs a value it can inspect, not a traceback.

**There is not one ffmpeg on a machine, and the difference is not a version
number.** Measured on this one: ``PATH`` carries ffmpeg 8.1, GPL-**3**, 481
filters; the binary `imageio-ffmpeg` ships inside site-packages is ffmpeg 7.1,
GPL-**2**, 484 filters — and the two filter sets are **non-nested**. Only PATH
has ``colordetect``, ``premultiply_dynamic``, ``transpose_vt``,
``yadif_videotoolbox``; only the bundled one has ``ass``, ``drawtext``, ``pp``,
``subtitles``, ``vidstabdetect``, ``vidstabtransform``, ``zscale``. So neither
"the ffmpeg version" nor "the ffmpeg licence" is a single fact about a machine.

The rule that follows is the important one: **a caller passes the environment
in; nothing downstream may call** :func:`probe` **for itself.** A compiled Look
is valid against *one* :class:`FfmpegEnv`, not against a machine, and a
component that probes on its own behalf silently binds to whichever binary
happened to be first on ``PATH`` — which, for anything invoked through moviepy,
is not the one the user is looking at.

Nothing here executes a filter, decodes a frame, or writes a file. It runs
``ffmpeg`` three times with no input and parses text.

    >>> env = probe()                       # doctest: +SKIP
    >>> env.licence                         # doctest: +SKIP
    <Licence.GPL3: 'gpl3'>
    >>> env.has_filter('lut3d')             # doctest: +SKIP
    True
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Optional, Sequence

from looks._run import run

#: How long any single probe subprocess may take. Generous: these are trivial
#: commands, so exceeding it means something is wrong (a network filesystem, a
#: binary that hangs on a missing dylib) and we would rather say "unknown" than
#: block a caller forever.
DFLT_PROBE_TIMEOUT_S = 20.0

#: The default binary name, looked up on ``PATH``.
DFLT_FFMPEG = "ffmpeg"

#: Where the committed gate table lives, relative to this package.
GATES_PATH = Path(__file__).with_name("data") / "ffmpeg_gates.json"


class Licence(Enum):
    """What licence an ffmpeg build carries, as ``ffmpeg -L`` reports it.

    Ordered from most to least permissive by :data:`LICENCE_ORDER`. ``UNKNOWN``
    is deliberately *not* on that ladder: it is not a position between two
    others, it is the absence of a position, and it must refuse rather than
    compare.
    """

    LGPL21 = "lgpl2.1"
    LGPL3 = "lgpl3"
    GPL2 = "gpl2"
    GPL3 = "gpl3"
    NONFREE = "nonfree"
    UNKNOWN = "unknown"


#: Permissiveness order, most permissive first. :attr:`Licence.UNKNOWN` is
#: absent on purpose — see :class:`Licence`.
LICENCE_ORDER: tuple[Licence, ...] = (
    Licence.LGPL21,
    Licence.LGPL3,
    Licence.GPL2,
    Licence.GPL3,
    Licence.NONFREE,
)

#: Probes against ``ffmpeg -L``'s output, in the order they must be tried:
#: most-restrictive first, because "GPL version 3" contains "GPL version" and a
#: permissive-first scan would match the wrong one. Each pattern is anchored to
#: wording FFmpeg's own ``#if`` cascade emits.
_LICENCE_PROBES: tuple[tuple[re.Pattern, Licence], ...] = (
    (re.compile(r"nonfree and unredistributable", re.I), Licence.NONFREE),
    (re.compile(r"GNU General Public License.*?version 3", re.I | re.S), Licence.GPL3),
    (re.compile(r"GNU General Public License.*?version 2", re.I | re.S), Licence.GPL2),
    (
        re.compile(r"GNU Lesser General Public License.*?version 3", re.I | re.S),
        Licence.LGPL3,
    ),
    (
        re.compile(r"GNU Lesser General Public License.*?version 2\.1", re.I | re.S),
        Licence.LGPL21,
    ),
)

#: A row of ``ffmpeg -filters``: flags, name, io signature, description.
#:
#: The flag column is **two or three** characters, and which one you get depends
#: on the ffmpeg version — a fact worth stating because the legend lies about it.
#: On 8.1 the legend prints three-character patterns (``T.. = Timeline support``)
#: while every row carries two (``' TS aap  AA->A ...'``); older builds carried
#: three (timeline / slice-threading / command support). A parser pinned to
#: either width silently matches nothing on the other, and "nothing" is
#: indistinguishable from "this build has no filters" unless you look.
#:
#: The io-signature column (``V->V``, ``AA->A``, ``|->V``) is what disambiguates
#: a row from the legend lines above it, which have no such column.
_FILTER_ROW = re.compile(
    r"^\s*[TSC.]{2,3}\s+(?P<name>[A-Za-z0-9_]+)\s+[AVN|]+->[AVN|]+\s"
)


@dataclass(frozen=True)
class FfmpegEnv:
    """One machine's ffmpeg, as far as it can be determined without running it.

    Attributes:
        path: Resolved path to the binary, or ``None`` if none was found.
        version: The version string from ``ffmpeg -version``'s first line, or
            ``None``.
        licence: What ``ffmpeg -L`` says. :attr:`Licence.UNKNOWN` whenever the
            output matched nothing known, the binary was absent, or the probe
            failed — three different reasons, one honest answer.
        filters: Every filter name ``ffmpeg -filters`` listed. Empty when the
            probe failed, which is why :attr:`available` exists to tell "no
            filters" apart from "did not look".
        configuration: The raw ``configuration:`` line, kept for diagnostics
            only. **Never** read it to decide a licence — it is editable by the
            builder, which is the whole reason :attr:`licence` comes from
            ``-L``.
        notes: Human-readable reasons anything above is missing.
    """

    path: Optional[str] = None
    version: Optional[str] = None
    licence: Licence = Licence.UNKNOWN
    filters: frozenset[str] = frozenset()
    configuration: Optional[str] = None
    notes: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        """Whether an ffmpeg binary was found and answered at all.

        Distinct from "has no filters": a probe that could not run leaves
        :attr:`filters` empty too, and a caller must be able to tell those
        apart before concluding anything.
        """
        return self.path is not None and bool(self.filters)

    def has_filter(self, name: str) -> bool:
        """Whether ``name`` is in this build's filter table.

        Always ``False`` when the probe did not run — check :attr:`available`
        first if the difference matters to you.

        Examples:
            >>> FfmpegEnv(filters=frozenset({'lut3d'})).has_filter('lut3d')
            True
            >>> FfmpegEnv(filters=frozenset({'lut3d'})).has_filter('eq')
            False
        """
        return name in self.filters

    def missing(self, names: Sequence[str]) -> tuple[str, ...]:
        """Which of ``names`` this build does not have, in the order given.

        Examples:
            >>> env = FfmpegEnv(filters=frozenset({'lut3d', 'curves'}))
            >>> env.missing(['lut3d', 'eq', 'boxblur'])
            ('eq', 'boxblur')
        """
        return tuple(n for n in names if n not in self.filters)


def _ask(argv: Sequence[str], *, timeout: float) -> Optional[str]:
    """Ask ffmpeg one question and return its combined output, or ``None``.

    Goes through :func:`looks._run.run`, the package's single process
    chokepoint, so these calls are covered by the ``-f null -`` invariant like
    every other — they qualify under its environment-question clause, since
    ``-L`` / ``-filters`` / ``-version`` open no input and write no output.

    Never surfaces an environment failure as an exception: a missing binary, a
    timeout or a permission error are facts about the machine that the caller
    wants back as data. A probe that raises turns "I could not determine this"
    into "your program stopped", which is the wrong trade for a diagnostic.
    """
    result = run(argv, timeout=timeout)
    if result.error is not None or result.timed_out:
        return None
    return result.stdout + result.stderr


def parse_licence(text: str) -> Licence:
    """Classify ``ffmpeg -L`` output.

    Most-restrictive-first, because the licence names are prefixes of one
    another: a permissive-first scan matches "GNU General Public License" inside
    the GPLv3 text and reports GPLv2. Anything unmatched is
    :attr:`Licence.UNKNOWN` — never a default, never a guess.

    Examples:
        >>> parse_licence("ffmpeg is free software; ... GNU General Public "
        ...               "License as published by ... either version 3")
        <Licence.GPL3: 'gpl3'>
        >>> parse_licence("... GNU Lesser General Public License ... version 2.1")
        <Licence.LGPL21: 'lgpl2.1'>
        >>> parse_licence("this build is nonfree and unredistributable")
        <Licence.NONFREE: 'nonfree'>
        >>> parse_licence("")
        <Licence.UNKNOWN: 'unknown'>
        >>> parse_licence("Copyright (c) somebody, all rights reserved")
        <Licence.UNKNOWN: 'unknown'>
    """
    for pattern, licence in _LICENCE_PROBES:
        if pattern.search(text):
            return licence
    return Licence.UNKNOWN


def parse_filters(text: str) -> frozenset[str]:
    """Extract filter names from ``ffmpeg -filters`` output.

    The samples below are **verbatim** ffmpeg output, not hand-written — an
    invented sample is a test of the regex against itself, which is how the
    first version of this parser passed its doctests while returning zero
    filters from the real binary.

    Examples:
        Two-character flags, as ffmpeg 8.1 emits them:

        >>> eight = '''Filters:
        ...   T.. = Timeline support
        ...   .S. = Slice threading
        ...   ------
        ...  TS aap               AA->A      Apply Affine Projection algorithm.
        ...  .. abench            A->A       Benchmark part of a filtergraph.
        ...  TS lut3d             V->V       Adjust colors using a 3D LUT.
        ... '''
        >>> sorted(parse_filters(eight))
        ['aap', 'abench', 'lut3d']

        Three-character flags, as older builds emit them:

        >>> six = ' TSC lut3d            V->V       Adjust colors using a 3D LUT.'
        >>> sorted(parse_filters(six))
        ['lut3d']

        The legend lines are rejected because they carry no io signature:

        >>> parse_filters('  T.. = Timeline support')
        frozenset()
    """
    names = set()
    for line in text.splitlines():
        m = _FILTER_ROW.match(line)
        if m:
            names.add(m.group("name"))
    return frozenset(names)


def parse_configuration(text: str) -> Optional[str]:
    """Pull the ``configuration:`` line out of ``ffmpeg -version`` output.

    Diagnostics only. See :attr:`FfmpegEnv.configuration` for why this must
    never decide a licence.

    Examples:
        >>> parse_configuration("ffmpeg version 8.1\\nconfiguration: --enable-gpl\\n")
        '--enable-gpl'
        >>> parse_configuration("ffmpeg version 8.1\\n") is None
        True
    """
    for line in text.splitlines():
        if line.startswith("configuration:"):
            return line[len("configuration:") :].strip()
    return None


def probe(
    ffmpeg: str = DFLT_FFMPEG,
    *,
    timeout: float = DFLT_PROBE_TIMEOUT_S,
) -> FfmpegEnv:
    """Interrogate one ffmpeg binary. Three subprocess calls, no input, no output.

    Returns a :class:`FfmpegEnv` in every case, including when ``ffmpeg`` is not
    installed — the absence of a binary is a fact about the machine, and a
    caller diagnosing it needs a value rather than an exception.

    Args:
        ffmpeg: Binary name (looked up on ``PATH``) or an explicit path.
        timeout: Seconds allowed per probe call.

    Examples:
        >>> env = probe('a-binary-that-does-not-exist')
        >>> env.available
        False
        >>> env.licence
        <Licence.UNKNOWN: 'unknown'>
        >>> env.notes[0]
        "no 'a-binary-that-does-not-exist' on PATH"
    """
    resolved = shutil.which(ffmpeg)
    if resolved is None:
        return FfmpegEnv(notes=(f"no {ffmpeg!r} on PATH",))

    notes: list[str] = []

    licence_out = _ask([resolved, "-hide_banner", "-L"], timeout=timeout)
    if licence_out is None:
        notes.append("`ffmpeg -L` did not run; licence is unknown")
        licence = Licence.UNKNOWN
    else:
        licence = parse_licence(licence_out)
        if licence is Licence.UNKNOWN:
            notes.append("`ffmpeg -L` output matched no known licence statement")

    filters_out = _ask([resolved, "-hide_banner", "-filters"], timeout=timeout)
    if filters_out is None:
        notes.append("`ffmpeg -filters` did not run; no filter is known to exist")
        filters = frozenset()
    else:
        filters = parse_filters(filters_out)
        if not filters:
            notes.append("`ffmpeg -filters` listed nothing")

    version_out = _ask([resolved, "-hide_banner", "-version"], timeout=timeout)
    version = None
    configuration = None
    if version_out:
        first = version_out.splitlines()[0] if version_out.splitlines() else ""
        version = first.strip() or None
        configuration = parse_configuration(version_out)

    return FfmpegEnv(
        path=resolved,
        version=version,
        licence=licence,
        filters=filters,
        configuration=configuration,
        notes=tuple(notes),
    )


@lru_cache(maxsize=None)
def gates() -> Mapping[str, object]:
    """The committed table of FFmpeg's own licence gates, extracted from source.

    **A filter is GPL-gated two ways, and a grep finds only one of them.**
    *Directly*, when its ``_filter_deps`` line contains the literal ``gpl``
    (33 filters, ``eq`` among them). *Indirectly*, when its deps name an
    external library that is itself in ``EXTERNAL_LIBRARY_GPL_LIST`` — enabling
    the filter then forces ``--enable-gpl`` transitively, with no ``gpl`` token
    anywhere on its own line. Five filters are in that second class:
    ``frei0r``, ``frei0r_src``, ``rubberband``, ``vidstabdetect``,
    ``vidstabtransform``.

    Missing them is a **false permission**, which is the dangerous direction:
    ``vidstabtransform`` is stabilisation, i.e. a perfectly plausible
    normalisation effect for this package, and the naive extraction tiers it
    permissive. The first version of this table did exactly that; it was caught
    by an adversarial review rather than by any test, which is why the two
    classes are now stored separately and asserted separately.

    This is what FFmpeg's ``configure`` *declares*, not what the local binary
    *has* — the two answer different questions, and both are needed. The table
    says an effect written with ``eq`` could never run on a clean-room LGPL
    build; :func:`probe` says whether the binary in front of you happens to have
    it. Collapsing them makes every purely-LGPL Look unrunnable on every
    Homebrew ffmpeg on earth, since those are all GPL builds.

    Examples:
        >>> g = gates()
        >>> 'eq' in g['gpl_filters']
        True
        >>> 'geq' in g['gpl_filters']      # relicensed in FFmpeg 4.3
        False
        >>> 'lut3d' in g['gpl_filters']
        False
        >>> 'libx264' in g['external_gpl']
        True
    """
    return json.loads(GATES_PATH.read_text())


def gpl_only_filters() -> frozenset[str]:
    """Filter names FFmpeg gates behind ``--enable-gpl``.

    Examples:
        >>> f = gpl_only_filters()
        >>> {'eq', 'boxblur', 'cropdetect'} <= f
        True
        >>> f & {'lut3d', 'curves', 'colorlevels', 'geq'}
        frozenset()
    """
    return frozenset(gates()["gpl_filters"])  # type: ignore[arg-type]


def needs_gpl(filters: Sequence[str]) -> tuple[str, ...]:
    """Which of ``filters`` exist only in a GPL build, in the order given.

    The point of the package in one function: a chain that reaches for the
    obvious grade filter is not portable to an LGPL build, and nothing in the
    ffmpeg CLI will tell you, because the binary you are holding runs it fine.

    Examples:
        >>> needs_gpl(['scale', 'eq', 'lut3d', 'boxblur'])
        ('eq', 'boxblur')
        >>> needs_gpl(['curves', 'colorlevels', 'lut3d'])
        ()
    """
    gpl = gpl_only_filters()
    return tuple(f for f in filters if f in gpl)
