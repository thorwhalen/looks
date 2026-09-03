"""A `.cube` is a build artifact. This is where it gets built, once.

A 33-cube is ~950 KB; the spec that determines it is ~566 bytes of JSON. So a
Look carries the **spec** and a cache carries the **file**, addressed by a hash
of everything that determines its bytes. Two Looks with the same ramp share one
file; a changed ramp cannot reuse a stale one; and nothing that reaches the
bytes is allowed to bypass the address.

Generating rather than downloading is measured, not assumed: 33³ takes 0.141 s
with nothing but the standard library, which beats a network read and needs no
registry, no credentials and no availability.

## Atomicity is the whole difficulty

This package exists to be fanned out — one process per cut, several at once, all
of them wanting the same LUT. Two of them will race, and the loser must not be
able to hand ffmpeg a half-written file. **A half-written `.cube` is not an
error, it is a silently wrong picture**: ffmpeg reads what is there and
interpolates the rest of the lattice from nothing.

So a write is `mkstemp` in the destination directory plus :func:`os.replace`,
which is atomic on POSIX and on Windows. A deterministic ``<key>.tmp`` path is
**not** good enough — two writers would open the same temp file and interleave
into it, which is the race in a costume rather than a fix.

## What is deliberately absent

No eviction, no size cap, no TTL. A content-addressed store where every entry is
reproducible from its key does not need one: deleting the whole directory is
always safe and always correct, which is a stronger property than any policy
would give. :func:`sweep` exists for a caller who wants that, and says so.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional, Union

from looks.lut import (
    DFLT_CUBE_SIZE,
    DFLT_CUBE_TITLE,
    GradientMap,
    LutError,
    Ramp,
    cube_key,
    cube_text,
)

#: Where cubes land when a caller names no directory. Under the user's cache
#: dir rather than the package or the working directory, because a build
#: artifact belongs to the machine, not to the source tree or to whatever
#: directory a process happened to start in.
DFLT_CACHE_ENV = "LOOKS_CACHE_DIR"

#: The extension every entry carries. Part of the filename rather than the key,
#: so a directory listing is readable and `lut3d=file=` gets what it expects.
CUBE_SUFFIX = ".cube"


class CacheError(LutError):
    """The cache could not produce a usable file."""


def cache_dir(into: Optional[Union[str, Path]] = None) -> Path:
    """Where cubes are kept, resolved in one place.

    ``into`` wins, then ``$LOOKS_CACHE_DIR``, then the platform cache directory.
    The directory is created if absent — a cache that refuses to exist is not a
    cache.
    """
    if into is not None:
        path = Path(into)
    elif os.environ.get(DFLT_CACHE_ENV):
        path = Path(os.environ[DFLT_CACHE_ENV])
    else:
        base = os.environ.get("XDG_CACHE_HOME")
        path = (Path(base) if base else Path.home() / ".cache") / "looks" / "cubes"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(frozen=True)
class Materialised:
    """One cube on disk, and whether this call is what put it there.

    ``hit`` is reported rather than inferred because it is the only way a caller
    can tell a cache that is working from one that is silently regenerating —
    the file is identical either way, and only the clock differs.
    """

    path: Path
    key: str
    hit: bool

    def __fspath__(self) -> str:
        """So it can be handed straight to `open`, `Path`, or a filter string."""
        return str(self.path)

    def __str__(self) -> str:
        return str(self.path)


def cube_file(
    spec: Union[Ramp, GradientMap],
    *,
    size: int = DFLT_CUBE_SIZE,
    title: str = DFLT_CUBE_TITLE,
    into: Optional[Union[str, Path]] = None,
) -> Materialised:
    """Ensure the cube for ``spec`` exists on disk, and say where.

    Idempotent and safe to call concurrently. The second caller finds the file
    the first one wrote; a caller racing another mid-write finds either the
    complete previous file or the complete new one, never a partial.

    Args:
        size: The lattice size. Part of the address — a 17-cube and a 33-cube of
            one ramp are different files.
        title: Written into the file's first line, and therefore into the
            address. See :func:`looks.lut.cube_key`.
        into: The cache directory. Defaults to :func:`cache_dir`.

    Examples:
        >>> import tempfile
        >>> from looks import Ramp
        >>> ramp = Ramp.from_hex([(8.2, '#2E0C18'), (100.0, '#FEF0DC')])
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     first = cube_file(ramp, size=9, into=tmp)
        ...     again = cube_file(ramp, size=9, into=tmp)
        ...     (first.hit, again.hit, first.path == again.path)
        (False, True, True)

        It is a path-like, so it goes straight into a filter string:

        >>> import os
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     cube = cube_file(ramp, size=9, into=tmp)
        ...     os.fspath(cube).endswith('.cube')
        True
    """
    key = cube_key(spec, size=size, title=title)
    directory = cache_dir(into)
    path = directory / f"{key}{CUBE_SUFFIX}"
    if path.exists():
        return Materialised(path=path, key=key, hit=True)

    text = cube_text(spec, size=size, title=title)
    # mkstemp in the DESTINATION directory: os.replace is only atomic within a
    # filesystem, and a temp dir elsewhere can be on another one. The unique
    # name is what makes two concurrent writers safe — a deterministic
    # "<key>.tmp" would have them interleaving into one file.
    handle, temporary = tempfile.mkstemp(
        dir=directory, prefix=f"{key}.", suffix=".partial"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return Materialised(path=path, key=key, hit=False)


def materialize_many(
    specs, *, size: int = DFLT_CUBE_SIZE, into: Optional[Union[str, Path]] = None
) -> tuple[Materialised, ...]:
    """Materialise several specs into one directory.

    Deduplicates by address on the way, so a set of Looks sharing a ramp
    generates its cube once rather than once per Look.
    """
    seen: dict[str, Materialised] = {}
    out = []
    for spec in specs:
        key = cube_key(spec, size=size)
        if key not in seen:
            seen[key] = cube_file(spec, size=size, into=into)
        out.append(seen[key])
    return tuple(out)


def entries(into: Optional[Union[str, Path]] = None) -> Iterator[Path]:
    """Every cube in the cache. Partial writes in flight are not listed."""
    for path in sorted(cache_dir(into).glob(f"*{CUBE_SUFFIX}")):
        yield path


def sweep(
    into: Optional[Union[str, Path]] = None, *, keep: Optional[set] = None
) -> tuple[Path, ...]:
    """Delete cached cubes, optionally keeping a set of keys. Returns what went.

    There is no eviction policy and this is not one — it is the caller's own
    decision, made explicit. Every entry is reproducible from its key, so
    deleting all of them is always safe; the only cost is regenerating, at
    0.141 s per 33-cube.
    """
    removed = []
    for path in entries(into):
        if keep is not None and path.stem in keep:
            continue
        path.unlink()
        removed.append(path)
    return tuple(removed)


#: The payload key a step uses to say "I need a cube that does not exist yet".
#: A REQUEST, not a path: `compile_look` writes no files, so a compiled plan
#: names the artifact it wants and :func:`materialize` is what supplies it.
PENDING = "cube_request"


def pending(plan) -> tuple[str, ...]:
    """The cube addresses this plan needs and has not been given.

    Empty means the plan is ready to run. This is the question a caller should
    ask before handing a plan to a backend, and it is what
    :func:`looks.ffmpeg.vf` answers with a refusal rather than a guess.
    """
    return tuple(
        step.payload[PENDING]["key"]
        for step in getattr(plan, "steps", ())
        if PENDING in step.payload
    )


def materialize(plan, *, into: Optional[Union[str, Path]] = None):
    """Build every artifact this plan asks for, and return a plan that has them.

    The split this preserves is the reason it is a separate verb rather than
    part of compiling: **`compile_look` starts no process and writes no file**,
    so a plan is pure data that can be hashed, stored, diffed and sent
    somewhere else. Artifacts are what a plan needs to actually *run*, and
    acquiring them is a side effect with a directory, a disk and a race in it.

    Returns a new plan — the input is left alone, because a caller may well
    want to keep the portable one.

    Idempotent: a plan with nothing pending is returned unchanged, and running
    it twice writes nothing the second time.

    Examples:
        >>> import tempfile
        >>> from looks import ClipSpec, Effect, Look, compile_look, probe
        >>> look = Look(steps=(Effect(name='gradient_map', params={
        ...     'stops': [(8.2, '#2E0C18'), (100.0, '#FEF0DC')], 'size': 9}),))
        >>> env = probe()
        >>> clip = ClipSpec(width=64, height=48, fps=10)
        >>> plan = compile_look(look, clip=clip, env=env)
        >>> len(pending(plan))                      # not built yet
        1
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     ready = materialize(plan, into=tmp)
        ...     pending(ready) == () and 'lut3d=file=' in ready.steps[0].payload['filter']
        True
    """
    import dataclasses

    steps = []
    changed = False
    for step in plan.steps:
        request = step.payload.get(PENDING)
        if request is None:
            steps.append(step)
            continue
        built = cube_file(
            _spec_from(request),
            size=request["size"],
            title=request["title"],
            into=into,
        )
        payload = {k: v for k, v in step.payload.items() if k != PENDING}
        payload["filter"] = request["filter_template"].format(
            file=_escaped(os.fspath(built))
        )
        payload["cube"] = os.fspath(built)
        steps.append(dataclasses.replace(step, payload=payload))
        changed = True
    return dataclasses.replace(plan, steps=tuple(steps)) if changed else plan


def _escaped(value: str) -> str:
    from looks.ffmpeg import escape_filter_value

    return escape_filter_value(value)


def _spec_from(request) -> GradientMap:
    """A cube request back into the spec it addresses.

    Rebuilt from the request rather than carried as an object, because a plan is
    serialisable data — a live `GradientMap` in a payload is exactly what stops
    it crossing a process boundary.
    """
    from looks.lut import Accent

    ramp = Ramp.from_hex([tuple(stop) for stop in request["stops"]])
    accent = request.get("accent")
    return GradientMap(
        ramp=ramp,
        accent=Accent(**accent) if accent else None,
        contrast=request.get("contrast", 1.0),
        lift=request.get("lift", 0.0),
    )
