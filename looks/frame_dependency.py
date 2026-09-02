"""Can this effect flicker? Answered by measurement, not by judgement.

The flagship look's central claim is that it is *frame-independent by
construction* — one fixed LUT, no temporal state — so it **cannot** flicker,
which is the failure mode of every per-frame palette quantiser and of the
non-commercial cartoon models. That claim is worth something only if it can be
checked, and it turns out to reduce to **two ffmpeg probes and a comparison**.

Two questions, two probes, and each isolates one hazard:

1. **Does the effect vary with time?** Apply it to a *looped still* and diff
   consecutive output frames. A constant input can only produce a changing
   output if the effect reads the clock or the frame index. Measured: `noise`
   with the `t` flag moves 82–85/255; `lut3d`, `curves`, `gblur`, `deband` and
   `noise` *without* `t` move 0.

2. **Does the effect adapt to frame content?** Apply it to a source whose
   *left half is constant* while its *right half changes*, then look only at the
   left half. A content-independent effect leaves it alone; one that adapts to
   global statistics changes it, because the statistics moved. Measured:
   `normalize` moves the constant half by **219/255**; `lut3d`, `curves`,
   `gblur` move 0.

Question 2 is the one that matters. **A content-adaptive effect flickers** —
its output for an unchanged pixel depends on what else is in the frame, so a
pixel that never moves still shimmers as the shot changes around it.

## Three things this probe gets wrong if you build it naively

Each cost a false reading before it was fixed, and each fails **silently**.

- **The varying half must actually move the statistic the effect adapts to,
  and no single source moves them all.** This is the deepest limitation here,
  and it is measured rather than theorised. A first version used `testsrc2`,
  which always spans the full luma range and therefore never moves a min/max —
  `normalize` read **0**, a false negative saying "cannot flicker" about an
  effect that can. A *fading* half moves the range and `normalize` jumps to
  **219**. But the fade leaves the colour histogram nearly alone, so `elbg` — a
  vector quantiser, adaptive by definition — still read **0**. A *hue-cycling*
  half moves the histogram and catches `elbg` at 5–8 — while missing
  `normalize` entirely, because it does not move the range.

  So **two** content probes run and the verdict is the larger. The pair is not
  provably complete: an effect adapting to a statistic neither probe moves
  reads independent. See *What this does not answer*.
- **Chroma subsampling bleeds across the seam.** In `yuv420p` a chroma sample
  is shared between the constant and varying halves, so the boundary column
  changes for reasons that have nothing to do with the effect. `yuv444p` plus a
  margin removes it.
- **`tblend=difference` of identical frames is not zero in RGB.** Black in
  limited-range YUV is 16, so a difference computed in RGB and then measured by
  `signalstats` reads 16 everywhere. Filters that need RGB (`lut3d`, `curves`)
  force that conversion, so the format is pinned on **both** sides of the
  effect under test.

## What this does not answer

**Some temporal filters.** A third probe (below) catches the common case by
running two sequences that differ only *before* a shared textured tail:
`tmix=frames=3` shows **146**/255 in the tail and `hqdn3d` shows 2. But
`tblend` and `atadenoise` both read **0** and are misreported as independent.
Measured, and the reason is structural rather than a tuning failure: `tblend`
consumes two input frames per output frame, so the trim that skips the
perturbation for a normal filter lands *past* it; `atadenoise` keeps nine
frames of history, more than a short probe can perturb. Lengthening the
perturbation from one frame to three changed neither — verified.

Those two are refused for an unrelated and stronger reason anyway: **every
temporal filter is out of scope**, because the execution model this package
serves renders one bounded ffmpeg *per cut*, so a temporal filter meets a hard
discontinuity at every cut. Do not read that as making the gap harmless —
it means the gap is not currently load-bearing, not that it is closed.

**And an `INDEPENDENT` verdict is evidence, not proof.** It says: none of three
probes could make this effect change a pixel it should not have touched. An
effect adapting to a statistic none of them moves would pass, and so would
`tblend`.
That is why the flagship look's claim does **not** rest on this module — a
fixed per-pixel lookup with no state cannot depend on anything else, which is a
*structural* argument, and the measurement corroborates it rather than
substituting for it. Use :func:`classify` to catch an effect that flickers; do
not use it to certify one that does not, unless you also have the structural
argument.

Every process here goes through :mod:`looks._run`, and every one is an
``ffprobe`` reading filter metadata — no pixel ever leaves ffmpeg, so the
``-f null -`` invariant is preserved by construction rather than by care.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from looks._run import run

#: Probe geometry. Small on purpose — the classification is about *whether* a
#: value changes, not by how much, so resolution buys nothing and costs time.
PROBE_SIZE = (32, 64)
PROBE_RATE = 5
PROBE_DURATION = 1.0

#: How far in from the seam the constant half is sampled, in pixels.
#:
#: A spatial effect legitimately reads pixels near the boundary, so without a
#: margin every blur reads as content-adaptive. The margin cannot be made large
#: enough for *every* spatial effect — a Gaussian's support runs to about 3
#: sigma, so `gblur=sigma=4` crosses 8 px and `sigma=10` would cross any margin
#: this probe can afford.
#:
#: That residual error is **conservative**: an over-wide spatial filter is
#: reported as `CONTENT_ADAPTIVE`, i.e. "can flicker" about something that
#: cannot. For a refusal engine that is the safe direction — the unsafe one is
#: calling an adaptive effect independent. Widen the margin (and the probe) if a
#: specific broad filter needs a correct verdict.
SEAM_MARGIN = 12

#: A difference at or below this (out of 255) is treated as no change.
#: Not zero: a filter that round-trips through another pixel format can move a
#: value by one without depending on anything.
NOISE_FLOOR = 1


class Dependency(Enum):
    """What an effect's output depends on, worst case.

    Ordered by how badly each behaves across a cut:

    - :attr:`INDEPENDENT` — the same input pixel gives the same output pixel,
      always. Cannot flicker. This is what the flagship look is.
    - :attr:`INDEPENDENT` — no probe could make the effect touch a pixel it
      should not have. **Evidence, not proof** — see the module docstring.
      A pixel-local map and a small spatial filter both land here, and for the
      flicker question that is the right grouping: neither can flicker.
    - :attr:`TIME_VARYING` — output depends on the frame index or clock.
      Deterministic and reproducible, but it changes: film grain is the wanted
      case.
    - :attr:`CONTENT_ADAPTIVE` — output depends on the frame's global
      statistics. **This flickers**, and it is the class the whole
      frame-independence argument is about.
    - :attr:`TEMPORAL` — output at frame *n* depends on frames before it.
      Structurally incompatible with the execution model this package serves:
      the consumer renders one bounded ffmpeg **per cut**, so a temporal filter
      meets a hard discontinuity at every cut and produces an artefact at every
      one of them.
    - :attr:`NONDETERMINISTIC` — two applications of the effect to the SAME
      input disagree. A reproducibility hazard rather than a flicker one: a
      re-render produces a different picture. Detected first, because it
      invalidates every other probe here.
    - :attr:`UNDETERMINED` — a probe could not run. Never a synonym for
      independent.
    """

    INDEPENDENT = "independent"
    NONDETERMINISTIC = "nondeterministic"
    TIME_VARYING = "time_varying"
    CONTENT_ADAPTIVE = "content_adaptive"
    TEMPORAL = "temporal"
    UNDETERMINED = "undetermined"


#: Convenience alias for the value that means "no answer".
UNDETERMINED = Dependency.UNDETERMINED

#: The classes that cannot produce flicker.
FLICKER_FREE = frozenset({Dependency.INDEPENDENT})

#: How many frames the determinism probe examines.
#:
#: **Eight, and the number is measured rather than chosen.** Detecting
#: randomness is itself probabilistic: two runs of a stochastic filter can
#: agree by chance, and the more frames you compare the less likely that is
#: across all of them. On `elbg` (a vector quantiser whose default `seed=-1`
#: re-randomises every instantiation), six repeats of the probe detected the
#: non-determinism in **1 of 6** runs at three frames and **6 of 6** at eight.
#: Fifteen was no better than eight, so eight is where it saturates.
#:
#: A consequence worth stating: a `NONDETERMINISTIC` verdict is a proof, but its
#: absence is not. An effect random on one pixel in ten thousand would pass.
DETERMINISM_PROBE_FRAMES = 8

#: How many frames of the shared tail the temporal probe examines.
#:
#: Small on purpose, and this is the subtle part: the probe only detects a
#: temporal effect if the frames it samples still have the perturbation inside
#: their memory window. Trimming further in makes every temporal filter read as
#: independent — measured, `tmix=frames=3` read 0 when sampling began 3 frames
#: after the perturbation and 146/255 when it began 1 frame after.
TEMPORAL_PROBE_FRAMES = 3


@dataclass(frozen=True)
class DependencyReport:
    """What the two probes measured, and what follows from it.

    Attributes:
        dependency: The verdict.
        time_delta: Largest change between consecutive output frames on a
            constant input, out of 255.
        content_delta: Largest change in the constant half when the rest of the
            frame changed, out of 255.
        temporal_delta: Largest change in a shared tail when the frames BEFORE
            it differed, out of 255.
        determinism_delta: Largest disagreement between two applications of the
            effect to the SAME input, out of 255. Nonzero means the effect is
            random, and every other number in this report is then meaningless.
        can_flicker: Whether the verdict admits flicker. ``None`` when
            undetermined — **not** ``False``, because "we could not tell" and
            "it cannot" are different answers and only one of them is a
            guarantee.
        note: Why, when something could not be measured.
    """

    dependency: Dependency
    time_delta: Optional[float] = None
    content_delta: Optional[float] = None
    temporal_delta: Optional[float] = None
    determinism_delta: Optional[float] = None
    note: str = ""

    @property
    def can_flicker(self) -> Optional[bool]:
        if self.dependency is Dependency.UNDETERMINED:
            return None
        return self.dependency not in FLICKER_FREE


def _max_luma_delta(
    source: str, chain: str, *, ffprobe: str, timeout: float
) -> Optional[float]:
    """Largest ``signalstats`` YMAX over a filter graph's frames, or ``None``."""
    result = run(
        [
            ffprobe,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"{source},{chain}",
            "-show_entries",
            "frame_tags=lavfi.signalstats.YMAX",
            "-of",
            "csv=p=0",
        ],
        timeout=timeout,
    )
    if not result.ok:
        return None
    values = []
    for line in result.stdout.splitlines():
        token = line.strip().rstrip(",")
        if token:
            try:
                values.append(float(token))
            except ValueError:
                continue
    # The first frame has nothing to difference against, so tblend emits it
    # unchanged; including it would report the picture rather than the delta.
    return max(values[1:], default=None) if len(values) > 1 else None


