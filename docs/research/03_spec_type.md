# looks — the core type design: `Effect`, `Look`, and the compiled plan

**2026-09-02** · research note 03 · status: proposal, code verified

## Verdict

Five frozen dataclasses carry the whole design — `Effect` (what you ask for), `Look` (an ordered stack plus a licence ceiling), `ImplRef` (what an implementation declares about itself), `Step` and `LookPlan` (the compiled form) — plus one small type, `Ref`, for a parameter that cannot be known until the clip is measured. The load-bearing decision, from which almost everything else follows, is that **the licence tier is declared by the implementation and never by the request**: an `Effect` has no tier field, a `Look` carries only a *ceiling*, and a tier appears for the first time in a compiled `Step`, copied off the `ImplRef` that was selected. That makes the refusal structural rather than advisory — a caller cannot assert its way past it — and it forces refusal to happen at compile time, which is the only moment at which anything decides what will actually run. The deferred-parameter problem is answered by a separate `resolve(look, probe) -> Look` pass over a pure-data `Ref`, **not** by a callable: a callable would make the Look unpersistable and unhashable, and the Look — not the plan — is the artifact you ship. The cost unit is **CPU-seconds, not dollars**, with falaw's unknown-is-not-zero arithmetic transposed verbatim; measured on this machine the Que Calor look costs 7.25 CPU-seconds per second of output at the shipped settings and 21.14 at the one clip that needed a different flattening scale, and you learn both numbers before a single frame is decoded. The proposed `looks/spec.py` below is stdlib-only, importable, and its 80 doctests pass **strictly** (ELLIPSIS only, no `IGNORE_EXCEPTION_DETAIL`) on Python 3.10.13 and 3.12.12.

---

## 1. What the four ancestors got right, and what each of them paid for

| Ancestor | Got right | Paid for it with |
|---|---|---|
| `falaw.Plan` / `CallPlan` [1] | Frozen · slots · kw_only. Composable by `__add__` with an identity element. Four cost properties that keep *unknown* distinguishable from *zero* (`total_cost_usd`, `known_cost_usd`, `unknown_call_count`, `has_unknown_costs`). `key_extra` for identity beyond the wire arguments. A schema tag on the dict, refused loudly when unrecognised. A canonical blob that **raises** on a value it cannot represent faithfully rather than falling back to `repr`. | `metadata` and `key_extra` as two dicts that look identical and mean opposite things (labelling vs. identity) — a real trap, mitigated only by docstring. `plan_hash` and the per-call cache key deliberately hash *different* projections, which is correct and permanently confusing. The **omit-if-default** sentinel on `backend`/`key_extra` is pure migration machinery: it exists so that every key ever issued stays byte-identical, and it costs a subtle rule forever after. |
| `muvid.visualize.VisualPlan` [2] | The shape `looks` is extracting: ffmpeg input groups + filter chains + an output label, with `register_visual` as an open-closed seam and `resolve_visual` doing the registry lookup *late*, with an error naming the registered set. The escape hatch — a strategy may return a **path to an already-rendered file** — is what lets a non-filtergraph backend plug into the same seam. | It is **not frozen** and it is not serialisable: `still: Path | None` is a filesystem handle inside the spec, `inputs` is a list of lists of argv fragments, and there is no `to_dict`. It is a builder, not a document. It also carries renderer *policy* (`has_cover`, `has_title`) inside the plan, which is how a spec type starts absorbing its consumer. |
| `burns.BurnsPath` [3] | A pure, deterministic `evaluate(t) -> Rect` with no I/O and no frame count — unit-testable without rendering and re-implementable in another language. A `version: int` in the type *and* in `to_dict`. `interp` declared as a field even though only one value is implemented, so richer schemes arrive without a format change. | It accepts a **callable** easing and then refuses at `to_dict` — the honest half-measure, and precisely the shape I reject for parameters below. A callable easing also makes two paths compare unequal for no visible reason and cannot enter any hash. `_ease` is a non-init, non-compare cached field on a frozen dataclass, which works but is the kind of thing that breaks `replace` semantics if anyone forgets. |
| `nw.Transform` [4] | `impl_version` as a **lock, not a receipt** — "same interface, changed behaviour" bumps it without renaming the registry key, and it enters both provenance and the cache identity. `input_kinds`/`output_kind` with registration *refusing* an empty `output_kind`, because a unit of work with no declared output type has unverifiable success. `params_model` on the Protocol rather than only on the base class, so the catalogue, the MCP builder and the CLI can all rely on it. | The lock "only locks what passes through it": a Transform that overrides `execute` must call `stamp_transform_identity` itself, and nothing enforces that. The Protocol is `runtime_checkable`, which compares method *names* and not signatures, so an out-of-date implementation passes `isinstance` and fails at call time. Both are the cost of putting behaviour on the same object as the declaration. |

Three of the four lessons transfer directly, and one does not:

- **Take `falaw`'s cost arithmetic verbatim**, changing only the unit. Unknown is never zero; the sum is a documented lower bound; the count of unknowns is a separate readable number.
- **Take `nw`'s `impl_version`**, but *not* its omit-if-default sentinel. That sentinel is a migration device protecting an installed base of cache keys. `looks` has no installed base, so the sentinel buys nothing and costs a permanent subtlety. Fold `impl_version` unconditionally.
- **Take `burns`'s "the spec never touches I/O"** and go one step further than burns did: refuse the callable outright rather than accepting it and failing at the wire.
- **Take `muvid`'s late registry lookup and its escape hatch**, but freeze the plan and make it serialisable. `VisualPlan` is a builder; `LookPlan` must be a document.

---

## 2. The proposal: `looks/spec.py`

