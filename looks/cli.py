"""The command line: thin adapters over the library, and no logic of its own.

Every function here converts strings to the library's types, calls one library
function, and returns something printable. **None of them decides anything.**
If a rule lives in this module it is in the wrong place — a CLI is one surface
among several, and a refusal that only fires on the command line is not a
refusal.

Dispatched with `cw <https://pypi.org/project/cw/>`_, which turns a mapping of
functions into an ``argparse`` parser by reading their signatures. Under
``cw.MODERN`` rather than its argh-compatible default, because this package
annotates with ``collections.abc`` interfaces and argh recognises ``list`` and
nothing else — under the default, ``looks check scale eq lut3d`` bound one token
and reported the rest as unrecognised. Reading ``Sequence[str]`` as "several
values" is `i2mint/cw#36 <https://github.com/i2mint/cw/pull/36>`_, contributed
from here.

Two reasons for `cw` rather than the obvious alternatives, and both are this
package's own thesis applied to itself:

- **`argh` is LGPL-3.0**, and its PyPI metadata ``License:`` field is *empty* —
  only the shipped ``COPYING`` / ``COPYING.LESSER`` pair says so. A package that
  refuses a dependency for a licence nobody's tooling can see should not import
  one.
- **`typer` pulls six packages** into a distribution that declares stdlib only.

``cw`` is MIT, declares ``dependencies = []``, and — verified — ``import cw``
pulls in nothing beyond stdlib: its ``argcomplete`` and ``i2`` imports are lazy,
inside the functions that need them. It is an optional extra here regardless,
so ``import looks`` never reaches it.

Everything below is analysis. The ``-f null -`` invariant covers the CLI like
everything else, because it goes through the same chokepoint.

    $ looks check scale eq lut3d
    eq
    $ echo $?
    1
"""

from __future__ import annotations

from typing import Optional, Sequence

DFLT_PROG = "looks"

#: What ``check`` exits with when a filter needs a GPL build. Not 0: the whole
#: point is that a script can gate on it, and a refusal that exits 0 is a
#: warning wearing a refusal's clothes.
EXIT_REFUSED = 1


def env(ffmpeg: str = "ffmpeg") -> str:
    """Report what the ffmpeg on this machine is, and what it may do.

    There is not one ffmpeg on a machine — pass ``--ffmpeg`` to ask a different
    one, e.g. the binary a wheel bundled.
    """
    from looks.environment import probe

    e = probe(ffmpeg)
    if not e.available:
        return "\n".join(
            [f"ffmpeg   : NOT USABLE ({ffmpeg})", *(f"  {n}" for n in e.notes)]
        )
    lines = [
        f"path     : {e.path}",
        f"version  : {e.version}",
        f"licence  : {e.licence.value}   (from `ffmpeg -L`, the only authority)",
        f"filters  : {len(e.filters)}",
    ]
    if e.notes:
        lines += [f"note     : {n}" for n in e.notes]
    return "\n".join(lines)


def check(
    filters: Sequence[str], *, ffmpeg: Optional[str] = None, quiet: bool = False
) -> str:  # noqa: D401
    """Which of these ffmpeg filters exist only in a GPL build?

    The headline. Prints one name per line and **exits non-zero** if any of them
    needs a GPL ffmpeg, so a build script can gate on it.

    An unrecognised filter name **raises** rather than reporting it clean: this
    check is an allowlist-by-absence, so a typo would otherwise be a computed
    false permission.
    """
    from looks.environment import UnknownFilter, needs_gpl, probe

    known = None
    if ffmpeg is not None:
        e = probe(ffmpeg)
        known = e.filters if e.available else None
    try:
        gated = needs_gpl(list(filters), known=known)
    except UnknownFilter as e:
        # A typo is a user error, not a bug: say so in one line rather than
        # showing a stack trace. The exit code stays non-zero — an unrecognised
        # name is a refusal, and a refusal that exits 0 is a warning wearing a
        # refusal's clothes.
        raise SystemExit(str(e)) from None
    if not gated:
        return "" if quiet else "none of these needs a GPL build"
    raise SystemExit(
        ("\n".join(gated))
        if quiet
        else (
            "\n".join(gated)
            + f"\n\n{len(gated)} of {len(filters)} need a GPL ffmpeg build. "
            "LGPL-clean substitutions: curves / lutyuv / colorlevels / "
            "colorbalance / exposure for eq; gblur for boxblur; "
            "atadenoise or removegrain for hqdn3d."
        )
    )