def _still_source() -> str:
    w, h = PROBE_SIZE
    return f"color=c=gray:s={w}x{h}:r={PROBE_RATE}:d={PROBE_DURATION}"


def _split_sources() -> tuple[str, ...]:
    """Constant left half; right halves that each move a DIFFERENT statistic.

    Two, because neither is enough. The fading half moves the luma range and
    catches ``normalize`` (219/255) while missing ``elbg`` entirely; the
    hue-cycling half moves the colour histogram and catches ``elbg`` (5-8)
    while missing ``normalize``. Both measured.

    Adding a source here strictly increases sensitivity and can only turn an
    ``INDEPENDENT`` verdict into ``CONTENT_ADAPTIVE``, never the reverse — so
    it is a safe extension, and the right response to discovering an effect
    that slipped through.
    """
    w, h = PROBE_SIZE
    const = f"color=c=gray:s={w}x{h}:r={PROBE_RATE}:d={PROBE_DURATION}"
    return (
        # moves the luma range
        f"{const}[l];"
        f"color=c=white:s={w}x{h}:r={PROBE_RATE}:d={PROBE_DURATION},"
        f"fade=t=out:st=0:d={PROBE_DURATION}[r];[l][r]hstack",
        # moves the colour histogram
        f"{const}[l];"
        f"testsrc2=s={w}x{h}:r={PROBE_RATE}:d={PROBE_DURATION},hue=h=90*t[r];"
        f"[l][r]hstack",
    )