Stdlib-only. 1303 lines including docstrings. Verified: 80 doctests pass under `ELLIPSIS` alone on CPython 3.10.13 and 3.12.12, and `ruff check --select D100` (the repo's only selected rule) is clean.

```python
"""The pure-data core of ``looks``: what a stylization *is*, before anything runs.

Four types and one rule.

- :class:`Effect` — one named operation the caller *asks for*. It never says
  which implementation will serve it, and it never carries a licence tier.
- :class:`Look` — an ordered stack of Effects plus a licence ceiling
  (:attr:`Look.max_tier`). The authoring artifact; the thing you ship.
- :class:`LookPlan` / :class:`Step` — the *compiled* form: exactly which
  implementation runs, at which version, with which fully-resolved parameters,
  at what CPU cost. The analogue of ``falaw.Plan``.
- :class:`Ref` — a parameter that is not known until the clip is measured.

The rule: **the licence tier is a property of the implementation, never of the
request.** A caller who could write ``Effect(..., tier="permissive")`` could
lie, and then the refusal is theatre. So an :class:`Effect` has no tier, a
:class:`Look` has only a *ceiling*, and a tier appears for the first time in a
compiled :class:`Step`, copied from the :class:`ImplRef` that was selected.
Refusal therefore happens at compile time — the moment something decides what
will actually run — and :func:`select_impl` is where it happens.

Nothing in this module executes anything, opens a file, or imports a backend.
It is stdlib-only and side-effect free, which is what lets a Look be inspected,
persisted, diffed and *costed* before a single frame is decoded.

Examples:
    >>> look = Look(
    ...     name="que_calor",
    ...     steps=(
    ...         Effect(name="flatten", params={"scale": Ref("flatten_scale"), "sr": 60}),
    ...         Effect(name="lut3d", params={"cube": "que_calor_b.cube"}),
    ...         Effect(name="posterize", params={"levels": 18}),
    ...     ),
    ... )
    >>> look.max_tier                       # the default ceiling
    <Tier.COPYLEFT_TOOL: 'copyleft-tool'>
    >>> look.is_resolved
    False
    >>> resolved = resolve(look, {"flatten_scale": 0.75})
    >>> resolved[0].params["scale"]
    0.75
    >>> resolved.is_resolved
    True
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Iterator, Mapping, Optional, Sequence

__all__ = [
    "Tier",
    "TIER_ORDER",
    "DFLT_MAX_TIER",
    "Span",
    "ClipSpec",
    "Ref",
    "Effect",
    "Look",
    "ImplRef",
    "Step",
    "LookPlan",
    "resolve",
    "select_impl",
    "look_to_dict",
    "look_from_dict",
    "plan_to_dict",
    "plan_from_dict",
    "look_hash",
    "plan_hash",
    "output_key",
    "LooksError",
    "UnknownEffect",
    "LicenceRefusal",
    "UnresolvedParameter",
    "SpanUnsupported",
    "SchemaError",
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LooksError(Exception):
    """Base of every refusal this package raises."""


class UnknownEffect(LooksError):
    """No registered implementation offers the requested capability."""


class LicenceRefusal(LooksError):
    """Every implementation that *could* run this effect exceeds the ceiling.

    Names each rejected candidate's tier and the exact call that would widen
    the ceiling. This is a refusal, never a warning — see :class:`Tier`.
    """


class UnresolvedParameter(LooksError):
    """A :class:`Ref` parameter reached compile time with nothing to resolve it."""


class SpanUnsupported(LooksError):
    """An :attr:`Effect.at` was given to an implementation that cannot be gated."""


class SchemaError(LooksError):
    """A serialized document carries a tag or version this build cannot read."""


# ---------------------------------------------------------------------------
# The licence ladder
# ---------------------------------------------------------------------------


class Tier(str, Enum):
    """How much licence risk an implementation asks you to accept.

    A **risk ladder**, deliberately not a licence taxonomy: it is a total order,
    so "no worse than this" is one comparison. Mapping real licences onto rungs
    is the licence note's job, not this module's.

    What a tier is *about*, stated so two questions do not get conflated:
    **what running this step causes to execute**, not everything the wheel it
    came from happens to contain. The distinction is not academic — the
    ``opencv-python-headless`` 4.13.0.92 macOS wheel declares ``License: Apache
    2.0`` and ships ``cv2/.dylibs/libx264.164.dylib`` beside a
    ``--enable-gpl``-configured libavcodec. ``pyrMeanShiftFiltering`` never
    enters libavcodec, so a flatten step is ``PERMISSIVE``; what you may
    *redistribute* is a separate ledger, and a separate field the day a second
    consumer for one exists.

    Ordering, most permissive first:

    - ``PERMISSIVE`` — MIT / BSD / Apache-2.0 / ISC / public domain. Vendor,
      link, ship.
    - ``COPYLEFT_TOOL`` — *shells out* to a copyleft binary (a homebrew ffmpeg
      built ``--enable-gpl``). No linking, so no infection of our code; still a
      dependency on a binary you may not redistribute.
    - ``COPYLEFT_LINK`` — would pull copyleft *into our process*. ``av`` and
      ``imageio-ffmpeg`` live here: both wheels ship GPL-built ffmpeg objects
      under permissive package metadata.
    - ``NONCOMMERCIAL`` — CC-BY-NC weights and research licences. AnimeGANv2 and
      White-box Cartoonization, the two most-cited cartoon stylizers, are both
      here, which is why neither can ship.
    - ``UNKNOWN`` — not established. **Strictest of all**, because you cannot
      bound what you have not read. It sorts *above* ``NONCOMMERCIAL`` so the
      ordering alone enforces "unknown is a refusal", with no special case.

    >>> Tier.PERMISSIVE < Tier.COPYLEFT_TOOL < Tier.UNKNOWN
    True
    >>> Tier.COPYLEFT_LINK <= DFLT_MAX_TIER    # `av` refuses by default
    False
    """

    PERMISSIVE = "permissive"
    COPYLEFT_TOOL = "copyleft-tool"
    COPYLEFT_LINK = "copyleft-link"
    NONCOMMERCIAL = "noncommercial"
    UNKNOWN = "unknown"

    @property
    def rank(self) -> int:
        """Position on the ladder; ``0`` is the most permissive."""
        return TIER_ORDER.index(self)

    # `str` already defines all four comparisons (lexicographically), so each
    # one has to be overridden — inheriting even one would compare
    # "copyleft-link" < "copyleft-tool" as strings and get the ladder wrong.
    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Tier):
            return NotImplemented
        return self.rank < other.rank

    def __le__(self, other: object) -> bool:
        if not isinstance(other, Tier):
            return NotImplemented
        return self.rank <= other.rank

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, Tier):
            return NotImplemented
        return self.rank > other.rank

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, Tier):
            return NotImplemented
        return self.rank >= other.rank


TIER_ORDER: tuple[Tier, ...] = (
    Tier.PERMISSIVE,
    Tier.COPYLEFT_TOOL,
    Tier.COPYLEFT_LINK,
    Tier.NONCOMMERCIAL,
    Tier.UNKNOWN,
)
"""The ladder, most permissive first. :attr:`Tier.rank` reads it."""

DFLT_MAX_TIER = Tier.COPYLEFT_TOOL
"""The default ceiling: shelling out to a copyleft binary is fine, linking one
into the process is not. Everything above this rung is opted into explicitly."""


# ---------------------------------------------------------------------------
# Where, and over what
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Span:
    """Where in the clip an effect applies — **never** where a cut is.

    Seconds, relative to the start of the clip the plan is compiled against.
    Floats rather than ``lacing.RationalTime`` for the reason ``an``'s IR uses
    float seconds: a half-frame error in *where a look starts* is imperceptible,
    and the ffmpeg boundary this compiles to (``enable='between(t,a,b)'``)
    speaks seconds anyway. A Look that has to cross into a ``lacing``
    annotation is pinned to a ``TimeInterval`` by the caller, whose provenance
    concern it is.

    ``start=None`` means "from the beginning", ``end=None`` "to the end", so
    ``Span()`` is the whole clip and equivalent to ``at=None``.

    >>> Span(1.0, 4.5).duration_s
    3.5
    >>> Span(1.0, None).duration_s is None
    True
    """

    start: Optional[float] = None
    end: Optional[float] = None

    def __post_init__(self) -> None:
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError(
                f"Span: end must be greater than start, got start={self.start!r} "
                f"end={self.end!r}. A zero-length span is an effect that never "
                "applies; drop the step instead."
            )

    @property
    def duration_s(self) -> Optional[float]:
        """Length in seconds, or ``None`` when either end is open."""
        if self.start is None or self.end is None:
            return None
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class ClipSpec:
    """The clip a plan is compiled *against* — geometry, rate, length.

    Not a file and not bytes: a plan must be buildable without opening anything.
    It is part of a plan's identity because the compiled payload depends on it
    (a ``scale=`` fragment names pixels) and because cost does.

    ``duration_s=None`` is legal and honest — some sources have no reliable
    duration — and it makes the plan's realtime factor unknown rather than zero.

    >>> ClipSpec(1280, 720, 30.0, 10.0).frame_count
    300
    >>> ClipSpec(1280, 720, 30.0).frame_count is None
    True
    >>> round(ClipSpec(1280, 720, 30.0).megapixels, 4)
    0.9216
    """

    width: int
    height: int
    fps: float
    duration_s: Optional[float] = None

    @property
    def megapixels(self) -> float:
        """Frame area in megapixels — the natural scale factor for a cost rate."""
        return self.width * self.height / 1_000_000

    @property
    def frame_count(self) -> Optional[int]:
        """Frames in the whole clip, or ``None`` when the duration is unknown."""
        if self.duration_s is None:
            return None
        return int(round(self.duration_s * self.fps))


# ---------------------------------------------------------------------------
# Deferred parameters
# ---------------------------------------------------------------------------

_NO_DEFAULT = object()

REF_MARKER = "$ref"
"""Reserved key inside a serialized parameter *value*. A parameter whose
legitimate value is a mapping containing this exact key cannot be expressed;
that is the documented cost of keeping :class:`Ref` JSON-native."""


@dataclass(frozen=True, slots=True)
class Ref:
    """A parameter value that resolves against a per-clip measurement.

    The measured constraint this exists for: the Que Calor flatten scale had to
    be ``0.5`` for two source clips and ``0.75`` for a third, because the right
    rule normalises *post-effect* sharpness across sources. A number fixed at
    the top of a Look is provably wrong; a callable is not serializable. A Ref
    is neither — it is a name plus an explicit policy for its absence.

    ``default`` is genuinely optional, and that is the point. A Ref with no
    default that the probe does not answer is a **refusal**
    (:class:`UnresolvedParameter`), because a silent global fallback is exactly
    the failure this indirection exists to prevent. ``Ref(key, default=x)`` is
    the deliberate opt-in to one.

    >>> Ref("flatten_scale").has_default
    False
    >>> Ref("flatten_scale", default=0.5).has_default
    True
    >>> Ref("flatten_scale", default=0.5).to_json()
    {'$ref': 'flatten_scale', 'default': 0.5}
    >>> Ref.from_json({"$ref": "flatten_scale"})
    Ref(key='flatten_scale')
    """

    key: str
    default: Any = _NO_DEFAULT

    def __repr__(self) -> str:
        if self.default is _NO_DEFAULT:
            return f"Ref(key={self.key!r})"
        return f"Ref(key={self.key!r}, default={self.default!r})"

    @property
    def has_default(self) -> bool:
        """Whether an absent probe entry falls back instead of refusing."""
        return self.default is not _NO_DEFAULT

    def to_json(self) -> dict:
        """The JSON-native encoding (see :data:`REF_MARKER`)."""
        d: dict = {REF_MARKER: self.key}
        if self.has_default:
            d["default"] = self.default
        return d

    @classmethod
    def from_json(cls, d: Mapping) -> "Ref":
        """Rebuild from :meth:`to_json`; strict about the shape.

        >>> Ref.from_json({"$ref": 3})
        Traceback (most recent call last):
            ...
        looks.spec.SchemaError: Ref '$ref' must be a string, got 3.
        """
        keys = set(d)
        if not keys <= {REF_MARKER, "default"} or REF_MARKER not in keys:
            raise SchemaError(
                f"not a Ref encoding: {dict(d)!r}. Expected exactly "
                f"{{{REF_MARKER!r}: <str>}} with an optional 'default'."
            )
        key = d[REF_MARKER]
        if not isinstance(key, str):
            raise SchemaError(f"Ref {REF_MARKER!r} must be a string, got {key!r}.")
        return cls(key, d["default"]) if "default" in d else cls(key)


def _is_ref_json(value: Any) -> bool:
    return isinstance(value, Mapping) and REF_MARKER in value


# ---------------------------------------------------------------------------
# The request
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class Effect:
    """One named operation the caller asks for. Pure data; no tier, no impl.

    Constructing an Effect deliberately does **not** consult the registry. A
    Look authored against a newer plugin set must still load, diff and print in
    a process that lacks it — the discipline that lets an old ``lacing`` build
    read a newer body. The refusal that matters ("we will not run this") belongs
    at compile time, where :func:`select_impl` names the registered set. The
    ergonomic front door (``looks.effect(...)``, which *does* check) lives in
    the registry module.

    Attributes:
        name: The **capability** asked for (``"flatten"``, ``"lut3d"``). Not an
            implementation; several may offer it at different tiers.
        params: Parameters. JSON values, or a :class:`Ref` for one that resolves
            per clip.
        at: Where in the clip it applies. ``None`` is the whole clip. A span,
            never a cut.
        impl: Pin one implementation by key. Bypasses tier-preference selection
            but **not** the ceiling — a pinned impl above ``max_tier`` still
            refuses.
        backend: Pin a backend family (``"ffmpeg"``, ``"frame"``) without naming
            an implementation. A weaker pin than ``impl``.
        metadata: Free-form labels. Deliberately **identity-free**: it does not
            enter :func:`look_hash`, mirroring ``falaw.CallPlan.metadata``.

    >>> Effect(name="posterize", params={"levels": 18})
    Effect(name='posterize', params={'levels': 18}, at=None, impl=None, backend=None, metadata={})
    >>> Effect(name="flatten", params={"scale": Ref("s")}).unresolved_refs
    ('scale',)
    """

    name: str
    params: dict = field(default_factory=dict)
    at: Optional[Span] = None
    impl: Optional[str] = None
    backend: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Effect: name must be a non-empty capability name.")

    @property
    def unresolved_refs(self) -> tuple[str, ...]:
        """Parameter names still holding a :class:`Ref`, in declaration order."""
        return tuple(k for k, v in self.params.items() if isinstance(v, Ref))

    @property
    def is_resolved(self) -> bool:
        """Whether every parameter is a concrete value."""
        return not self.unresolved_refs


# ---------------------------------------------------------------------------
# The authoring artifact
# ---------------------------------------------------------------------------

LOOK_SCHEMA = "looks.look/v1"
"""Schema tag written by :func:`look_to_dict`. Bumped only on a *breaking*
change to the dict shape — see the serialization note below."""

LOOK_VERSION = 1


@dataclass(frozen=True, slots=True, kw_only=True)
class Look:
    """An ordered stack of :class:`Effect`\\ s under one licence ceiling.

    Looks compose. ``a + b`` concatenates the steps and takes the **stricter**
    of the two ceilings, never the looser: composing a commercial-safe Look with
    a research one must refuse loudly rather than silently relax the guarantee
    the first one carried. Widening is always a separate, deliberate act
    (:meth:`with_max_tier`).

    >>> safe = Look(name="grade", steps=(Effect(name="eq"),), max_tier=Tier.PERMISSIVE)
    >>> lab = Look(steps=(Effect(name="cartoon"),), max_tier=Tier.NONCOMMERCIAL)
    >>> (safe + lab).max_tier
    <Tier.PERMISSIVE: 'permissive'>
    >>> (safe + lab).with_max_tier(Tier.NONCOMMERCIAL).max_tier
    <Tier.NONCOMMERCIAL: 'noncommercial'>
    >>> len(safe + lab), [e.name for e in safe + lab]
    (2, ['eq', 'cartoon'])
    """

    steps: tuple[Effect, ...] = ()
    name: str = ""
    max_tier: Tier = DFLT_MAX_TIER
    metadata: dict = field(default_factory=dict)
    version: int = LOOK_VERSION

    def __add__(self, other: "Look") -> "Look":
        if not isinstance(other, Look):
            return NotImplemented
        return Look(
            steps=self.steps + other.steps,
            name=self.name or other.name,
            max_tier=min(self.max_tier, other.max_tier),
            metadata={**other.metadata, **self.metadata},
        )

    def __len__(self) -> int:
        return len(self.steps)

    def __iter__(self) -> Iterator[Effect]:
        return iter(self.steps)

    def __getitem__(self, idx):
        return self.steps[idx]

    @property
    def unresolved(self) -> tuple[tuple[int, str], ...]:
        """``(step index, parameter name)`` for every parameter still a Ref."""
        return tuple(
            (i, k) for i, e in enumerate(self.steps) for k in e.unresolved_refs
        )

    @property
    def is_resolved(self) -> bool:
        """Whether :func:`resolve` would be the identity on this Look."""
        return not self.unresolved

    def with_max_tier(self, tier: Tier) -> "Look":
        """A copy under a different ceiling. Widening is deliberate, by design."""
        return replace(self, max_tier=tier)

    def with_step_replaced(self, index: int, step: Effect) -> "Look":
        """A copy with one step swapped (Looks are frozen)."""
        steps = list(self.steps)
        steps[index] = step
        return replace(self, steps=tuple(steps))


def resolve(look: Look, probe: Mapping[str, Any] = ()) -> Look:
    """Replace every :class:`Ref` with a concrete value from ``probe``.

    Pure, total, and the **identity on a Look that holds no Refs** — which is
    what keeps the simple case simple: a caller who already has numbers never
    meets this function.

    ``probe`` is a plain mapping the caller measures however it likes. That is
    deliberate: the rule Que Calor validated is a closed loop over the *output*
    ("measure post-effect sharpness and land the sources in family"), not a
    function of input statistics, so the measurement policy cannot live inside a
    spec type. What lives here is the refusal.

    Raises:
        UnresolvedParameter: a Ref with no default that ``probe`` does not
            answer. Names the step, the parameter and the key.

    >>> look = Look(steps=(Effect(name="flatten", params={"scale": Ref("s"), "sr": 60}),))
    >>> resolve(look, {"s": 0.75})[0].params
    {'scale': 0.75, 'sr': 60}
    >>> resolve(look)
    Traceback (most recent call last):
        ...
    looks.spec.UnresolvedParameter: step 0 ('flatten') parameter 'scale' needs probe key 's',
    which was not supplied and has no default. Measure it, pass probe={'s': ...},
    or give the Ref an explicit default.
    >>> concrete = Look(steps=(Effect(name="eq", params={"gamma": 1.1}),))
    >>> resolve(concrete) is concrete
    True
    """
    if look.is_resolved:
        return look
    probe = dict(probe)
    steps = []
    for i, effect in enumerate(look.steps):
        if effect.is_resolved:
            steps.append(effect)
            continue
        params = {}
        for key, value in effect.params.items():
            if not isinstance(value, Ref):
                params[key] = value
            elif value.key in probe:
                params[key] = probe[value.key]
            elif value.has_default:
                params[key] = value.default
            else:
                raise UnresolvedParameter(
                    f"step {i} ({effect.name!r}) parameter {key!r} needs "
                    f"probe key {value.key!r},\nwhich was not supplied and has "
                    f"no default. Measure it, pass probe={{{value.key!r}: ...}},"
                    "\nor give the Ref an explicit default."
                )
        steps.append(replace(effect, params=params))
    return replace(look, steps=tuple(steps))


# ---------------------------------------------------------------------------
# What an implementation declares about itself
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class ImplRef:
    """One implementation's self-declaration. Pure data.

    The registry pairs this with two callables (``compile`` and ``estimate``);
    only the declaration travels into a :class:`Step`, which is why a serialized
    plan can be audited for licence without importing a single backend.

    Attributes:
        effect: The capability served (matches :attr:`Effect.name`).
        impl: Globally unique implementation key,
            ``<effect>.<backend>.<variant>`` — e.g. ``"flatten.opencv.meanshift"``.
        backend: Execution family: ``"ffmpeg"`` (a filter fragment), ``"frame"``
            (a per-frame array op), ``"external"`` (renders and returns a path —
            muvid's escape hatch).
        tier: This implementation's rung on the licence ladder. **The only place
            a tier is ever declared.**
        impl_version: Behaviour version. "Same interface, changed behaviour"
            bumps this *without renaming* ``impl``; it enters :func:`plan_hash`
            unconditionally.
        timeline: Whether the implementation can be gated to an
            :attr:`Effect.at`. Verified against ffmpeg 8.1's filter table:
            ``lut3d``, ``lutrgb``, ``eq``, ``curves``, ``unsharp`` and ``gblur``
            carry the ``T`` (timeline) flag; ``scale`` does not, so a spanned
            geometry effect must refuse rather than silently apply to the whole
            clip.

    >>> ImplRef(effect="lut3d", impl="lut3d.ffmpeg.cube", backend="ffmpeg",
    ...         tier=Tier.COPYLEFT_TOOL).impl_version
    '1'
    """

    effect: str
    impl: str
    backend: str
    tier: Tier
    impl_version: str = "1"
    timeline: bool = True

    def __post_init__(self) -> None:
        for attr in ("effect", "impl", "backend"):
            if not getattr(self, attr):
                raise ValueError(f"ImplRef: {attr} must be non-empty.")
        if not isinstance(self.impl_version, str):
            raise ValueError(
                f"ImplRef({self.impl!r}): impl_version must be a str, got "
                f"{self.impl_version!r}. A non-str version renders identically "
                "in provenance while hashing differently."
            )


def select_impl(
    effect: Effect,
    candidates: Sequence[ImplRef],
    *,
    max_tier: Tier = DFLT_MAX_TIER,
) -> ImplRef:
    """Choose the implementation that will serve ``effect``, or refuse.

    The rule, in order:

    1. Keep candidates whose ``effect`` matches; if the Effect pins ``impl`` or
       ``backend``, keep only those.
    2. Drop every candidate above ``max_tier``.
    3. Among survivors prefer the **lowest tier**, ties broken by registration
       order. The default is the safest thing that can do the job; a caller who
       wants a specific implementation for *quality* reasons pins ``impl=``,
       because quality is not knowable to a registry and licence is.
    4. No candidates at all → :class:`UnknownEffect`.
    5. Candidates existed but all exceeded the ceiling → :class:`LicenceRefusal`,
       naming each one's tier and the call that would widen the ceiling.

    ``Tier.UNKNOWN`` needs no special case: it sits at the top of the ladder, so
    it is unreachable unless the ceiling is literally ``Tier.UNKNOWN`` — a
    spelling nobody writes by accident.

    >>> cands = (
    ...     ImplRef(effect="cartoon", impl="cartoon.torch.animeganv2",
    ...             backend="frame", tier=Tier.NONCOMMERCIAL),
    ...     ImplRef(effect="cartoon", impl="cartoon.ffmpeg.posterize",
    ...             backend="ffmpeg", tier=Tier.COPYLEFT_TOOL),
    ... )
    >>> select_impl(Effect(name="cartoon"), cands).impl
    'cartoon.ffmpeg.posterize'
    >>> select_impl(Effect(name="cartoon"), cands, max_tier=Tier.PERMISSIVE)
    Traceback (most recent call last):
        ...
    looks.spec.LicenceRefusal: no implementation of 'cartoon' is within the 'permissive' ceiling.
    Rejected: cartoon.ffmpeg.posterize (copyleft-tool), cartoon.torch.animeganv2 (noncommercial).
    Raise it deliberately with look.with_max_tier(Tier.COPYLEFT_TOOL), or pick another effect.
    >>> select_impl(Effect(name="nope"), cands)
    Traceback (most recent call last):
        ...
    looks.spec.UnknownEffect: no implementation offers 'nope'.
    Registered capabilities: 'cartoon'.

    A span is refused rather than silently widened when the chosen backend
    cannot be gated — ``scale`` is the real case (ffmpeg 8.1 gives it no ``T``
    flag, unlike ``lut3d`` / ``lutrgb`` / ``eq`` / ``curves`` / ``unsharp``):

    >>> geom = (ImplRef(effect="fit", impl="fit.ffmpeg.scale", backend="ffmpeg",
    ...                 tier=Tier.COPYLEFT_TOOL, timeline=False),)
    >>> select_impl(Effect(name="fit", at=Span(0.0, 2.0)), geom)
    Traceback (most recent call last):
        ...
    looks.spec.SpanUnsupported: 'fit.ffmpeg.scale' cannot be gated to a time span
    (its backend has no timeline support), but the effect declares
    at=Span(start=0.0, end=2.0). Drop the span, or split the clip first.
    """
    offered = [c for c in candidates if c.effect == effect.name]
    if not offered:
        listed = ", ".join(repr(n) for n in sorted({c.effect for c in candidates}))
        raise UnknownEffect(
            f"no implementation offers {effect.name!r}.\n"
            f"Registered capabilities: {listed or '(none)'}."
        )
    pinned = offered
    if effect.impl is not None:
        pinned = [c for c in pinned if c.impl == effect.impl]
        if not pinned:
            listed = ", ".join(repr(c.impl) for c in offered)
            raise UnknownEffect(
                f"{effect.name!r} has no implementation {effect.impl!r}. "
                f"Available: {listed}."
            )
    if effect.backend is not None:
        pinned = [c for c in pinned if c.backend == effect.backend]
        if not pinned:
            listed = ", ".join(sorted({c.backend for c in offered}))
            raise UnknownEffect(
                f"{effect.name!r} has no {effect.backend!r} implementation. "
                f"Backends: {listed}."
            )
    within = sorted(
        ((i, c) for i, c in enumerate(pinned) if c.tier <= max_tier),
        key=lambda pair: (pair[1].tier.rank, pair[0]),
    )
    if not within:
        rejected = ", ".join(
            f"{c.impl} ({c.tier.value})" for c in sorted(pinned, key=lambda c: c.tier)
        )
        cheapest = min(pinned, key=lambda c: c.tier).tier
        raise LicenceRefusal(
            f"no implementation of {effect.name!r} is within the "
            f"{max_tier.value!r} ceiling.\n"
            f"Rejected: {rejected}.\n"
            f"Raise it deliberately with look.with_max_tier(Tier.{cheapest.name}), "
            "or pick another effect."
        )
    chosen = within[0][1]
    if effect.at is not None and not chosen.timeline:
        raise SpanUnsupported(
            f"{chosen.impl!r} cannot be gated to a time span\n"
            f"(its backend has no timeline support), but the effect declares\n"
            f"at={effect.at!r}. Drop the span, or split the clip first."
        )
    return chosen


# ---------------------------------------------------------------------------
# The compiled form
# ---------------------------------------------------------------------------

PLAN_SCHEMA = "looks.plan/v1"
"""Schema tag written by :func:`plan_to_dict`."""

PLAN_VERSION = 1


@dataclass(frozen=True, slots=True, kw_only=True)
class Step:
    """One compiled operation: exactly what will run, and at what cost.

    The analogue of ``falaw.CallPlan``. ``params`` is fully concrete (no Refs
    survive compilation), ``impl`` records *which* implementation was selected
    and at which behaviour version, and :attr:`tier` is read off it — so a
    stored plan is auditable for licence with nothing imported.

    ``payload`` is backend-shaped, and is the one place in the whole type system
    where backend specifics live. The asymmetry between backends is deliberate
    and worth stating plainly:

    - ``ffmpeg`` → ``{"filter": "<fragment>", "inputs": [[...]]}``. Fully
      self-describing: you can read a plan and see the exact filtergraph.
    - ``frame`` → ``{"op": "<registry key>"}``. Only *nameable* — there is no
      inspectable rendering of "run this Python function". The op is a registry
      key, never a ``module:attr`` import path, so a plan loaded from an
      untrusted document cannot name ``os:system``.
    - ``external`` → ``{"tool": "<registry key>"}``, same rule, same reason.

    ``cpu_seconds`` is the cost unit: **CPU-seconds, not dollars**. ``None``
    means unknown, and never zero.

    >>> ref = ImplRef(effect="posterize", impl="posterize.ffmpeg.lutrgb",
    ...               backend="ffmpeg", tier=Tier.COPYLEFT_TOOL)
    >>> s = Step(effect="posterize", impl=ref, params={"levels": 18},
    ...          payload={"filter": "lutrgb=r='trunc(val/18)*18+9'"},
    ...          cpu_seconds=2.9)
    >>> s.tier, s.backend
    (<Tier.COPYLEFT_TOOL: 'copyleft-tool'>, 'ffmpeg')
    >>> Step(effect="flatten", impl=ref, params={"scale": Ref("s")})
    Traceback (most recent call last):
        ...
    looks.spec.UnresolvedParameter: Step('flatten'): parameter 'scale' is still a Ref.
    Call resolve(look, probe) before compiling.
    """

    effect: str
    impl: ImplRef
    params: dict = field(default_factory=dict)
    at: Optional[Span] = None
    payload: dict = field(default_factory=dict)
    cpu_seconds: Optional[float] = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        cost = self.cpu_seconds
        # `not (x >= 0)` also catches NaN — falaw.CallPlan's guard, same reason.
        if cost is not None and not (cost >= 0):
            raise ValueError(
                f"Step({self.effect!r}): cpu_seconds must be non-negative or "
                f"None, got {cost!r}. `None` is how unknown is spelled."
            )
        for key, value in self.params.items():
            if isinstance(value, Ref):
                raise UnresolvedParameter(
                    f"Step({self.effect!r}): parameter {key!r} is still a Ref.\n"
                    "Call resolve(look, probe) before compiling."
                )

    @property
    def tier(self) -> Tier:
        """The selected implementation's rung. Not settable by the request."""
        return self.impl.tier

    @property
    def backend(self) -> str:
        """The execution family this step dispatches to."""
        return self.impl.backend


@dataclass(frozen=True, slots=True, kw_only=True)
class LookPlan:
    """The compiled pipeline: pure data, inspectable, persistable, costable.

    ``falaw.Plan`` transposed from dollars to CPU-seconds. The cost arithmetic is
    falaw's, verbatim in shape and for the same reasons:

    - :attr:`total_cpu_seconds` coerces unknown to ``0.0`` so sums stay total and
      composable, and is therefore a documented **lower bound**.
    - :attr:`known_cpu_seconds` and :attr:`unknown_step_count` are the honest
      pair a budget gate reads together.
    - :attr:`realtime_factor` returns ``None`` when anything is unknown. The
      asymmetry with ``total_cpu_seconds`` is deliberate: a sum has to be a total
      function to compose, but a single headline ratio a human will act on must
      not fabricate.

    Deliberately **not** modelled: peak memory and the streaming shape. Those are
    the executor's invariant — muvid's ``assemble.py`` earned its bounded-memory
    rule after 30-cut OOM kills — and a plan that claimed to predict them would
    invite exactly the one-big-filtergraph convenience this package is chartered
    to stay out of.

    >>> ref = ImplRef(effect="lut3d", impl="lut3d.ffmpeg.cube",
    ...               backend="ffmpeg", tier=Tier.COPYLEFT_TOOL)
    >>> clip = ClipSpec(1280, 720, 30.0, 10.0)
    >>> known = Step(effect="lut3d", impl=ref, cpu_seconds=2.9)
    >>> unpriced = Step(effect="flatten", impl=ImplRef(
    ...     effect="flatten", impl="flatten.opencv.meanshift",
    ...     backend="frame", tier=Tier.PERMISSIVE))
    >>> p = LookPlan(steps=(known,), clip=clip)
    >>> p.total_cpu_seconds, p.has_unknown_costs, round(p.realtime_factor, 3)
    (2.9, False, 0.29)
    >>> q = LookPlan(steps=(known, unpriced), clip=clip)
    >>> q.total_cpu_seconds, q.known_cpu_seconds, q.unknown_step_count
    (2.9, 2.9, 1)
    >>> q.has_unknown_costs, q.realtime_factor is None
    (True, True)
    >>> q.tier                  # the plan's worst rung
    <Tier.COPYLEFT_TOOL: 'copyleft-tool'>
    >>> q.backends              # Que Calor's real shape: a frame op, then ffmpeg
    ('ffmpeg', 'frame')
    """

    steps: tuple[Step, ...] = ()
    clip: Optional[ClipSpec] = None
    look_name: str = ""
    max_tier: Tier = DFLT_MAX_TIER
    probe: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    version: int = PLAN_VERSION

    def __len__(self) -> int:
        return len(self.steps)

    def __iter__(self) -> Iterator[Step]:
        return iter(self.steps)

    def __getitem__(self, idx):
        return self.steps[idx]

    def __add__(self, other: "LookPlan") -> "LookPlan":
        if not isinstance(other, LookPlan):
            return NotImplemented
        if self.clip is not None and other.clip is not None and self.clip != other.clip:
            raise ValueError(
                "LookPlan: refusing to concatenate plans compiled against "
                f"different clips ({self.clip} vs {other.clip}). A payload names "
                "pixels, so the geometry is part of what a step means."
            )
        return LookPlan(
            steps=self.steps + other.steps,
            clip=self.clip or other.clip,
            look_name=self.look_name or other.look_name,
            max_tier=min(self.max_tier, other.max_tier),
            probe={**other.probe, **self.probe},
            metadata={**other.metadata, **self.metadata},
        )

    @property
    def total_cpu_seconds(self) -> float:
        """Sum over steps, unknown counted as zero. A **lower bound**."""
        return sum((s.cpu_seconds or 0.0 for s in self.steps), 0.0)

    @property
    def known_cpu_seconds(self) -> float:
        """The priced part of :attr:`total_cpu_seconds` — the same number today,
        honest by construction."""
        return sum(
            (s.cpu_seconds for s in self.steps if s.cpu_seconds is not None), 0.0
        )

    @property
    def unknown_step_count(self) -> int:
        """How many steps carry no cost estimate at all."""
        return sum(1 for s in self.steps if s.cpu_seconds is None)

    @property
    def has_unknown_costs(self) -> bool:
        """Whether any step is unpriced. A budget gate refuses on this."""
        return self.unknown_step_count > 0

    @property
    def realtime_factor(self) -> Optional[float]:
        """CPU-seconds per second of output, or ``None`` when not knowable."""
        duration = None if self.clip is None else self.clip.duration_s
        if self.has_unknown_costs or not duration:
            return None
        return self.total_cpu_seconds / duration

    @property
    def tier(self) -> Tier:
        """The worst rung any step reaches — the plan's licence verdict."""
        if not self.steps:
            return Tier.PERMISSIVE
        return max(s.tier for s in self.steps)

    @property
    def backends(self) -> tuple[str, ...]:
        """Distinct backends, in first-appearance order. A plan spanning more
        than one is normal, and is what tells an executor it needs more than a
        filtergraph."""
        seen: list[str] = []
        for s in self.steps:
            if s.backend not in seen:
                seen.append(s.backend)
        return tuple(seen)


# ---------------------------------------------------------------------------
# Serialization
#
# The additive-vs-breaking rule, taken from artful / lacing / falaw and stated
# once:
#
# * Adding an OPTIONAL field with a default is a *tolerated-default addition*.
#   It is always written, and the reader defaults it when absent, so a document
#   from before the field parses here, and a document written here parses under
#   an older build (which simply never reads the extra key). No tag bump, no
#   migration.
# * Renaming, removing, retyping or re-defaulting a serialized field is
#   BREAKING: bump the tag, and land a migration with the downstream update.
# * An unrecognized tag is refused loudly. A missing tag is tolerated as v1, so
#   hand-written Looks stay easy.
#
# There is no migration registry at v1, because a registry with no entries is a
# stub. When the first v2 lands it must be keyed on `(kind, from_version)`, not
# on `(from, to)` alone: `an` paid for that lesson — a registry that cannot tell
# its document kinds apart runs a Look migration against a plan, and nothing
# collides, the wrong function simply runs.
# ---------------------------------------------------------------------------


def _params_to_json(params: Mapping[str, Any]) -> dict:
    return {k: (v.to_json() if isinstance(v, Ref) else v) for k, v in params.items()}


def _params_from_json(params: Mapping[str, Any]) -> dict:
    return {k: (Ref.from_json(v) if _is_ref_json(v) else v) for k, v in params.items()}


def _span_to_json(span: Optional[Span]):
    return None if span is None else {"start": span.start, "end": span.end}


def _span_from_json(d) -> Optional[Span]:
    return None if d is None else Span(d.get("start"), d.get("end"))


def _effect_to_json(effect: Effect) -> dict:
    return {
        "name": effect.name,
        "params": _params_to_json(effect.params),
        "at": _span_to_json(effect.at),
        "impl": effect.impl,
        "backend": effect.backend,
        "metadata": effect.metadata,
    }


def _effect_from_json(d: Mapping) -> Effect:
    return Effect(
        name=d["name"],
        params=_params_from_json(d.get("params") or {}),
        at=_span_from_json(d.get("at")),
        impl=d.get("impl"),
        backend=d.get("backend"),
        metadata=dict(d.get("metadata") or {}),
    )


def look_to_dict(look: Look) -> dict:
    """A plain JSON-serializable dict, round-tripping through :func:`look_from_dict`.

    >>> look = Look(name="qc", steps=(Effect(name="flatten",
    ...     params={"scale": Ref("s", default=0.5)}, at=Span(0.0, 4.0)),))
    >>> d = look_to_dict(look)
    >>> d["schema"], d["max_tier"]
    ('looks.look/v1', 'copyleft-tool')
    >>> import json; json.loads(json.dumps(d)) == d
    True
    >>> look_from_dict(d) == look
    True
    """
    return {
        "schema": LOOK_SCHEMA,
        "version": look.version,
        "name": look.name,
        "max_tier": look.max_tier.value,
        "steps": [_effect_to_json(e) for e in look.steps],
        "metadata": look.metadata,
    }


def look_from_dict(d: Mapping) -> Look:
    """Rebuild a :class:`Look`. Refuses an unknown tag; tolerates a missing one.

    >>> look_from_dict({"schema": "looks.look/v9", "steps": []})
    Traceback (most recent call last):
        ...
    looks.spec.SchemaError: cannot read a Look tagged 'looks.look/v9';
    this build understands 'looks.look/v1'.
    >>> look_from_dict({"steps": [{"name": "eq"}]})[0].name   # untagged reads as v1
    'eq'
    """
    schema = d.get("schema")
    if schema is not None and schema != LOOK_SCHEMA:
        raise SchemaError(
            f"cannot read a Look tagged {schema!r};\n"
            f"this build understands {LOOK_SCHEMA!r}."
        )
    return Look(
        steps=tuple(_effect_from_json(e) for e in d.get("steps", ())),
        name=d.get("name", ""),
        max_tier=Tier(d.get("max_tier", DFLT_MAX_TIER.value)),
        metadata=dict(d.get("metadata") or {}),
        version=d.get("version", LOOK_VERSION),
    )


def _impl_to_json(impl: ImplRef) -> dict:
    return {
        "effect": impl.effect,
        "impl": impl.impl,
        "backend": impl.backend,
        "tier": impl.tier.value,
        "impl_version": impl.impl_version,
        "timeline": impl.timeline,
    }


def _impl_from_json(d: Mapping) -> ImplRef:
    return ImplRef(
        effect=d["effect"],
        impl=d["impl"],
        backend=d["backend"],
        tier=Tier(d["tier"]),
        impl_version=d.get("impl_version", "1"),
        timeline=d.get("timeline", True),
    )


def _step_to_json(step: Step) -> dict:
    return {
        "effect": step.effect,
        "impl": _impl_to_json(step.impl),
        "params": _params_to_json(step.params),
        "at": _span_to_json(step.at),
        "payload": step.payload,
        "cpu_seconds": step.cpu_seconds,
        "metadata": step.metadata,
    }


def _step_from_json(d: Mapping) -> Step:
    return Step(
        effect=d["effect"],
        impl=_impl_from_json(d["impl"]),
        params=_params_from_json(d.get("params") or {}),
        at=_span_from_json(d.get("at")),
        payload=dict(d.get("payload") or {}),
        cpu_seconds=d.get("cpu_seconds"),
        metadata=dict(d.get("metadata") or {}),
    )


def plan_to_dict(plan: LookPlan) -> dict:
    """A plain JSON-serializable dict for a compiled plan.

    >>> ref = ImplRef(effect="lut3d", impl="lut3d.ffmpeg.cube",
    ...               backend="ffmpeg", tier=Tier.COPYLEFT_TOOL)
    >>> plan = LookPlan(steps=(Step(effect="lut3d", impl=ref, cpu_seconds=2.9),),
    ...                 clip=ClipSpec(1280, 720, 30.0, 10.0), probe={"s": 0.75})
    >>> d = plan_to_dict(plan)
    >>> d["schema"]
    'looks.plan/v1'
    >>> import json; plan_from_dict(json.loads(json.dumps(d))) == plan
    True
    """
    clip = plan.clip
    return {
        "schema": PLAN_SCHEMA,
        "version": plan.version,
        "look_name": plan.look_name,
        "max_tier": plan.max_tier.value,
        "clip": (
            None
            if clip is None
            else {
                "width": clip.width,
                "height": clip.height,
                "fps": clip.fps,
                "duration_s": clip.duration_s,
            }
        ),
        "probe": plan.probe,
        "steps": [_step_to_json(s) for s in plan.steps],
        "metadata": plan.metadata,
    }


def plan_from_dict(d: Mapping) -> LookPlan:
    """Rebuild a :class:`LookPlan`. Refuses an unknown tag."""
    schema = d.get("schema")
    if schema is not None and schema != PLAN_SCHEMA:
        raise SchemaError(
            f"cannot read a LookPlan tagged {schema!r};\n"
            f"this build understands {PLAN_SCHEMA!r}."
        )
    clip = d.get("clip")
    return LookPlan(
        steps=tuple(_step_from_json(s) for s in d.get("steps", ())),
        clip=(
            None
            if clip is None
            else ClipSpec(
                clip["width"], clip["height"], clip["fps"], clip.get("duration_s")
            )
        ),
        look_name=d.get("look_name", ""),
        max_tier=Tier(d.get("max_tier", DFLT_MAX_TIER.value)),
        probe=dict(d.get("probe") or {}),
        metadata=dict(d.get("metadata") or {}),
        version=d.get("version", PLAN_VERSION),
    )


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def _canonical_blob(payload: Any) -> bytes:
    """Sorted-key JSON with no ``default=str`` fallback and no NaN.

    ``falaw.canonical.canonical_blob``'s rule, for its reason: a value the form
    cannot represent faithfully must **raise** rather than collide with
    something else's ``repr``.
    """
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def look_hash(look: Look) -> str:
    """Structural identity of the authored *intent*.

    Answers "is this the same Look?" — stable across machines and across
    registries, because it names capabilities and parameters and nothing about
    implementations. ``metadata`` is excluded on purpose (labelling, not
    identity), and so is ``max_tier``: a ceiling changes what a Look is
    *allowed* to compile to, never what it asks for.

    >>> a = Look(name="x", steps=(Effect(name="eq", params={"gamma": 1.1}),))
    >>> look_hash(a) == look_hash(replace(a, name="y"))          # name IS identity
    False
    >>> look_hash(a) == look_hash(replace(a, metadata={"who": "thor"}))
    True
    >>> look_hash(a) == look_hash(a.with_max_tier(Tier.PERMISSIVE))
    True
    """
    payload = {
        "name": look.name,
        "steps": [
            {
                "name": e.name,
                "params": _params_to_json(e.params),
                "at": _span_to_json(e.at),
                "impl": e.impl,
                "backend": e.backend,
            }
            for e in look.steps
        ],
    }
    return hashlib.sha256(_canonical_blob(payload)).hexdigest()


def plan_hash(plan: LookPlan) -> str:
    """Identity of the compiled pipeline — "will this produce the same pixels?".

    Folds, per step: the **implementation key and its version**, the resolved
    parameters, the span and the compiled payload; plus the clip geometry,
    because a payload names pixels.

    Three decisions worth spelling out:

    - The **capability name is carried, but the implementation is what binds.**
      Two implementations of ``"flatten"`` produce different pixels; the name
      denotes what was asked for, ``impl`` / ``impl_version`` what answers.
    - ``impl_version`` is folded **unconditionally**. falaw and nw omit theirs
      at the default value, but that is a *migration* device protecting an
      installed base of cache keys, not a design principle — ``looks`` has no
      installed base, and the sentinel would buy nothing while costing a subtle
      rule.
    - The **tier is not hashed**. Relicensing an implementation changes what you
      are allowed to run, never what it renders; the audit trail for that lives
      in :func:`plan_to_dict`, not in the identity of the pixels.

    ``probe`` is not hashed either: the entries that mattered already became
    resolved parameters, and hashing the whole probe would key a plan on
    measurements it never consumed.

    >>> ref = ImplRef(effect="lut3d", impl="lut3d.ffmpeg.cube",
    ...               backend="ffmpeg", tier=Tier.COPYLEFT_TOOL)
    >>> clip = ClipSpec(1280, 720, 30.0, 10.0)
    >>> p = LookPlan(steps=(Step(effect="lut3d", impl=ref),), clip=clip)
    >>> plan_hash(p) == plan_hash(replace(p, probe={"s": 0.5}))
    True
    >>> bumped = replace(p, steps=(replace(p[0], impl=replace(ref, impl_version="2")),))
    >>> plan_hash(p) == plan_hash(bumped)
    False
    >>> plan_hash(p) == plan_hash(replace(p, clip=ClipSpec(1920, 1080, 30.0, 10.0)))
    False
    """
    clip = plan.clip
    payload = {
        "clip": (
            None
            if clip is None
            else [clip.width, clip.height, clip.fps, clip.duration_s]
        ),
        "steps": [
            {
                "effect": s.effect,
                "impl": s.impl.impl,
                "impl_version": s.impl.impl_version,
                "backend": s.impl.backend,
                "params": _params_to_json(s.params),
                "at": _span_to_json(s.at),
                "payload": s.payload,
            }
            for s in plan.steps
        ],
    }
    return hashlib.sha256(_canonical_blob(payload)).hexdigest()


def output_key(plan: LookPlan, source_digest: str) -> str:
    """The content-addressed key of what this plan makes from these bytes.

    ``source_digest`` is a digest of the source's **content**, never its path or
    URL. That is falaw's D1 defect stated as a signature: keying on a location
    means a byte-identical regeneration upstream misses the cache forever, and a
    changed file at the same path hits it wrongly.

    ``looks`` computes the formula and nothing else — it does not open the file,
    because reading bytes is execution, and this package declares no
    dependencies and runs nothing.

    >>> ref = ImplRef(effect="lut3d", impl="lut3d.ffmpeg.cube",
    ...               backend="ffmpeg", tier=Tier.COPYLEFT_TOOL)
    >>> p = LookPlan(steps=(Step(effect="lut3d", impl=ref),),
    ...              clip=ClipSpec(1280, 720, 30.0, 10.0))
    >>> k = output_key(p, "a" * 64)
    >>> len(k), k == output_key(p, "a" * 64)
    (64, True)
    >>> k == output_key(p, "b" * 64)
    False
    """
    if not source_digest:
        raise ValueError(
            "output_key: source_digest must be a digest of the source's bytes. "
            "An empty digest would collide every source into one key."
        )
    h = hashlib.sha256()
    h.update(plan_hash(plan).encode())
    h.update(b"\0")
    h.update(source_digest.encode())
    return h.hexdigest()
```

---

## 3. Q1 — `Effect`

**Fields:** `name` (the *capability*), `params`, `at`, `impl`, `backend`, `metadata`. Frozen, slots, keyword-only — falaw's shape, for falaw's reasons.

**No tier field, and this is the whole design.** If a caller could write `Effect(name="cartoon", tier=Tier.PERMISSIVE)`, the refusal becomes theatre: the thing being checked is an assertion by the party who wants the answer to be yes. So the tier lives on `ImplRef`, which the *implementation* declares, and the ceiling lives on `Look`. An `Effect` in isolation genuinely has no licence status, and that is honest — the same capability name can be served by a permissive implementation on one machine and a copyleft one on another.

**No version field either.** The version that matters is the implementation's behaviour version, which is not knowable until an implementation is selected. Putting an author-supplied version on the request would be a second, unenforceable identity.

**How an unregistered name fails: at compile time, not at construction.** This is the one place I deliberately diverge from "fail early", and there are two reasons.

The first is portability. A `Look` is a document. A `Look` authored on a machine with an extra plugin installed must still *load, print, diff and round-trip* on a machine without it — you should be able to read what someone asked for even when you cannot serve it. Refusing at `Effect.__init__` makes `look_from_dict` refuse too, which turns a missing plugin into an unreadable file. That is the failure shape `lacing`'s body-schema discipline exists to prevent [5], and `artful` states the rule explicitly for the four URIs it owns [7]: an old build must be able to read a newer body.

The second is that the refusal that matters is a *different* refusal. "I do not know that name" and "I know that name, and every implementation of it is above your ceiling" are answers to the same question and must be raised from the same place, with the same information in hand. That place is `select_impl`.

The ergonomic cost is real: `Effect(name="meanshfit")` survives until compile. The mitigation is a checking front door in the registry module — `looks.effect("flatten", scale=0.5)` — which *does* consult the registry and is what a human types. The dataclass stays the wire door. That is the same split `lacing` uses: the `Annotation` envelope accepts any `body_schema_uri`; the validating constructor is a separate call.

**`at` is a `Span`, in float seconds, and it is never a cut.** The kickoff's non-negotiable is that `Effect.at` says where a look applies and never where a cut is [14], so the type carries `start`/`end` and nothing else — no `clip_id`, no ordering, no adjacency. A `Span` is meaningless except against the clip a plan was compiled for, which is exactly the property that prevents it from growing into an EDL.

Float seconds rather than `lacing.RationalTime` deserves a defence, because it looks like a violation of a federation non-negotiable. It is not: lacing's rule governs *lacing annotations*, and the federation already runs three time conventions on purpose — `an`'s IR pillar 5 says "time in seconds (float) at the IR boundary; rational time only where audio drift matters", and `burns` uses a normalised `t ∈ [0,1]`. A half-frame error in *where a look starts* is imperceptible, and the thing this compiles to — ffmpeg's `enable='between(t,a,b)'` [8] — takes seconds. A Look that has to cross into a lacing annotation gets pinned to a `TimeInterval` by the caller, whose provenance concern that is.

**`metadata` is identity-free**, mirroring `falaw.CallPlan.metadata`, and `look_hash` proves it with a doctest rather than a comment. `looks` does not repeat falaw's `key_extra`/`metadata` twin-dict trap, because it does not need to: everything that affects the output is already a named field.

---

## 4. Q2 — `Look`

**Composition is `+`, and the ceiling takes the stricter of the two.**

This is the only interesting decision in the type. `a + b` where `a.max_tier` is `PERMISSIVE` and `b.max_tier` is `NONCOMMERCIAL` has two candidate meanings, and they fail in opposite directions:

- *Looser wins* — the result compiles, and `a`'s commercial-safety guarantee has silently evaporated. Nobody is told.
- *Stricter wins* — the result **refuses** `b`'s steps at compile time, loudly, naming the step and the rung.

Stricter wins. A guarantee that composition can silently relax is not a guarantee, and the non-negotiable is that this is a refusal and not a warning [14]. Widening is then a separate, deliberate act: `(a + b).with_max_tier(Tier.NONCOMMERCIAL)`. That is the same shape reelee applies to its spend threshold — raising or zeroing the ceiling is always its own explicit act, never a side effect of another option [12].

`min` works directly because `Tier` defines a real ordering. Note the trap that ordering had to dodge: `Tier` subclasses `str` (so `json.dumps` handles it and the wire form is a readable string, stable under member reordering), which means `str` already supplies all four comparison operators lexicographically. All four are overridden. Inheriting even one would have compared `"copyleft-link" < "copyleft-tool"` as strings and silently got the ladder right *by accident* in that one pair while getting `"noncommercial" < "permissive"` wrong.

**`max_tier` is not part of `look_hash`.** A ceiling changes what a Look is *allowed* to compile to; it never changes what the Look asks for. Two Looks that differ only in ceiling are the same look, and treating them as different would fragment a cache for no reason.

**The default ceiling is `COPYLEFT_TOOL`**, per the kickoff: shelling out to a copyleft binary is fine by default; linking one in is not. The pleasing consequence is that "never depend on `av`, never depend on `imageio-ffmpeg`" stops being a rule in a document and becomes a comparison in the data — those live at `COPYLEFT_LINK`, one rung above the default, so they refuse without anyone remembering to check.

---

## 5. Q3 — the deferred-parameter problem

The measured constraint, restated because it is easy to mis-model: the Que Calor flattening scale had to be `0.5` for two source clips and `0.75` for a third, and the rule that produced those numbers **normalises the output, not the input** — measure post-effect sharpness per source and pick parameters that land them in family. Full resolution was available, sharper, and deliberately *not* used, because at ~150 Laplacian variance it would have made the softest source the sharpest thing in the edit [10][14].

That rule is a **closed loop over the output**. It is not a function `stats -> value`. Any design that assumes it is will be wrong on the first hard case.

### The four options

**(a) A param value may be a callable `stats -> value`.**

Rejected. Two reasons, one of which is not the obvious one.

The obvious one is serialisation — and it is narrower than it first appears. A callable would be *evaluated during resolution*, so the resulting `LookPlan` still holds a number and is still serialisable. What breaks is the **Look**, and the Look is the artifact. "The Que Calor look" is the thing you want to name, version, ship, diff against next month's revision, and reuse on the next project. A Look you cannot write to disk is not an asset, it is a local variable. `burns` hit exactly this and took the half-measure — accept the callable, raise at `to_dict` [3] — which is tolerable for easing, a tiny closed vocabulary that rarely travels, and intolerable for parameters, which *are* the identity.

The less obvious one: it also destroys diffability and hashability. Two Looks differing only in a lambda compare unequal and print `<function <lambda> at 0x10a...>`, which is not a diff. And no honest cache key can be computed — hashing `__code__` is brittle across Python versions, hashing the `repr` is a lie, and hashing nothing means a behaviour change serves stale artifacts forever, which is precisely defect D1's shape.

There is a third reason worth recording even though it is not decisive today: a callable in a document is arbitrary code from an untrusted source. That is the ComfyUI-graph lesson in miniature, and the video_gen decisions of record already say agent-generated graphs are untrusted input to a code-execution engine.

**(c) Params carry a `Resolver` object.**

Rejected for v1, kept as the growth path. If the `Resolver` is an arbitrary object it is option (a) with a class around it, and inherits every problem. If it is a *registered name plus params* it is serialisable and honest — but then it is a `Ref` with more machinery, and the machinery has no second customer. The standing architecture rule is that a seam is declared only when its eventual replacement already exists somewhere you can point at; a resolver registry does not. So: `Ref` is the single resolution strategy, a `Ref` is the degenerate `Resolver` ("look it up"), and the day a second strategy is *measured* the additive move is a `$resolver` marker alongside `$ref`, which needs no schema bump under the additive rule in §7.

**(d) The caller resolves; `looks` only ever sees concrete numbers.**

Rejected as the *only* option, and retained as a fully-supported mode. This is literally what Que Calor did — a `MS_PARAMS` dict literal at the top of `render_v2c.py` [10] — and it works. What it costs is portability: the per-clip numbers are not in the Look, so the Look is not the whole recipe, and every caller reimplements the same three lines of lookup. Crucially, this option is *not lost* by adopting (b): a Look with no `Ref`s is already fully concrete, `resolve` is the identity on it (`resolve(concrete) is concrete`, asserted in a doctest), and a caller with numbers never meets the function. Simple things stay simple.

**(b) A separate `resolve(look, probe) -> Look` pass. ADOPTED.**

`Ref(key)` names a probe entry. `probe` is a plain `Mapping[str, Any]` the caller measures however it likes — which is the point, because the validated rule is a loop over the output and cannot live inside a spec type. What lives in the spec type is the **refusal**.

Four properties make this the right answer rather than merely a workable one:

1. **JSON-native.** `Ref` encodes as `{"$ref": "flatten_scale"}`, a plain object. A Look with unresolved parameters round-trips through `json.dumps`.
2. **Diffable.** Two Looks differing in a Ref differ visibly, by name.
3. **The cache key is honest by construction.** By the time a `Step` exists, no `Ref` survives — `Step.__post_init__` raises if one does — so `plan_hash` folds the *resolved* value and nothing else. And the probe itself is deliberately **not** hashed: the entries that mattered already became parameters, and hashing the whole probe would key a plan on measurements it never consumed. That is the "key on the semantic input, never on a rendering of global state" rule reelee learned when memoizing at the wrong layer put the entire Transform registry into every planner cassette key [12].
4. **The refusal rule generalises from licences to parameters.** `default` is *optional*, and a `Ref` with no default that the probe does not answer **raises**. This is the same principle as `Tier.UNKNOWN`: unknown is a refusal, not a silent fallback. And it is the direct encoding of the measured lesson — a single global default is what made the softest source the mushiest thing on screen, so the type makes you either measure it or opt into the global explicitly, per parameter, in writing.

**Same type in, same type out.** `resolve` returns a `Look`, not a `ResolvedLook`. A fully-concrete Look *is* just a Look with no Refs; a second class would double the serialisation surface, double the migration surface, and force callers who already have numbers to construct something different for no gain. The predicate `Look.is_resolved` carries the distinction, and `Step.__post_init__` is the enforcement point where it actually matters.

**One documented cost.** `REF_MARKER` (`"$ref"`) is a reserved key inside a parameter *value*, so a parameter whose legitimate value is a mapping containing that exact key cannot be expressed. The decoder is strict about the shape (`{"$ref": <str>}` with an optional `default` and nothing else, raising otherwise) so the ambiguity cannot be hit silently. This is worth naming rather than hiding.

---

## 6. Q4 — the compiled form, and what a cost unit is here

### An `Effect` compiles to a `Step`, and a `Step` is a tagged union in a trench coat

The evidence forbids "an ffmpeg filter fragment". The Que Calor chain is `[per-frame OpenCV op] -> [ffmpeg filter] -> [ffmpeg filter]` — two execution shapes in one look — and muvid's escape hatch is a third [2][10]. So `Step.payload` is backend-shaped, and it is the *only* place in the type system where backend specifics live.

The asymmetry between backends is real and should be stated rather than smoothed over:

| backend | payload | inspectable? |
|---|---|---|
| `ffmpeg` | `{"filter": "<fragment>", "inputs": [[...]]}` | **Fully.** You can read a stored plan and see the exact filtergraph that will run. |
| `frame` | `{"op": "<registry key>"}` | **Only nameable.** There is no inspectable rendering of "run this Python function". |
| `external` | `{"tool": "<registry key>"}` | Only nameable, same reason. |

Two consequences follow, and both are load-bearing.

**Security.** The `frame` and `external` payloads name a *registry key*, never a `module:attr` import path. A plan is a document, documents arrive from places, and a document that can name `os:system` is a remote-code-execution primitive wearing a schema tag. Resolution goes through the registry or it does not happen.

**Identity.** An ffmpeg step's compiled fragment is itself a faithful identity — change the LUT path or the posterise level and the string changes. A frame step has no such string, so its identity has to come from `(impl, impl_version, params)`. `plan_hash` folds both, which covers each case with the same formula.

### The cost unit is CPU-seconds

Not dollars, obviously; but also not wall-clock seconds (which depend on worker count, an executor concern) and not a realtime multiple (which is derived, so it is a property and not a field). **CPU-seconds** is the unit an implementation can honestly estimate, is additive across steps, and converts to both of the others with information the caller already has.

Measured on this machine — Apple Silicon, darwin 24.6.0, Python 3.12.12, `opencv-python-headless` 4.13.0.92, ffmpeg 8.1 (homebrew, `--enable-gpl --enable-version3`), single-threaded throughout:

| operation | resolution | s/frame |
|---|---|---|
| `cv2.pyrMeanShiftFiltering(sp=12, sr=60)` | 1280×720 | 0.582 |
| `cv2.pyrMeanShiftFiltering(sp=12, sr=60)` | 640×360 (scale 0.5) | 0.232 |
| `cv2.pyrMeanShiftFiltering(sp=12, sr=40)` | 960×540 (scale 0.75) | 0.695 |
| `lut3d` (33³ `.cube`) — marginal over decode | 1280×720 | 0.0087 |
| `lutrgb` posterise — marginal over decode | 1280×720 | 0.00107 |

Method for the ffmpeg rows: 300 frames of `testsrc2`, `-threads 1 -filter_threads 1`, output to `-f null -`; decode-only baseline 0.65 s user, `lut3d` alone 3.27 s, `lutrgb` alone 0.97 s, both together 3.51 s. The marginal figures are the differences.

Two findings come out of that table, and both shape the API:

**The flatten stage costs ~27× the LUT stage** at the shipped setting (0.232 vs 0.0087 s/frame). That ratio is why costing a Look before running it is worth a type: the two stages look equally like "a step" in a filter list and differ by more than an order of magnitude in what they will do to your afternoon.

**A per-megapixel rate is a fiction for `pyrMeanShiftFiltering`.** The same three measurements give 0.63, 1.01 and 1.34 s/Mpx — it is not linear in area, and it varies with `sr` and with content. So `estimate()` **must** be allowed to return `None`, and a measured estimate is per `(impl, params, resolution)`. This is falaw's `estimated_cost_usd: Optional[float]` and its "`None` means unknown, never free" rule arriving from a completely different direction, which is a good sign the rule is real and not a fal-specific accident.

### `LookPlan`'s cost arithmetic

falaw's quartet, transposed:

- `total_cpu_seconds` — coerces unknown to `0.0`, so the sum stays a total function and plans compose. Documented as a **lower bound**, exactly as `nw.TransformResult.cost_usd_actual` documents itself.
- `known_cpu_seconds` + `unknown_step_count` — the honest pair a gate reads together. "1138 CPU-seconds *plus an unknown amount spread over N steps*" is a sentence; "1138 CPU-seconds" alone is a quote you should not have given.
- `has_unknown_costs` — the boolean a gate refuses on.
- `realtime_factor` — returns **`None`** when anything is unknown.

That last asymmetry is deliberate and I want it on the record. A *sum* must be total to compose. A single headline ratio that a human will read and act on must not fabricate: quoting a lower bound as if it were the answer is the reelee#208 failure mode, where a `$0.00`-because-unknown read as "under the threshold, spend freely" [12].

**Deliberately not modelled: peak memory and streaming shape.** Those are the executor's invariant — muvid's `assemble.py` earned its bounded-memory rule after 30-cut OOM kills — and a plan that claimed to predict them would be an invitation to write the convenience `looks.render()` that the kickoff forbids [14]. `LookPlan.backends` tells an executor that it needs more than a filtergraph; it does not tell it how to be careful.

---

## 7. Q5 — serialisation, and the migration story

Two schema tags, because there are two documents with independent lifecycles: `looks.look/v1` and `looks.plan/v1`. Each carries a `version` int in-band as well, following `burns` [3].

**The additive-vs-breaking rule**, taken from `artful` [7], `lacing` [5] and `falaw` [1] and written once at the top of the serialisation section of the module:

- Adding an **optional field with a default** is a *tolerated-default addition*. It is always written, and the reader defaults it when absent — so a document from before the field parses here, and a document written here parses under an older build, which simply never reads the extra key. **No tag bump, no migration.** This is exactly how falaw added `CallPlan.backend`, and the precedent is worth copying because it is the case that comes up constantly.
- **Renaming, removing, retyping or re-defaulting** a serialised field is breaking: bump the tag, and land the migration together with the downstream update.
- An **unrecognised tag is refused loudly**; a **missing tag is tolerated as v1**, so hand-written Looks stay easy.

**There is no migration registry at v1, and that is a decision rather than an omission.** A registry with zero entries is a stub, and the standing rule is to declare a seam only when its replacement exists. What must exist at v1 is the *discipline* — the tag, the in-band version, and the loud refusal — which is what makes a migration possible later. What that later registry must look like is already known, and it is worth writing down now so nobody re-derives it: it must be keyed on **`(kind, from_version)`**, not on `(from, to)` alone. `an` paid for that lesson with an#77 — two document kinds sitting at the same version number, a `(from, to)`-keyed registry that could not tell them apart, and consequently the *wrong migration silently running against the wrong document*. Nothing collides; the wrong function simply runs [6]. `looks` versions two kinds independently from day one, so it is a live hazard here, not a borrowed one.

There is a second reason not to reach for `lacing.register_migration` [5] even though it exists and is good: it would be a hard dependency, and `looks` declares none. When the day comes, the ~40 lines of an-style per-kind chained registry are stdlib.

---

## 8. Q6 — identity and the cache key

Three levels, deliberately separated. `falaw` has the same split (`plan_hash` for idempotency vs. the per-call content key) and its docstring goes out of its way to say the two "key on different bytes and must not be assumed to agree" [1]; naming all three up front is cheaper than discovering the distinction later.

**`look_hash(look)` — the authored intent.** Folds the Look's name and, per step, the capability name, the parameters (Refs included, by name), the span, and any `impl`/`backend` pin. Stable across machines and across registries. Excludes `metadata` (labelling) and `max_tier` (a permission, not a request). Answers *"is this the same look?"*

**`plan_hash(plan)` — the compiled pipeline.** Folds, per step: the **implementation key and its version**, the resolved parameters, the span, and the compiled payload; plus the clip geometry. Answers *"will this produce the same pixels from the same input?"*

Four things enter or stay out on purpose:

- **The implementation binds, not the capability name.** Two implementations of `"flatten"` produce different pixels. The name says what was asked; `impl`/`impl_version` say what answers. Note this inverts falaw, which *does* hash its `tool` alongside its `application` — correctly, because there a tool→application dispatch is itself part of the identity. Here the dispatch has already happened by the time a `Step` exists.
- **`impl_version` is folded unconditionally**, dropping nw's omit-if-default sentinel. `looks` has no installed base of cache keys to protect, so the sentinel would buy nothing and cost a permanent subtlety. This is the clearest case in the whole design of *not* copying a sibling: omit-if-default is a migration device, not a design principle.
- **Clip geometry is in**, because a compiled payload names pixels (`scale=`, `s=WxH`) and because the measured evidence says the flattening round trip is defined at a specific resolution.
- **Tier is out.** Relicensing an implementation changes what you are *allowed* to run, never what it renders. The audit trail for that lives in `plan_to_dict`, not in the identity of the pixels.
- **Probe is out**, per §5.

**`output_key(plan, source_digest)` — the content-addressed key of the result.** Pure string arithmetic over `plan_hash` and a digest of the source's **bytes**. That signature is falaw's D1 defect stated as a type: keying on a *location* means a byte-identical regeneration upstream misses the cache forever, and a changed file at the same path hits it wrongly. `looks` computes the formula and refuses to open the file — reading bytes is execution, and this package declares no dependencies and runs nothing. That keeps the executor honest about where the digest came from, which is where it should be honest.

---

## 9. Q7 — how an implementation declares itself, and what a refusal looks like

`ImplRef` is the declaration: `effect` (capability served), `impl` (unique key, `<effect>.<backend>.<variant>`), `backend`, `tier`, `impl_version`, `timeline`. Pure data, and only the data travels into a `Step` — which is why a stored `LookPlan` can be audited for licence **with nothing imported**. The registry pairs it with two callables (`compile` and `estimate`) that never leave the registry module.

`select_impl(effect, candidates, *, max_tier)` is the whole selection and refusal rule, and it is a pure function over a supplied candidate list so it can be unit-tested and doctested without a registry:

1. Keep candidates whose `effect` matches; honour an `impl` or `backend` pin.
2. Drop everything above `max_tier`.
3. Among survivors prefer the **lowest tier**, ties by registration order.
4. No candidates at all → `UnknownEffect`, naming the registered capabilities (muvid's message shape [2]).
5. Candidates existed but all exceeded the ceiling → **`LicenceRefusal`**.

**Step 3 is a judgement and deserves its counter-argument.** The lowest-tier implementation may well be the *worse-looking* one. The defence: quality is not knowable to a registry and licence is, so the automatic choice should be the safe one, and a caller who wants a specific implementation for quality reasons pins `impl=`. The alternative — prefer registration order, i.e. "whatever the plugin author registered first" — makes the default depend on import order, which is the least legible input possible.

**`Tier.UNKNOWN` needs no special case.** It sits at the top of the ladder, so it is unreachable unless the ceiling is literally `Tier.UNKNOWN` — a spelling nobody writes by accident. "Unknown is a refusal" falls out of the ordering rather than being a branch someone can forget.

**What the refusal message must contain**, and this is not decoration. reelee's hard-won framing is that *a gate can only refuse; a free door is what lets the caller find out first*, and that the door has to be a mechanism rather than a convention, because prose gets edited away [12]. Here the error message **is** the door, and it is composed rather than written:

```
looks.spec.LicenceRefusal: no implementation of 'cartoon' is within the 'permissive' ceiling.
Rejected: cartoon.ffmpeg.posterize (copyleft-tool), cartoon.torch.animeganv2 (noncommercial).
Raise it deliberately with look.with_max_tier(Tier.COPYLEFT_TOOL), or pick another effect.
```

Every element is derived from the candidates: each rejected implementation with its rung, and the *exact* call that would widen the ceiling to the cheapest one that works. A caller is never left to guess how far up to move, and never told to move further than necessary.

**A sixth refusal, and it is verified rather than hypothesised.** `ImplRef.timeline` says whether an implementation can be gated to a span. In ffmpeg 8.1's filter table, `lut3d`, `lutrgb`, `eq`, `hue`, `curves`, `unsharp`, `gblur` and `colorchannelmixer` all carry the `T` (timeline support) flag — and **`scale` does not** [8]. So an `Effect.at` on a geometry filter cannot compile to `enable=between(t,...)`, and the only honest options are to refuse or to silently apply the effect to the whole clip. `SpanUnsupported` refuses. Silently widening a span is the kind of bug that produces a video nobody can explain.

---

## 10. Rejected alternatives, consolidated

| Rejected | Because |
|---|---|
| A `tier` field on `Effect` or a `tier=` argument to a compile call | The party asking for the effect would be asserting the answer. The refusal becomes theatre. |
| Checking the registry in `Effect.__init__` | Makes a Look unreadable on a machine without the plugin — the failure lacing's schema discipline exists to prevent. The check belongs where the decision to run is made. |
| Callable parameter values (option a) | Kills the Look's persistability, diffability and cache identity. `burns` accepts a callable easing and refuses at `to_dict`; tolerable for a tiny vocabulary that rarely travels, intolerable for the fields that *are* the identity. Also arbitrary code in a document. |
| A `Resolver` registry (option c) | No second resolution strategy exists to point at. `Ref` is the degenerate case, and a `$resolver` marker is an additive extension when one is measured. |
| Caller-resolves-only (option d) | Makes the Look not the whole recipe and pushes the same lookup into every caller. Retained as a supported mode: `resolve` is the identity on a Ref-free Look. |
| A distinct `ResolvedLook` type | Doubles the serialisation and migration surface to express a predicate. `Look.is_resolved` plus a `Step.__post_init__` guard is the same guarantee for nothing. |
| `omit-if-default` on `impl_version` | A migration device for an installed base of cache keys. `looks` has none; copying it here would be cargo cult, and it costs a permanent subtlety. |
| A `Look.render()` / `looks.render(clip, look)` convenience | The kickoff forbids it and is right: it *will* get used and it *will* rebuild one big `-filter_complex`, discarding the bounded-memory invariant muvid's `assemble.py` won after 30-cut OOM kills. |
| Modelling peak memory in the plan | Same reason. Predicting it is the first step toward owning it. |
| `xdol.Registry` for the effect registry | It is the federation's pattern, and it is a dependency. Zero hard dependencies is a non-negotiable; ~20 lines of dict with `on_conflict="error"` semantics reproduces what is needed. Worth a note in the README so the divergence is deliberate. |
| Frame numbers, or `RationalTime`, for `Span` | Frame numbers need an fps and do not survive a reframe. `RationalTime` is lacing's rule for lacing annotations; `an` already settled that float seconds are right at an IR boundary, and ffmpeg's `enable=` takes seconds. |
| Hashing the whole `probe` into `plan_hash` | Keys a plan on measurements it never consumed. The consumed ones are already in the resolved parameters. |
| A `module:attr` import path in a `frame` payload | A plan is a document; a document that can name `os:system` is an RCE primitive with a schema tag. Registry keys only. |

---

## 11. A licence finding this session turned up, which the design has to absorb

While verifying that `flatten.opencv.meanshift` could honestly be declared `Tier.PERMISSIVE`, I checked what the OpenCV wheel actually ships. **`opencv-python-headless` 4.13.0.92 and `opencv-python` 4.12.0.88 both bundle a GPL-configured FFmpeg.** Verified directly, not inferred:

- Both wheels' `RECORD` lists `cv2/.dylibs/libx264.164.dylib` (identical sha256 in both), alongside `libx265.215.dylib`.
- `otool -L cv2/.dylibs/libavcodec.61.19.101.dylib` shows `@loader_path/libx264.164.dylib` and `@loader_path/libx265.215.dylib`.
- `otool -L cv2/cv2.abi3.so` shows it links `libavcodec.61` and `libavformat.61` directly.
- The build-configuration string inside `libavcodec` reads `--prefix=/opt/homebrew/Cellar/ffmpeg/7.1.1_3 ... --enable-version3 ... --enable-gpl ... --enable-libx264 --enable-libx265 ...`.
- Meanwhile the distribution's `License` metadata field says `Apache 2.0`, its own `LICENSE.txt` is MIT (covering the wrapper), and the 3575-line `LICENSE-3RD-PARTY.txt` carries full LGPL-2.1 and LGPL-3 texts and a header stating "FFmpeg is redistributed within all opencv-python packages".

This is reelee-web's rule 1 in the wild — *the licence text is the authority, the metadata field is not* [13] — and it means the kickoff's non-negotiable, as written, is incomplete: `av` and `imageio-ffmpeg` are named, but `opencv-python` is the third member of that set and is the one nobody suspects.

**I am not drawing the legal conclusion here** — that is the licence-tier note's job, and the effective licence of a combination is exactly the kind of claim that should not be settled by an agent reading `strings` output. What the *type design* has to absorb is narrower and does not wait on the legal question: it forces a definition of what a tier is *about*, because two different questions were quietly sharing one field.

- **What running this step causes to execute.** `pyrMeanShiftFiltering` lives in OpenCV core (Apache-2.0) and never enters libavcodec, so a flatten step is `PERMISSIVE`.
- **What you must redistribute.** If you ship `opencv-python`, you ship `libx264`.

`looks` tiers the first, because that is the question a caller of `looks` is asking ("may I use this effect on a commercial job?"), and the `Tier` docstring now says so in as many words. The second is a distribution ledger belonging to whoever assembles the wheel, and if it ever needs to be machine-checkable it is an additive `requires` field on `ImplRef` — declared the day a second consumer exists, and not before.

---

## 12. Appendix — the registry sketch, and the Que Calor look compiling end to end

Not part of the deliverable, but written and run so that the spec types are demonstrated carrying a real look rather than a toy. This is roughly what `looks/registry.py` + `looks/compile.py` become. Its cost rates are the measured figures from §6.

```python
"""Appendix sketch: the registry + compile layer that sits on top of spec.py.

Shown to prove the spec types carry a real look end to end; not the deliverable.
"""

from dataclasses import dataclass
from typing import Any, Callable, Optional

from looks.spec import (
    ClipSpec,
    Effect,
    ImplRef,
    Look,
    LookPlan,
    Ref,
    Step,
    Tier,
    resolve,
    select_impl,
)


@dataclass(frozen=True)
class EffectDef:
    """An :class:`ImplRef` plus the two callables the registry needs."""

    ref: ImplRef
    compile: Callable[[ClipSpec, dict, Optional[object]], dict]
    estimate: Callable[[ClipSpec, dict, Optional[object]], Optional[float]]
    defaults: dict


_REGISTRY: dict[str, EffectDef] = {}


def register_effect(defn: EffectDef) -> EffectDef:
    if defn.ref.impl in _REGISTRY:
        raise ValueError(f"register_effect: {defn.ref.impl!r} is already registered.")
    _REGISTRY[defn.ref.impl] = defn
    return defn


def compile_look(look: Look, clip: ClipSpec, *, probe=()) -> LookPlan:
    look = resolve(look, probe)
    cands = tuple(d.ref for d in _REGISTRY.values())
    steps = []
    for effect in look.steps:
        ref = select_impl(effect, cands, max_tier=look.max_tier)
        defn = _REGISTRY[ref.impl]
        unknown = set(effect.params) - set(defn.defaults)
        if unknown:
            raise ValueError(
                f"{ref.impl!r} has no parameter(s) {sorted(unknown)}; "
                f"declared: {sorted(defn.defaults)}."
            )
        params = {**defn.defaults, **effect.params}
        steps.append(
            Step(
                effect=effect.name,
                impl=ref,
                params=params,
                at=effect.at,
                payload=defn.compile(clip, params, effect.at),
                cpu_seconds=defn.estimate(clip, params, effect.at),
                metadata=effect.metadata,
            )
        )
    return LookPlan(
        steps=tuple(steps),
        clip=clip,
        look_name=look.name,
        max_tier=look.max_tier,
        probe={
            v.key: (probe or {}).get(v.key, v.default)
            for e in look.steps
            for v in e.params.values()
            if isinstance(v, Ref)
        },
    )


def _frames(clip: ClipSpec, at) -> Optional[int]:
    if at is not None and at.duration_s is not None:
        return int(round(at.duration_s * clip.fps))
    return clip.frame_count


# --- three implementations: one frame op, two ffmpeg filters ----------------

# Measured on this machine (opencv 4.13.0, Apple Silicon, single thread):
# 1280x720 -> 0.582 s/frame; 640x360 (scale 0.5) -> 0.232; 960x540 (0.75) -> 0.695.
# Deliberately NOT a per-megapixel rate: the observed rates are 0.63, 1.01 and
# 1.34 s/Mpx, so a linear model would be a fiction. A table, and None off it.
_MEANSHIFT_S_PER_FRAME = {
    (1280, 720, 0.5): 0.232,
    (1280, 720, 0.75): 0.695,
    (1280, 720, 1.0): 0.582,
}

register_effect(
    EffectDef(
        ref=ImplRef(
            effect="flatten",
            impl="flatten.opencv.meanshift",
            backend="frame",
            tier=Tier.PERMISSIVE,  # opencv-python is Apache-2.0 (MIT core)
        ),
        defaults={"scale": 0.5, "sp": 12, "sr": 60},
        compile=lambda clip, p, at: {"op": "flatten.opencv.meanshift"},
        estimate=lambda clip, p, at: (
            None
            if _frames(clip, at) is None
            or (clip.width, clip.height, p["scale"]) not in _MEANSHIFT_S_PER_FRAME
            else _frames(clip, at)
            * _MEANSHIFT_S_PER_FRAME[(clip.width, clip.height, p["scale"])]
        ),
    )
)

# Measured over 300 frames of 1280x720 (0.9216 Mpx), `-threads 1
# -filter_threads 1`, output to `-f null -`, ffmpeg 8.1. Decode-only baseline
# 0.65 s user; lut3d alone 3.27 s; lutrgb alone 0.97 s. Marginal filter cost:
# lut3d 8.7 ms/frame, lutrgb 1.07 ms/frame.
_LUT3D_S_PER_MPX_FRAME = 0.0087 / 0.9216
_LUTRGB_S_PER_MPX_FRAME = 0.00107 / 0.9216

register_effect(
    EffectDef(
        ref=ImplRef(
            effect="lut3d",
            impl="lut3d.ffmpeg.cube",
            backend="ffmpeg",
            tier=Tier.COPYLEFT_TOOL,
        ),
        defaults={"cube": None, "interp": "tetrahedral"},
        compile=lambda clip, p, at: {
            "filter": _gate(f"lut3d=file={p['cube']}:interp={p['interp']}", at)
        },
        estimate=lambda clip, p, at: (
            None
            if _frames(clip, at) is None
            else _frames(clip, at) * clip.megapixels * _LUT3D_S_PER_MPX_FRAME
        ),
    )
)

register_effect(
    EffectDef(
        ref=ImplRef(
            effect="posterize",
            impl="posterize.ffmpeg.lutrgb",
            backend="ffmpeg",
            tier=Tier.COPYLEFT_TOOL,
        ),
        defaults={"levels": 18},
        compile=lambda clip, p, at: {"filter": _gate(_posterize(p["levels"]), at)},
        estimate=lambda clip, p, at: (
            None
            if _frames(clip, at) is None
            else _frames(clip, at) * clip.megapixels * _LUTRGB_S_PER_MPX_FRAME
        ),
    )
)


def _posterize(n: int) -> str:
    expr = f"trunc(val/{n})*{n}+{n // 2}"
    return f"lutrgb=r='{expr}':g='{expr}':b='{expr}'"


def _gate(fragment: str, at) -> str:
    if at is None:
        return fragment
    lo = "0" if at.start is None else f"{at.start:g}"
    hi = "inf" if at.end is None else f"{at.end:g}"
    return f"{fragment}:enable='between(t,{lo},{hi})'"
```

Driving it with the Que Calor look, against the real output geometry (1280×720, 30 fps, 156.968 s = 4709 frames):

```
c01/c02  total=1138.5 CPU-s  rt=7.25x   ['flatten=1092.5', 'lut3d=41.0', 'posterize=5.0']  plan=427355af58a0
c03      total=3318.8 CPU-s  rt=21.14x  ['flatten=3272.8', 'lut3d=41.0', 'posterize=5.0']  plan=8cd3abc98d92
one look_hash for both: b767465ae062
```

That output is the design's whole argument in three lines. **One Look, one `look_hash`** — the Que Calor look is a single shippable artifact. **Two plans, two `plan_hash`es** — because the same look resolves differently against different clips, exactly as the measured constraint demands, and each gets its own cache identity so neither can serve the other's frames. And **the cost is known before anything runs**: 7.25 CPU-seconds per output second at the shipped setting, 21.14 for the clip that needed the gentler flattening. On eight workers those are roughly 2.4 and 6.9 wall-clock minutes; that is the difference between a coffee and a lunch, and you get to know which before you commit.

Two refusals, from the same run:

```
>>> compile_look(QUE_CALOR.with_max_tier(Tier.PERMISSIVE), clip, probe=...)
looks.spec.LicenceRefusal: no implementation of 'lut3d' is within the 'permissive' ceiling.
Rejected: lut3d.ffmpeg.cube (copyleft-tool).
Raise it deliberately with look.with_max_tier(Tier.COPYLEFT_TOOL), or pick another effect.

>>> compile_look(QUE_CALOR, clip)          # no probe
looks.spec.UnresolvedParameter: step 0 ('flatten') parameter 'scale' needs probe key 'flatten_scale',
which was not supplied and has no default. Measure it, pass probe={'flatten_scale': ...},
or give the Ref an explicit default.
```

---

## 13. What this note does not settle

- **The tier vocabulary itself.** Five rungs are proposed and given an ordering that makes the non-negotiables fall out as comparisons, but the mapping from real licences onto rungs — and whether five is the right number — belongs to the licence-tier note. `TIER_ORDER` is one tuple; changing it is a one-line edit plus a schema decision about the stored strings.
- **Whether geometry belongs here at all.** The kickoff's own open question — should `burns` become a backend, or does geometry-over-time stay in `burns` and only *pixel* effects live here? — is not answered by this design, but it is not blocked by it either. `ImplRef.timeline=False` already exists because `scale` needs it, and a `burns` implementation would be an `external` or `ffmpeg` backend like any other. The `mixing/video/video_util.py` geometry tier can arrive as effects (`fit`, `fill`, `social`) without a second spec type; the tension the kickoff names — that `video_util.py` is moviepy-through-and-through while `looks` declares zero dependencies — is an *implementation* problem for that backend, not a spec problem, because the moviepy import would live behind an `ImplRef` in an optional extra.
- **Whether normalisation and stylization share one vocabulary.** They compile to the same insertion point and the type system does not distinguish them, which is the tempting answer and probably right — but that should be said deliberately somewhere, not inferred from the absence of a field.
- **`EffectDef` parameter validation.** The sketch refuses an undeclared parameter against a `defaults` mapping, which is the `z.strictObject` lesson (an undeclared key silently stripped is worse than an error). Whether that is enough, or whether a schema is eventually wanted, is unresolved — but any schema must stay stdlib, so pydantic is out.
- **Whether `LookPlan.__add__` should exist at all.** It is there for symmetry with `falaw.Plan` and it refuses to concatenate plans compiled against different clips. It has no demonstrated caller.

---

## 14. Verification log

Every claim in this note about the local environment was produced by running something. What follows is what I ran.

| Claim | How verified |
|---|---|
| The proposed `spec.py` is importable, stdlib-only, and its doctests pass | `doctest.testmod(looks.spec, optionflags=doctest.ELLIPSIS)` → `TestResults(failed=0, attempted=80)` on CPython **3.12.12** and **3.10.13**. Deliberately run *without* `IGNORE_EXCEPTION_DETAIL` (which the repo's `pyproject.toml` enables and which would have hidden every exception-message mismatch); one mismatch was found that way and fixed. |
| It satisfies the repo's lint config | `ruff check --select D100 --ignore D203,E501,B905 --target-version py310` → clean. (`D100` is the only rule the repo selects.) |
| `pyrMeanShiftFiltering` cost figures | Direct `time.perf_counter()` around single calls on one 1280×720 frame from the Que Calor source, `opencv-python-headless` **4.13.0.92**, numpy 2.2.6. Single-threaded. |
| `lut3d` / `lutrgb` cost figures | `/usr/bin/time -p ffmpeg -v error -threads 1 -filter_threads 1 -i t.mp4 -vf <chain> -f null -` over 300 frames of `testsrc2` at 1280×720; `user` time differenced against a decode-only baseline. ffmpeg **8.1**. |
| Timeline (`T`) flags on ffmpeg filters | `ffmpeg -hide_banner -filters` on **8.1**; the legend in its own header defines `T.. = Timeline support`. `scale` shows `..`; `lut3d`, `lutrgb`, `curves`, `gblur`, `unsharp`, `colorchannelmixer` show `TS`; `eq`, `hue` show `T.`. |
| The local ffmpeg is GPL-configured | `ffmpeg -version` → `configuration: ... --enable-gpl --enable-version3 ... --enable-libx264 --enable-libx265`. |
| Que Calor output geometry and duration | `ffprobe -show_entries format=duration` on the delivered renders → 156.968005 s; the renderer's own constants are `W, H, FPS = 1280, 720, 30`. |
| `opencv-python` ships `libx264` and a GPL-configured FFmpeg | `RECORD` of both dist-infos; `otool -L` on `libavcodec.61.19.101.dylib` and on `cv2.abi3.so`; `strings` on `libavcodec`/`libavutil` for the build configuration; `head` of `LICENSE.txt` and `grep` of `LICENSE-3RD-PARTY.txt`. |
| The end-to-end compile figures in §12 | Ran the appendix module and printed the plans. Reproducible from the two code blocks in this note plus the cost table in §6. |

**Explicitly not verified in this session, and inherited from the shared kickoff context** — each is load-bearing somewhere in the design and each should be independently confirmed by the licence-tier note before anything ships on it:

- That **AnimeGANv2 and White-box Cartoonization are non-commercial**. Used as the illustrative `NONCOMMERCIAL` examples in `Tier`'s docstring. **Unverified here.**
- That **`av`'s wheel bundles libx264/libx265 GPL dylibs under BSD-3 metadata** and that **`imageio-ffmpeg` bundles an `--enable-gpl` binary**. Used to place both at `COPYLEFT_LINK`. **Unverified here** — though the OpenCV finding in §11 is direct evidence that this class of defect is real and common.
- That **`pip install burns` already redistributes a GPL ffmpeg via moviepy → imageio-ffmpeg**. **Unverified here.**
- That the effective licence of the OpenCV wheel's *combination* is GPL. I verified the constituent facts in §11; the legal conclusion is **not** mine to draw and is marked as such there.

One further caveat on the measurements: the `pyrMeanShiftFiltering` timings are three points, on one machine, on one image. They are enough to establish that a linear per-megapixel model is unsafe — which is the design-relevant conclusion — and are **not** a characterisation of the operator. Any cost table shipped in the package should be measured per machine, or the estimate should return `None`.

---

## REFERENCES

1. falaw — `Plan` / `CallPlan` / `plan_hash` / `plan_to_dict`. Local source: `$PP/t/falaw/falaw/plan.py`; canonicalisation in `$PP/t/falaw/falaw/canonical.py`.
2. muvid — `VisualPlan`, `register_visual`, `resolve_visual`. Local source: `$PP/t/muvid/muvid/visualize/visuals.py`.
3. burns — `BurnsPath`, `evaluate`, `to_dict` / `from_dict`, `SPEC_VERSION`. Local source: `$PP/t/burns/burns/path.py`.
4. nw — `Transform` Protocol, `BaseTransform`, `register_transform`, `stamp_transform_identity`, `cache_key`, `DFLT_IMPL_VERSION`. Local source: `$PP/t/nw/nw/transforms/__init__.py`.
5. lacing — `register_migration` / `migrate`, single-step chained body-schema migrations. Local source: `$PP/t/lacing/lacing/schema.py`.
6. an — per-document-kind migration registry and the an#77 namespace-conflation lesson. Local source: `$PP/t/an/an/ir/migrate.py`.
7. artful — "THE MIGRATION-REQUIRED RULE": the federation's carve-out from *clean shape over backward compatibility*, and `tests/test_body_schema_stability.py`. Local source: `$PP/t/artful/CLAUDE.md`.
8. FFmpeg documentation — [Timeline editing](https://ffmpeg.org/ffmpeg-filters.html#Timeline-editing) and the filter list. Verified against the locally installed **ffmpeg 8.1**; the `T` flag is defined in `ffmpeg -filters`' own header.
9. OpenCV — [`pyrMeanShiftFiltering`](https://docs.opencv.org/4.x/d4/d86/group__imgproc__filter.html#ga9fabdce9543bd602445f5db3827e4cc0), image-filtering module. Behaviour measured against `opencv-python-headless` **4.13.0.92**.
10. Que Calor V2 stylizer — the validated chain and the per-source `MS_PARAMS` table. Local source: `~/Downloads/que_calor/work/style/render_v2c.py`, with `mklut.py` (the gradient-map LUT), `tonematch.py` (the L\* histogram match) and `stylize.py`.
11. thorwhalen/muvid — [issue #63](https://github.com/thorwhalen/muvid/issues/63), the `looks` proposal and the comment recording the measured per-source flattening constraint.
12. reelee — the unknown-cost / approval-gate rules, the estimate-twin "free door" mechanism, and the cassette-key lesson. Local source: `$PP/tt/reelee/CLAUDE.md`.
13. reelee-web — "the licence TEXT is the authority; the `package.json` field is not", and the build-time notice generator that enforces it. Local source: `$PP/tt/reelee-web/CLAUDE.md`, `scripts/licenses/`.
14. looks — the kickoff: non-negotiables, the two things to keep out, the measured Que Calor findings. Local source: `$PP/t/looks/KICKOFF.md`.
15. VideoLAN — [x264](https://www.videolan.org/developers/x264.html), GPL-2.0-or-later. Referenced for the §11 finding; the licence statement itself is **not** re-verified here.
16. Python — [`dataclasses`](https://docs.python.org/3/library/dataclasses.html): `frozen`, `slots` (3.10+), `kw_only` (3.10+), `replace`. Verified working on 3.10.13.

---

## Adversarial review (2026-09-02)

*An independent session re-ran every command in §14, fetched every external licence text, and attacked the design against the kickoff's non-negotiables. Nothing below rewrites the author's text; it records what survived and what did not.*

### Confirmed — re-verified independently, not taken on trust

- **The code is real.** Block 0 was re-extracted from this markdown by regex into `looks/spec.py` and run: `doctest.testmod(m, optionflags=doctest.ELLIPSIS)` → `TestResults(failed=0, attempted=80)` on CPython **3.10.13, 3.11.11, 3.12.12 and 3.13.2** (two more interpreters than claimed). An AST scan of the imports finds only `__future__, dataclasses, enum, hashlib, json, typing` — **stdlib-only, confirmed**. `ruff check --select D100 --ignore D203,E501,B905 --target-version py310` → *All checks passed*.
- **The ffmpeg timeline flags are exactly as stated** on the local 8.1: `lut3d lutrgb curves gblur unsharp colorchannelmixer` → `TS`; `eq hue` → `T.`; `scale` → `..`. Strengthening the finding: **`crop`, `pad` and `scale_vt` also carry no `T`**, so the whole geometry tier is un-gateable, not just `scale`.
- **The §12 pipeline reproduces exactly**: `total=1138.5 rt=7.25x` and `total=3318.8 rt=21.14x`, two distinct `plan_hash`es. `MS_PARAMS = {c01:(0.5,12,60), c02:(0.5,12,60), c03:(0.75,12,40)}`, `W, H, FPS = 1280, 720, 30` and `format=duration → 156.968005` all verified at source.
- **The ffmpeg cost figures reproduce within run-to-run noise**: baseline 0.52 s, lut3d 3.60, lutrgb 1.04, both 3.87 → **lut3d 10.3 ms/frame, lutrgb 1.73 ms/frame** against the note's 8.7 / 1.07. The flatten:LUT ratio lands at 22×–27× rather than exactly 27×; the qualitative point is untouched.
- **§11's OpenCV finding is correct in every particular.** Both wheels' `RECORD` list `cv2/.dylibs/libx264.164.dylib` and `libx265.215.dylib` at **identical sha256**; `otool -L libavcodec.61.19.101.dylib` → `@loader_path/libx264.164.dylib`, `@loader_path/libx265.215.dylib`; `cv2.abi3.so` links `libavformat.61 / libavcodec.61 / libswscale.8 / libavutil.59`; the embedded configuration reads `--prefix=/opt/homebrew/Cellar/ffmpeg/7.1.1_3 … --enable-version3 … --enable-gpl … --enable-libx264 --enable-libx265`; `METADATA` says `License: Apache 2.0`. This is the most valuable thing in the note.
- **The three claims §14 marked "unverified" are now verified**, and one is *worse* than stated:
  - `av` **16.0.1** — `License-Expression: BSD-3-Clause`, ships `av/.dylibs/libx264.165.dylib` + `libx265.215.dylib`, and `otool -L` shows its `libavcodec.62` linking both. **Refinement:** its bundled FFmpeg's configuration string contains `--enable-libx264 --enable-libx265` and **no `--enable-gpl` at all** (grep count 0), because PyAV patches `configure` to move those out of `EXTERNAL_LIBRARY_GPL_LIST` — so the binary *self-reports* LGPL-3 while linking GPL codec libraries. The wheel's dist-info mentions neither `x264` nor `GPL` outside the `RECORD` filenames.
  - `imageio-ffmpeg` **0.6.0** — `License: BSD-2-Clause`, ships a 49.4 MB `binaries/ffmpeg-macos-aarch64-v7.1` whose configuration contains `--enable-gpl --enable-libx264 --enable-libx265`.
  - `burns` **0.0.9** → `Requires-Dist: moviepy` (unconditional) → `moviepy` 2.2.1 → `Requires-Dist: imageio_ffmpeg>=0.2.0` (unconditional). `pip install burns` does redistribute that binary.
  - **White-box Cartoonization** — CC BY-NC-SA 4.0, verbatim: *"Commercial application is prohibited, please remain this license if you clone this repo"*. **AnimeGANv2** — README §License: *"made freely available to academic and non-academic entities for non-commercial purposes … please contact us via email to help you obtain the authorization letter"*.
- **Every ancestor claim checks out at source**: falaw's four cost properties, its omit-if-empty `key_extra` / omit-if-default `backend`, and `canonical_blob`'s no-fallback rule; nw's `stamp_transform_identity` with "every key ever issued stays byte-identical"; `burns/path.py:169,178` accepting a callable easing and raising at `to_dict`.
- **Recommendations 2, 3, 5, 6, 10 and 11 could not be broken.** `Ref` over callables, no-default-is-a-refusal, dropping the omit-if-default sentinel, the three identity levels with `output_key` taking a *digest*, registry-keys-not-import-paths, and `(kind, from_version)` for the future migration registry are all sound and well-argued.

### Refuted

**1 · FATAL — the ladder produces a mechanical false permission, and it disarms the kickoff's two named "never".** §4 claims that "never depend on `av`, never on `imageio-ffmpeg` stops being a rule in a document and becomes a comparison in the data". It does not. `COPYLEFT_LINK` sits *below* `NONCOMMERCIAL`, so a caller who raises the ceiling one rung for an unrelated reason — to admit one research model — silently admits both. Run against the proposed `select_impl`:

```
look = Look(steps=(Effect('cartoon'), Effect('decode'), Effect('encode')), max_tier=Tier.NONCOMMERCIAL)
  admitted: cartoon.torch.animeganv2
  admitted: decode.av.pyav
  admitted: encode.imageio.ffmpeg
```

The cause is that a **total order over incommensurable axes** is not a risk ladder: field-of-use ("may not be sold") is not "more copyleft than GPL". The sibling brief `06_licence_tiers.md` reaches the same conclusion independently and takes field-of-use off the ladder entirely as a separate opt-in. §13's framing — "`TIER_ORDER` is one tuple; changing it is a one-line edit" — badly under-scopes this.

**2 · FATAL — `ImplRef.tier` as a frozen constant is the wrong shape for the flagship backend.** The note declares it "the only place a tier is ever declared" and pins every ffmpeg implementation at `COPYLEFT_TOOL` because *this machine's* binary is GPL. Two measurements refute the shape:

- FFmpeg's own `configure` at tag `n8.1` gates licences **per filter**: `eq_filter_deps="gpl"`, while `lut3d`, `lutrgb`, `curves`, `gblur`, `unsharp` and `colorchannelmixer` have no gpl dependency at all. So `COPYLEFT_TOOL` is a **false refusal** for most of the colour vocabulary. Worse: the note's own `Look` docstring uses `Look(name="grade", steps=(Effect(name="eq"),), max_tier=Tier.PERMISSIVE)` as its exemplar of a commercial-safe Look — `eq` is the one filter in that list that can never be permissive under any ffmpeg.
- The tier of a *shell-out* backend is an environment fact. `ffmpeg -L` on the local binary — the least-editable statement, per this repo's own `looks/environment.py` — says **"GNU General Public License … version 3 or later"**, which is both stronger than the note reports and obtained a different way: §14 read the `configuration:` line, which `environment.py` documents as editable *and which PyAV demonstrably edits* (see above). Same `ImplRef`, different machine, different truth.

`06_licence_tiers.md` states the correction directly: *"The tier is resolved from the environment rather than declared as a constant, because it genuinely varies"* — `resolved_terms = declared_terms ⊔ probe(provider)`, with `ImplRef.tier=None` for probed providers. The two notes are in direct structural conflict on this design's headline decision.

**3 · SERIOUS — `select_impl` checks `timeline` after choosing, so recommendation 9 refuses runs that should succeed.** Two candidates for one spanned effect, both within the ceiling, one gateable:

```
ImplRef('blur.a.nogate', tier=PERMISSIVE,    timeline=False)
ImplRef('blur.b.gated',  tier=COPYLEFT_TOOL, timeline=True)
select_impl(Effect(name='blur', at=Span(0.0, 2.0)), cands)
→ SpanUnsupported: 'blur.a.nogate' cannot be gated to a time span
```

`blur.b.gated` was available, within the ceiling, and could do the job. `timeline` is a hard *requirement*, so it must filter in step 1, not be re-checked on the winner.

**4 · SERIOUS — the `Tier`/`str` comparison hole is not closed.** Overriding all four operators to return `NotImplemented` for a non-`Tier` hands the comparison to the reflected `str` method, which is exactly the lexicographic path the comment says was dodged. `Tier` subclasses `str` *precisely so the wire form is a plain string*, so a ceiling arriving from JSON or a config as `str` is the normal case. 8 of 25 pairs diverge from the ladder, **4 of them in the false-permission direction**:

```
COPYLEFT_TOOL <= 'permissive'    → True   (ladder: False)
COPYLEFT_LINK <= 'permissive'    → True   (ladder: False)
COPYLEFT_LINK <= 'copyleft-tool' → True   (ladder: False)
NONCOMMERCIAL <= 'permissive'    → True   (ladder: False)
```

Raise `TypeError` instead of returning `NotImplemented`, or stop subclassing `str` (nothing needs it — every serializer already writes `.value`).

**5 · SERIOUS — `plan_hash`'s promise is false, because `ClipSpec` omits the clip's colour state.** §8 says `plan_hash` answers *"will this produce the same pixels from the same input?"*. `ClipSpec` carries `width, height, fps, duration_s` and nothing else. This repo's own `00b_colour_range_trap_evidence.md`, produced the same day, measured the same LUT under the two colour-range assumptions differing on **99.6% of bytes, max 15/255, mean 6.05/255**, and concluded *"a clip's `color_range` is part of its measured state, and untagged is a third value"*. The words `color_range`, `pix_fmt` and `color_space` appear **zero times** in this note.

**6 · SERIOUS — the cost estimate is keyed on parameters that do not include the one that dominates it.** `_MEANSHIFT_S_PER_FRAME` is keyed on `(width, height, scale)` and ignores `sr`. Measured here on a real photographic frame at 1280×720, `sp=12`, single-threaded, opencv 4.13.0:

```
sr=30 → 0.783 s/frame     sr=40 → 0.637     sr=60 → 0.408
```

`sr` moves the true cost by **1.9× at fixed geometry**, and the sketch returns the identical `3318.8 CPU-s` for `sr=40` and `sr=60`. This is the note's own D1 shape — an identity that omits something that changes the answer — applied to cost.

**7 · SERIOUS — the appendix cannot express the look it claims to compile.** `render_v2c.py` calls `cv2.pyrMeanShiftFiltering(small, sp, sr, maxLevel=2)`. `maxLevel` is absent from `defaults={"scale","sp","sr"}`, and `compile_look` hard-refuses undeclared parameters:

```
maxLevel -> ValueError: 'flatten.opencv.meanshift' has no parameter(s) ['maxLevel']; declared: ['scale', 'sp', 'sr'].
```

`maxLevel` changes the pixels (and the cost — 0.184 vs 0.143 s/frame at 640×360, sr=60), so it must be in `params` and therefore in `plan_hash`.

**8 · The published §12 numbers are not reproducible from the Look literal the note prints.** Running the note's own `Effect(name="flatten", params={"scale": Ref("flatten_scale"), "sr": 60})` gives `look_hash 13027b859dcd` and c03 `plan_hash 7abf6dedbde5`, not the reported `b767465ae062` / `8cd3abc98d92`. A search over candidate literals recovers the actual one: **`"sr": Ref("flatten_sr")`** — two Refs, not one. The design point ("one `look_hash`, two `plan_hash`es") is *true and stronger* than shown, since the shipped look defers `sr` per clip as well; the printed code is simply not the code that produced the numbers, and as printed it hard-codes `sr: 60` — one global default for a parameter the measured evidence says is per-source (60 / 60 / 40).

**9 · Claim 4's conclusion survives; its stated reason does not.** The three points varied resolution *and* `sr` *and*, through the resize, image content. Isolating area at `sr=60` on a real frame: **0.804 → 0.567 → 0.443 → 0.307 s/Mpx** across 0.23 → 2.07 Mpx — genuinely sub-linear, so `estimate()` must indeed be allowed to return `None`. But on a smooth synthetic frame the same operator is *perfectly* linear (0.059 / 0.055 / 0.058 s/Mpx), so the non-linearity is a property of **content**, not of area, and the note names the wrong variable.

**10 · The ffmpeg per-megapixel rate was extrapolated from one resolution** — the very linearity assumption the note refutes two paragraphs earlier, with no test. Tested here, `lut3d` *is* approximately linear (0.01244 / 0.01132 / 0.01043 s/Mpx over a 9× area range), so the model holds — but the shipped constant `0.0087/0.9216 = 0.00944` under-estimates by 10–30%, and the measured `lutrgb` marginal (1.73 ms/frame) is 62% above the shipped 1.07.

**11 · Smaller, all reproduced:**

- `_canonical_blob` takes only half of falaw's rule. falaw raises the typed `FalNonCanonicalArgument` via `ensure_canonical`; this lets a bare `TypeError` escape. The most likely authoring mistake in this domain — `params={"cube": Path(...)}` — dies as `TypeError: Object of type PosixPath is not JSON serializable`, outside `LooksError` entirely.
- `Tier(d["tier"])` in `look_from_dict` / `_impl_from_json` raises bare `ValueError`, so a document from a build with a new rung fails outside the package's refusal tree.
- **There is no audit function.** §9 claims a stored `LookPlan` "can be audited for licence with nothing imported", but `plan_from_dict` happily reconstructs a plan whose worst step exceeds its own `max_tier` (`plan.max_tier=PERMISSIVE`, `plan.tier=NONCOMMERCIAL`), and `__all__` exports nothing that would catch it. The refusal exists only at compile time; the *document* is what crosses machines.
- **"Frozen" is advertised, not enforced.** `params` / `metadata` / `payload` / `probe` are plain mutable dicts: mutating `effect.params` in place changes `look_hash` after the fact, and `hash(Look(...))` raises `TypeError: unhashable type: 'dict'`.
- **AnimeGANv2 has no licence file at all** (`gh api repos/TachibanaYoshino/AnimeGANv2 --jq .license` → `null`) — only a README paragraph. Under this note's own doctrine (`UNKNOWN` = "you cannot bound what you have not read", strictest rung) the flagship `NONCOMMERCIAL` example is arguably an `UNKNOWN` one.
- **Recommendation 12's counter-argument is not actually dodged.** Ties break by registration order, and since every ffmpeg implementation sits on the same rung, ties are the *common* case — so among ffmpeg impls the default is import order after all.

### What it did not check

- **`enable=` does not mean what `Span` says it means, and this is measured.** `Span` is documented as "relative to the start of the clip the plan is compiled against", and §3 asserts the ffmpeg boundary "speaks seconds anyway". With the same gate `enable='between(t,1,3)'` on ffmpeg 8.1: no seek → black at source 1–3 s; `-ss 2 -i` → the gate lands 2 s later in the source; `-ss 2 -copyts -i` → source-relative but the leading window is truncated. The compiled payload's meaning depends on an executor flag that is not in the plan. Nothing in the design notices, and `SpanUnsupported` does not address it.
- **No rung for `--enable-nonfree`.** A binary built with it is not redistributable at all; on this ladder it can only be spelled `UNKNOWN`.
- **The probe is a chicken-and-egg the note does not name.** The validated rule is a closed loop over the *output* — you cannot know whether 7.25× or 21.14× applies until you have already run the flatten on sample frames. So "you learn both numbers before a single frame is decoded" is true of a plan and false of the decision that selects it. Nobody is assigned the cost of the sample render.
- **A simpler alternative was never weighed.** §5 rejects option (d) "as the *only* option", but never considers **(d) plus a named-variant table on the `Look`** — `variants: dict[str, dict[str, Any]]`, one entry per clip, selected by name at compile time. That is JSON-native, diffable, keeps one `look_hash`, needs no reserved `$ref` marker inside a parameter *value*, and needs no new type. It should have been the baseline that `Ref` had to beat.