def terms(provider: str) -> str:
    """What is recorded about a provider's licence, and what tier it projects to."""
    from looks.licence import classify, terms_for

    rows = terms_for(provider)
    out = []
    for t in rows:
        a = classify(t)
        tier = a.tier.value if a.tier else f"off-ladder ({a.verdict.value})"
        out.append(f"{t.provider}/{t.component} [{t.realisation}]")
        out.append(f"  spdx     : {t.spdx}")
        out.append(f"  tier     : {tier}")
        out.append(
            f"  coupling : {t.coupling.value}   conveyance: {t.conveyance.value}"
        )
        for ev in t.evidence:
            out.append(f"  observed : {ev.observed_on} by `{ev.method}`")
        if a.advisories:
            out += [f"  advisory : {x}" for x in a.advisories]
        out.append("")
    return "\n".join(out).rstrip()


def place(
    source: str, target: str, *, mode: str = "fit", backdrop: str = "000000"
) -> str:
    """The ffmpeg chain that puts a WxH source into a WxH target.

    ``target`` may be a size (``1920x1080``) or a preset name (``shorts``).
    """
    from looks.geometry import Size, Solid, ffmpeg_chain, placement, social_size

    def size(text: str) -> Size:
        if "x" in text:
            w, h = text.lower().split("x", 1)
            return Size(int(w), int(h))
        return social_size(text)

    chain = ffmpeg_chain(
        placement(size(source), size(target), mode=mode),  # type: ignore[arg-type]
        backdrop=Solid(tuple(int(backdrop[i : i + 2], 16) for i in (0, 2, 4))),  # type: ignore[arg-type]
    )
    return chain or "(no-op: the source is already the target)"


def measure(clip: str, *, vf: str = "", frames: int = 5) -> str:
    """Measure a clip, optionally through a filter chain.

    Supplying ``--vf`` makes it a **post-effect** measurement, which is the one
    that governs a resolver's answer — and the two are deliberately not
    comparable.
    """
    from looks.environment import probe
    from looks.measure import measure as measure_clip

    e = probe()
    version = (e.version or "").split()[2] if e.version else "unknown"
    s = measure_clip(clip, vf=vf, frames=frames, ffmpeg_version=version)
    return "\n".join(
        [
            f"stage      : {s.stage}",
            f"frames     : {s.n_frames}",
            f"sharpness  : {s.sharpness}   ({s.sharpness_unit}, {s.sharpness_space})",
            f"blur       : {s.blur}",
            f"temporal   : {s.temporal_delta}",
            f"saturation : {s.saturation_mean}",
            f"luma       : {s.luma}",
            f"range      : {s.color_range}",
            f"instrument : {s.instrument}",
        ]
    )


def flicker(chain: str) -> str:
    """Can this filter chain flicker? Decided by four probes, not by judgement.

    A verdict of ``independent`` is **evidence, not proof** — see
    :mod:`looks.frame_dependency`.
    """
    from looks.frame_dependency import classify as classify_chain

    r = classify_chain(chain)
    lines = [
        f"verdict     : {r.dependency.value}",
        f"can flicker : {r.can_flicker}",
        f"  determinism delta : {r.determinism_delta}",
        f"  time delta        : {r.time_delta}",
        f"  content delta     : {r.content_delta}",
        f"  temporal delta    : {r.temporal_delta}",
    ]
    if r.note:
        lines.append(f"note        : {r.note}")
    return "\n".join(lines)


def unverified() -> str:
    """What the licence ledger could NOT verify.

    Printed rather than buried, because an unverified claim asserted as fact is
    worse than no claim.
    """
    from looks.licence import unverified_claims

    return "\n".join(f"- {c}" for c in unverified_claims())


def disclaimer() -> str:
    """What a tier is, and what it is not."""
    from looks.licence import DISCLAIMER

    return DISCLAIMER


#: The command table. A callable value is a command; `cw` reads the signatures.
COMMANDS = {
    "env": env,
    "check": check,
    "terms": terms,
    "place": place,
    "measure": measure,
    "flicker": flicker,
    "unverified": unverified,
    "disclaimer": disclaimer,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Dispatch the command table. The entry point for ``looks ...``.

    Raises:
        SystemExit: With a message naming the extra, when `cw` is absent. It is
            an optional dependency: ``import looks`` must stay stdlib-only, so
            the CLI cannot be a hard requirement of the library.
    """
    try:
        import cw
    except ImportError as e:  # pragma: no cover - environment dependent
        raise SystemExit(
            "the looks CLI needs `cw` (MIT, no dependencies): pip install 'looks[cli]'"
        ) from e
    return cw.dispatch(COMMANDS, argv, prog=DFLT_PROG, convention=cw.MODERN)