def _determinism_probe(chain: str) -> str:
    """A graph that applies ``chain`` twice to the SAME frames and diffs them.

    **This must run before the others**, because every other probe here compares
    two applications of the effect — so a random effect makes them differ for a
    reason that has nothing to do with what is being tested. Measured: `elbg`
    with its default ``seed=-1`` disagrees with itself by **70/255**, and the
    temporal probe consequently reported it TEMPORAL, which it is not. With
    ``seed=1`` it disagrees by 0.

    A non-deterministic effect is a *reproducibility* hazard rather than a
    flicker one: the same Look over the same clip produces a different picture
    on a re-render, which defeats a content-addressed cache and makes a golden
    test impossible.
    """
    w, h = PROBE_SIZE
    return (
        f"testsrc2=s={w}x{h}:r={PROBE_RATE}:d={DETERMINISM_PROBE_FRAMES / PROBE_RATE},"
        f"format=yuv444p,split[x][y];"
        f"[x]{chain},format=yuv444p[a];[y]{chain},format=yuv444p[b];"
        f"[a][b]blend=all_mode=difference,signalstats"
    )


def _temporal_probe(chain: str) -> str:
    """A graph whose two branches differ ONLY before a shared, textured tail.

    A stateless or spatial effect produces the identical tail for both. One that
    reads earlier frames does not — its output in the tail still carries the
    perturbation.

    Two construction details, each of which silently defeats the probe:

    - **The tail must be textured.** With flat colour, `hqdn3d` has nothing to
      denoise and reads 0 — a false negative for a spatio-temporal filter.
    - **The sampled frames must still have the perturbation in their memory
      window.** Measured: `tmix=frames=3` reads **146**/255 when sampling starts
      one frame after the perturbation and **0** when it starts three frames
      after. Trimming further in makes every temporal filter look independent.
    """
    w, h = PROBE_SIZE
    lead = f"s={w}x{h}:r={PROBE_RATE}:d=0.2"
    tail = f"testsrc2=s={w}x{h}:r={PROBE_RATE}:d=1.2"
    trim = (
        f"trim=start_frame=1:end_frame={1 + TEMPORAL_PROBE_FRAMES},setpts=PTS-STARTPTS"
    )
    branch = f"format=yuv444p,{chain},format=yuv444p,{trim}"
    return (
        f"color=c=black:{lead}[a0];{tail}[a1];[a0][a1]concat=n=2:v=1:a=0,{branch}[A];"
        f"color=c=white:{lead}[b0];{tail}[b1];[b0][b1]concat=n=2:v=1:a=0,{branch}[B];"
        f"[A][B]blend=all_mode=difference,signalstats"
    )


def classify(
    chain: str,
    *,
    ffprobe: str = "ffprobe",
    timeout: float = 120.0,
) -> DependencyReport:
    """Measure what ``chain`` depends on.

    Args:
        chain: An ffmpeg filter chain, as it would appear in ``-vf``.
        ffprobe: Binary name or path.
        timeout: Seconds per probe.

    Examples:
        >>> classify('lut3d=look.cube').dependency        # doctest: +SKIP
        <Dependency.INDEPENDENT: 'independent'>
        >>> classify('normalize').can_flicker             # doctest: +SKIP
        True
    """
    # `format` is pinned on BOTH sides: an effect that needs RGB otherwise
    # leaves tblend computing in RGB, where black is 0 but reads as 16 once
    # signalstats converts it, so every effect would look time-varying.
    fixed = f"format=yuv444p,{chain},format=yuv444p"
    w, h = PROBE_SIZE

    # FIRST, and the ordering is load-bearing: every probe below compares two
    # applications of the effect, so a random one makes them differ for reasons
    # unrelated to what is being measured.
    determinism_delta: Optional[float] = None
    result = run(
        [
            ffprobe,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            _determinism_probe(chain),
            "-show_entries",
            "frame_tags=lavfi.signalstats.YMAX",
            "-of",
            "csv=p=0",
        ],
        timeout=timeout,
    )
    if result.ok:
        vals = []
        for line in result.stdout.splitlines():
            tok = line.strip().rstrip(",")
            if tok:
                try:
                    vals.append(float(tok))
                except ValueError:
                    continue
        determinism_delta = max(vals) if vals else None
    if determinism_delta is None:
        return DependencyReport(
            dependency=Dependency.UNDETERMINED,
            note=f"the determinism probe did not run for {chain!r}",
        )
    if determinism_delta > NOISE_FLOOR:
        return DependencyReport(
            dependency=Dependency.NONDETERMINISTIC,
            determinism_delta=determinism_delta,
            note=(
                f"{chain!r} disagrees with itself by {determinism_delta}/255 on "
                f"identical input, so no other measurement here would mean "
                f"anything. Pin its seed if it has one."
            ),
        )

    time_delta = _max_luma_delta(
        _still_source(),
        f"{fixed},tblend=all_mode=difference,signalstats",
        ffprobe=ffprobe,
        timeout=timeout,
    )
    if time_delta is None:
        return DependencyReport(
            dependency=Dependency.UNDETERMINED,
            note=f"the time probe did not run for {chain!r}",
        )

    keep = w - SEAM_MARGIN
    tail = f"{fixed},crop={keep}:{h}:0:0,tblend=all_mode=difference,signalstats"
    deltas = [
        _max_luma_delta(source, tail, ffprobe=ffprobe, timeout=timeout)
        for source in _split_sources()
    ]
    if any(d is None for d in deltas):
        return DependencyReport(
            dependency=Dependency.UNDETERMINED,
            time_delta=time_delta,
            note=f"a content probe did not run for {chain!r}",
        )
    # The LARGER of the two: each source moves a different statistic, and an
    # effect only has to adapt to one of them to flicker.
    content_delta = max(deltas)

    # The third probe: does the output depend on EARLIER frames? Neither probe
    # above separates this — a looped still through a frame-averager is still
    # constant, and so is the constant half.
    result = run(
        [
            ffprobe,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            _temporal_probe(f"{chain}"),
            "-show_entries",
            "frame_tags=lavfi.signalstats.YMAX",
            "-of",
            "csv=p=0",
        ],
        timeout=timeout,
    )
    temporal_delta: Optional[float] = None
    if result.ok:
        values = []
        for line in result.stdout.splitlines():
            token = line.strip().rstrip(",")
            if token:
                try:
                    values.append(float(token))
                except ValueError:
                    continue
        temporal_delta = max(values) if values else None
    if temporal_delta is None:
        return DependencyReport(
            dependency=Dependency.UNDETERMINED,
            time_delta=time_delta,
            content_delta=content_delta,
            note=(
                f"the temporal probe did not run for {chain!r} — a filter that "
                f"changes the frame count (tblend, framestep) breaks its trim "
                f"indices, and that is itself a sign of temporal behaviour"
            ),
        )

    if time_delta > NOISE_FLOOR:
        verdict = Dependency.TIME_VARYING
    elif temporal_delta > NOISE_FLOOR:
        verdict = Dependency.TEMPORAL
    elif content_delta > NOISE_FLOOR:
        verdict = Dependency.CONTENT_ADAPTIVE
    else:
        verdict = Dependency.INDEPENDENT
    return DependencyReport(
        dependency=verdict,
        time_delta=time_delta,
        content_delta=content_delta,
        temporal_delta=temporal_delta,
        determinism_delta=determinism_delta,
    )


def assert_flicker_free(chain: str, **kwargs) -> DependencyReport:
    """Raise unless ``chain`` provably cannot flicker.

    **What a pass means, precisely: three probes could not make this effect
    depend on anything they varied.** It is not a proof of frame independence —
    `tblend` and `atadenoise` pass and are temporal. For an effect whose class
    matters, pair this with the structural argument (a stateless per-pixel
    lookup cannot depend on anything else) or with a declared class this
    function is used to *falsify*.

    An ``UNDETERMINED`` verdict **raises**: "we could not tell" must not be
    reported as "it cannot", which is the same unknown-is-a-refusal rule the
    licence tier follows, applied to the other guarantee this package makes.

    Raises:
        AssertionError: The chain can flicker, or could not be shown not to.
    """
    report = classify(chain, **kwargs)
    if report.dependency is Dependency.UNDETERMINED:
        raise AssertionError(
            f"could not determine whether {chain!r} can flicker"
            + (f": {report.note}" if report.note else "")
            + ". Unknown is not a guarantee."
        )
    if report.can_flicker:
        raise AssertionError(
            f"{chain!r} is {report.dependency.value} "
            f"(time delta {report.time_delta}, content delta "
            f"{report.content_delta} out of 255), so it can flicker across a "
            f"cut: its output for an unchanged pixel depends on what else is "
            f"in the frame."
        )
    return report
