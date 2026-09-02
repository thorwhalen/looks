"""What a stylization *is*, before anything runs. Pure data, no I/O, no registry.

Five types carry the design, and one small one carries the hard part.

- :class:`Effect` — one named operation the caller **asks for**. It never says
  which implementation will serve it, and **it carries no licence tier**.
- :class:`Look` — an ordered stack of Effects plus a :class:`~looks.licence.Policy`.
  The authoring artifact; the thing you persist, diff and ship.
- :class:`ImplRef` — what an implementation **declares about itself**, including
  its :class:`~looks.licence.Terms`. Not a tier: a tier is derived.
- :class:`Step` and :class:`LookPlan` — the compiled form. A tier appears here
  for the first time, **read** off the selected implementation against a
  resolved environment.
- :class:`Ref` — a parameter that cannot be known until the clip is measured.

**The load-bearing decision: `Effect` has no tier field.** If a caller could
write ``Effect(..., tier=PERMISSIVE)``, the refusal is theatre — the party who
wants the answer to be yes would be asserting it. The tier belongs to the
implementation and the environment, so it can only appear at compile time, which
is also the only moment anything decides what will actually run.

**A `Ref` is pure data, never a callable.** A callable would be evaluated during
resolution, so the *plan* would stay serialisable — but the **Look** is the
artifact, and a Look you cannot write to disk is a local variable, not an asset.
It also destroys diffability (two Looks print ``<function <lambda> at 0x...>``)
and any honest cache key.

**The cost unit is CPU-seconds, not dollars**, with ``falaw``'s
unknown-is-not-zero arithmetic transposed for its reasons: a sum must be total
to compose, and a headline ratio a human acts on must not fabricate.

Nothing here consults a registry, probes an environment, or opens a file. A Look
authored against a newer plugin set must still load, print and diff in a process
that lacks it — the discipline that lets an old build read a newer document.

    >>> look = Look(
    ...     name="que_calor",
    ...     steps=(
    ...         Effect(name="flatten", params={"scale": Ref("flatten_scale")}),
    ...         Effect(name="lut3d", params={"cube": "que_calor.cube"}),
    ...         Effect(name="posterize", params={"levels": 18}),
    ...     ),
    ... )
    >>> look.is_resolved
    False
    >>> resolve(look, {"flatten_scale": 0.75})[0].params["scale"]
    0.75
"""

from __future__ import annotations

import enum
import hashlib
import json
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Optional, Sequence

from looks.environment import EnvFingerprint
from looks.licence import DFLT_POLICY, Policy, Terms, Tier, classify

__all__ = [
    "EMPTY",
    "LOOK_SCHEMA",
    "LOOK_VERSION",
    "PLAN_SCHEMA",
    "PLAN_VERSION",
    "REF_MARKER",
    "ClipSpec",
    "Effect",
    "ImplRef",
    "Look",
    "LookPlan",
    "Ref",
    "SchemaError",
    "Span",
    "SpanUnsupported",
    "SpecError",
    "Step",
    "Target",
    "UnresolvedParameter",
    "look_from_dict",
    "look_hash",
    "look_to_dict",
    "output_key",
    "plan_from_dict",
    "plan_hash",
    "plan_to_dict",
    "resolve",
    "resolve_across",
    "select_impl",
]

#: Schema tags. Two kinds, two independent lifecycles — which is exactly why a
#: future migration registry must be keyed on ``(kind, from_version)`` and never
#: on ``(from, to)``. `an` paid for that with an#77: two kinds at the same
#: version number, and the wrong migration silently running against the wrong
#: document.
LOOK_SCHEMA = "looks.look/v1"
LOOK_VERSION = 1
PLAN_SCHEMA = "looks.plan/v1"
PLAN_VERSION = 1

#: The reserved key that marks a deferred parameter in serialised form.
#:
#: Documented cost: a parameter whose legitimate value is a mapping containing
#: this exact key is inexpressible. The decoder is strict about the shape, so
#: the ambiguity raises rather than being hit silently.
REF_MARKER = "$ref"

#: An empty, immutable mapping — the default for every mapping field here.
#:
#: A shared frozen singleton rather than ``field(default_factory=dict)``:
#: ``frozen=True`` prevents *rebinding* a field, not mutating the dict behind
#: it, so a mutable default lets :func:`look_hash` change after a Look has been
#: built, hashed and stored — and makes the objects unhashable despite the
#: decorator generating ``__hash__``.
EMPTY: Mapping[str, Any] = MappingProxyType({})

_NO_DEFAULT = object()


class SpecError(Exception):
    """A Look or a plan that cannot mean what it says."""


class UnresolvedParameter(SpecError):
    """A :class:`Ref` the probe did not answer, and which has no default.

    Deliberately a refusal rather than a fallback. The measured lesson: one
    global flattening scale made the softest of three sources softer still
    (46 -> 38, against 35 -> 72 and 117 -> 114), so it became the softest thing
    on screen. A silent global fallback is exactly that mistake, re-armed.
    """


class SpanUnsupported(SpecError):
    """An :attr:`Effect.at` given to an implementation that cannot be gated."""


class SchemaError(SpecError):
    """A serialised document this build cannot read."""


def _freeze(mapping: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    """A read-only view over a **copy** — see :data:`EMPTY` for why.

    Examples:
        >>> d = {"a": 1}
        >>> frozen = _freeze(d)
        >>> d["a"] = 2               # the caller's dict moves on
        >>> frozen["a"]              # ours does not
        1
    """
    return EMPTY if not mapping else MappingProxyType(dict(mapping))


class Target(str, enum.Enum):
    """What a Look's parameters resolve **against** — RULE N.

    - :attr:`EXTERNAL` — a fixed target outside the material: a delivery
      contract, a reference palette, a colour conform. One clip's probe answers
      it, and :func:`resolve` serves it.
    - :attr:`SET_RELATIVE` — the target *is the set's own distribution*. The
      answer for one clip depends on every other clip, so only
      :func:`resolve_across` can serve it and :func:`resolve` **raises**.

    That refusal is the measured lesson as a type: normalising the OUTPUT across
    sources is not a thing you can compute from one clip.

    The field is ``target`` and **not** ``intent="style"|"grade"``: a colour
    conform is a *normalisation* whose target is external and fixed, and under a
    style/grade wording it would have to be mislabelled.
    """

    EXTERNAL = "external"
    SET_RELATIVE = "set_relative"


@dataclass(frozen=True, slots=True)
class Span:
    """Seconds, relative to frame 0 **as the host's decoder will see it**.

    Says *where a look applies*. It never says where a cut is — that is the
    caller's, and the distinction is what keeps this package out of the EDL.

    Examples:
        >>> Span(1.0, 3.5).duration
        2.5
        >>> Span(None, None).is_whole
        True
        >>> Span(3.0, 1.0)
        Traceback (most recent call last):
        ...
        looks.spec.SpecError: a Span must not end before it starts: 3.0 -> 1.0
    """

    start: Optional[float] = None
    end: Optional[float] = None

    def __post_init__(self) -> None:
        if self.start is not None and self.end is not None and self.end < self.start:
            raise SpecError(
                f"a Span must not end before it starts: {self.start} -> {self.end}"
            )

    @property
    def is_whole(self) -> bool:
        """Whether this span covers everything (both ends open)."""
        return self.start is None and self.end is None

    @property
    def duration(self) -> Optional[float]:
        """Length in seconds, or ``None`` when either end is open."""
        if self.start is None or self.end is None:
            return None
        return self.end - self.start


@dataclass(frozen=True, slots=True, kw_only=True)
class ClipSpec:
    """The clip a plan is compiled **against**. Not a file, not bytes.

    The colour fields are not decoration; without them the plan's central
    promise is false. Measured on an untagged full-range source against a
    correctly-tagged reference, the max channel error is 27/255 fixing
    **neither** range nor matrix, **19** fixing range only, **20** fixing matrix
    only, and **2** fixing both. Two independent unknowns, and half a fix is
    barely a fix — so two clips identical in geometry but differing in colour
    produce visibly different pixels through the same LUT, and a
    :func:`plan_hash` that omits them is lying.

    ``sar`` is here because ``xfade`` silently tolerates a sample-aspect
    mismatch and stamps its output 1:1 — the false-permission direction, in a
    package built on refusal.

    ``None`` means **not declared**, which is a third value and never a synonym
    for a default.

    Examples:
        >>> c = ClipSpec(width=1920, height=1080, fps=30.0)
        >>> c.color_range is None            # untagged is a THIRD value
        True
        >>> c.aspect
        1.7777777777777777
        >>> ClipSpec(width=0, height=1080, fps=30.0)
        Traceback (most recent call last):
        ...
        looks.spec.SpecError: a ClipSpec needs positive dimensions, got 0x1080
    """

    width: int
    height: int
    fps: float
    duration_s: Optional[float] = None
    pix_fmt: Optional[str] = None
    color_range: Optional[str] = None
    color_space: Optional[str] = None
    sar: Optional[tuple[int, int]] = None

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise SpecError(
                f"a ClipSpec needs positive dimensions, got {self.width}x{self.height}"
            )
        if self.fps <= 0:
            raise SpecError(f"a ClipSpec needs a positive fps, got {self.fps}")

    @property
    def aspect(self) -> float:
        """Display aspect, honouring :attr:`sar` when it is declared."""
        ratio = self.width / self.height
        if self.sar:
            num, den = self.sar
            ratio *= num / den
        return ratio

    @property
    def colour_is_declared(self) -> bool:
        """Whether both colour unknowns are answered.

        Read this before trusting a colour operation: half the tags is barely
        better than none.

        Examples:
            >>> ClipSpec(width=2, height=2, fps=1.0).colour_is_declared
            False
            >>> ClipSpec(width=2, height=2, fps=1.0, color_range="limited",
            ...          color_space="bt709").colour_is_declared
            True
        """
        return self.color_range is not None and self.color_space is not None


@dataclass(frozen=True, slots=True)
class Ref:
    """A parameter that cannot be known until the clip is measured.

    Serialised as ``{"$ref": "flatten_scale", "default": 0.5}``. Per-parameter
    on purpose: a diff shows exactly which knobs are clip-dependent, and a Ref
    with no default that the probe does not answer **raises**.

    Rejected alternative — a per-clip ``variants`` table. It is JSON-native and
    would work, but it cannot express the design's central rule (*this parameter
    must be measured, and there is no global fallback*), because a missing entry
    is either a ``KeyError`` or a silent fall-through to the base.

    Examples:
        >>> Ref("flatten_scale").has_default
        False
        >>> Ref("flatten_scale", 0.5).has_default
        True
    """

    key: str
    default: Any = _NO_DEFAULT

    def __post_init__(self) -> None:
        if not self.key:
            raise SpecError("a Ref needs a non-empty key")

    @property
    def has_default(self) -> bool:
        """Whether absence from the probe is tolerable."""
        return self.default is not _NO_DEFAULT

    def resolve(self, probe: Mapping[str, Any], *, where: str = "") -> Any:
        """The value for this Ref, or raise.

        Examples:
            >>> Ref("s", 0.5).resolve({})
            0.5
            >>> Ref("s").resolve({}, where="flatten.scale")
            Traceback (most recent call last):
            ...
            looks.spec.UnresolvedParameter: flatten.scale needs 's'...
        """
        if self.key in probe:
            return probe[self.key]
        if self.has_default:
            return self.default
        raise UnresolvedParameter(
            f"{where or 'a parameter'} needs {self.key!r}, the probe does not "
            f"provide it, and it has no default. That is deliberate: a silent "
            f"global fallback is the mistake this type exists to prevent — one "
            f"global flattening scale made the softest of three sources softer "
            f"still. Measure it, or give the Ref a default you can defend."
        )


def _refs_in(value: Any) -> Iterator[Ref]:
    """Every :class:`Ref` reachable inside a parameter value."""
    if isinstance(value, Ref):
        yield value
    elif isinstance(value, Mapping):
        for v in value.values():
            yield from _refs_in(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _refs_in(v)


def _resolve_value(value: Any, probe: Mapping[str, Any], where: str) -> Any:
    if isinstance(value, Ref):
        return value.resolve(probe, where=where)
    if isinstance(value, Mapping):
        return {k: _resolve_value(v, probe, f"{where}.{k}") for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_value(v, probe, f"{where}[{i}]") for i, v in enumerate(value)]
    if isinstance(value, tuple):
        return tuple(
            _resolve_value(v, probe, f"{where}[{i}]") for i, v in enumerate(value)
        )
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class Effect:
    """One named operation the caller asks for. Pure data; no tier, no impl.

    :attr:`name` is the **capability** (``"flatten"``, ``"posterize"``), never an
    implementation. :attr:`impl` and :attr:`backend` pin *which* answer serves
    it — and neither bypasses the ceiling: a pinned implementation above the
    policy is still refused, because a pin says which one you want, not that you
    may have it.

    :attr:`metadata` is identity-free labelling and never enters
    :func:`look_hash`.

    Examples:
        >>> e = Effect(name="posterize", params={"levels": 18})
        >>> e.name, e.params["levels"]
        ('posterize', 18)
        >>> e.is_resolved
        True
        >>> Effect(name="flatten", params={"scale": Ref("s")}).is_resolved
        False
        >>> Effect(name="")
        Traceback (most recent call last):
        ...
        looks.spec.SpecError: an Effect needs a capability name
    """

    name: str
    params: Mapping[str, Any] = EMPTY
    at: Optional[Span] = None
    impl: Optional[str] = None
    backend: Optional[str] = None
    metadata: Mapping[str, Any] = EMPTY

    def __post_init__(self) -> None:
        if not self.name:
            raise SpecError("an Effect needs a capability name")
        object.__setattr__(self, "params", _freeze(self.params))
        object.__setattr__(self, "metadata", _freeze(self.metadata))

    @property
    def refs(self) -> tuple[Ref, ...]:
        """Every deferred parameter, in no particular order."""
        return tuple(r for v in self.params.values() for r in _refs_in(v))

    @property
    def is_resolved(self) -> bool:
        """Whether every parameter is concrete."""
        return not self.refs

    def resolved(self, probe: Mapping[str, Any]) -> "Effect":
        """A copy with every :class:`Ref` replaced, or raise."""
        return replace(
            self,
            params={
                k: _resolve_value(v, probe, f"{self.name}.{k}")
                for k, v in self.params.items()
            },
        )


def _stricter_policy(a: Policy, b: Policy) -> Policy:
    """The stricter of two policies, per field.

    A guarantee that composition can silently relax is not a guarantee, so
    ``+`` never widens: the lower ceiling wins, and only restrictions **both**
    sides accepted survive.
    """
    order = a.order
    lower = (
        a.max_tier if order.index(a.max_tier) <= order.index(b.max_tier) else b.max_tier
    )
    return replace(
        a,
        max_tier=lower,
        allow_field_restricted=frozenset(a.allow_field_restricted)
        & frozenset(b.allow_field_restricted),
    )


def _stricter_target(a: Target, b: Target) -> Target:
    """``SET_RELATIVE`` wins: it demands the more capable resolver."""
    return Target.SET_RELATIVE if Target.SET_RELATIVE in (a, b) else Target.EXTERNAL


@dataclass(frozen=True, slots=True, kw_only=True)
class Look:
    """An ordered stack of Effects plus a policy. The artifact you ship.

    ``a + b`` concatenates the steps and takes the **stricter** of the two
    policies, never the looser — a guarantee composition can silently relax is
    not a guarantee. Widening is always a separate deliberate act
    (:meth:`with_policy`).

    :attr:`policy` is **not** part of :func:`look_hash`: a ceiling changes what
    a Look is *allowed* to compile to, never what it asks for.

    Examples:
        >>> from looks.licence import Policy, Tier
        >>> safe = Look(name="grade", steps=(Effect(name="gamma"),),
        ...             policy=Policy(max_tier=Tier.PERMISSIVE))
        >>> lab = Look(steps=(Effect(name="flatten"),))
        >>> (safe + lab).policy.max_tier          # the STRICTER survives
        <Tier.PERMISSIVE: 'permissive'>
        >>> len((safe + lab).steps)
        2
        >>> (safe + lab).with_policy(lab.policy).policy.max_tier
        <Tier.COPYLEFT_TOOL: 'copyleft_tool'>
    """

    steps: tuple[Effect, ...] = ()
    name: str = ""
    policy: Policy = DFLT_POLICY
    target: Target = Target.EXTERNAL
    metadata: Mapping[str, Any] = EMPTY
    version: int = LOOK_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps", tuple(self.steps))
        object.__setattr__(self, "metadata", _freeze(self.metadata))

    def __add__(self, other: "Look") -> "Look":
        if not isinstance(other, Look):
            return NotImplemented
        return replace(
            self,
            steps=self.steps + other.steps,
            policy=_stricter_policy(self.policy, other.policy),
            target=_stricter_target(self.target, other.target),
        )

    def __len__(self) -> int:
        return len(self.steps)

    def __iter__(self) -> Iterator[Effect]:
        return iter(self.steps)

    def __getitem__(self, index):
        return self.steps[index]

    @property
    def refs(self) -> tuple[Ref, ...]:
        """Every deferred parameter across every step."""
        return tuple(r for step in self.steps for r in step.refs)

    @property
    def is_resolved(self) -> bool:
        """Whether the whole Look is concrete."""
        return not self.refs

    def with_policy(self, policy: Policy) -> "Look":
        """A copy under a different ceiling — the deliberate widening act."""
        return replace(self, policy=policy)


def resolve(look: Look, probe: Mapping[str, Any] = EMPTY) -> Look:
    """Replace every :class:`Ref` from one clip's ``probe``.

    The **identity** on a Look holding no Refs, so a caller who already has
    numbers never meets this function.

    Raises:
        SpecError: The Look is ``SET_RELATIVE`` — RULE N. Its target is the
            set's own distribution, which one clip cannot supply.
        UnresolvedParameter: A Ref with no default that ``probe`` does not
            answer.

    Examples:
        >>> look = Look(steps=(Effect(name="flatten", params={"scale": Ref("s")}),))
        >>> resolve(look, {"s": 0.75})[0].params["scale"]
        0.75
        >>> resolve(Look(steps=(Effect(name="lut3d"),)))     # identity
        Look(steps=(Effect(name='lut3d', ...),), ...)

        A set-relative Look refuses the single-clip resolver:

        >>> resolve(Look(target=Target.SET_RELATIVE), {})
        Traceback (most recent call last):
        ...
        looks.spec.SpecError: this Look is SET_RELATIVE...
    """
    if look.target is Target.SET_RELATIVE:
        raise SpecError(
            "this Look is SET_RELATIVE: its target is the set's own "
            "distribution, so one clip's probe cannot answer it. Use "
            "resolve_across(look, probes). Normalising the OUTPUT across "
            "sources is the measured rule, and it is not computable from one "
            "clip."
        )
    if look.is_resolved:
        return look
    return replace(look, steps=tuple(s.resolved(probe) for s in look.steps))


def resolve_across(look: Look, probes: Sequence[Mapping[str, Any]]) -> tuple[Look, ...]:
    """One resolved Look per probe — N in, N out.

    The resolver for a target that is the set's own distribution. This function
    does **not** compute the cross-clip answer: it applies per-clip probes a
    caller has already solved for, because choosing them requires running the
    effect, and running things is not this package's job. See
    :mod:`looks.measure` for the measurement half.

    Examples:
        >>> look = Look(target=Target.SET_RELATIVE,
        ...             steps=(Effect(name="flatten", params={"scale": Ref("s")}),))
        >>> got = resolve_across(look, [{"s": 0.5}, {"s": 0.5}, {"s": 0.75}])
        >>> [lk[0].params["scale"] for lk in got]
        [0.5, 0.5, 0.75]

        Each result is EXTERNAL: the set-relative question has been answered,
        and re-resolving would ask it again against a different set.

        >>> got[0].target
        <Target.EXTERNAL: 'external'>
        >>> resolve_across(look, [])
        Traceback (most recent call last):
        ...
        looks.spec.SpecError: resolve_across needs at least one probe...
    """
    if not probes:
        raise SpecError(
            "resolve_across needs at least one probe; an empty set has no "
            "distribution to normalise against"
        )
    plain = replace(look, target=Target.EXTERNAL)
    return tuple(resolve(plain, p) for p in probes)


@dataclass(frozen=True, slots=True, kw_only=True)
class ImplRef:
    """What an implementation declares about itself — **terms, never a tier**.

    A tier is a position on a policy ladder; terms are what was observed. An
    implementation that could declare its own tier could declare itself
    acceptable, which is the same failure as an ``Effect`` carrying one.

    Attributes:
        effect: The capability served.
        impl: ``"<effect>.<backend>.<variant>"``, globally unique.
        backend: ``"ffmpeg"`` | ``"frame"`` | ``"external"``.
        terms: What it is. See :class:`looks.licence.Terms`.
        requires_filters: ffmpeg filters this implementation emits.
        impl_version: A behaviour lock, not a receipt — "same interface,
            changed behaviour" bumps it, and it enters :func:`plan_hash`
            **unconditionally**.
        timeline: Whether it can be gated to an :attr:`Effect.at`.
        preference: Explicit tiebreak within one tier; lower wins.

    Examples:
        >>> from looks.licence import terms_for
        >>> impl = ImplRef(effect="lut3d", impl="lut3d.ffmpeg.default",
        ...                backend="ffmpeg", terms=terms_for("ffmpeg")[0],
        ...                requires_filters=("lut3d",))
        >>> impl.impl_version
        '1'
        >>> impl.timeline
        True
    """

    effect: str
    impl: str
    backend: str
    terms: Terms
    requires_filters: tuple[str, ...] = ()
    impl_version: str = "1"
    timeline: bool = True
    preference: int = 0

    def __post_init__(self) -> None:
        if not self.effect or not self.impl:
            raise SpecError("an ImplRef needs both an effect and an impl key")
        object.__setattr__(self, "requires_filters", tuple(self.requires_filters))

    @property
    def tier(self) -> Optional[Tier]:
        """The rung its terms project onto, or ``None`` when off the ladder.

        Derived on read, never stored — so it cannot drift from the terms.
        """
        return classify(self.terms).tier


def select_impl(
    effect: Effect,
    candidates: Sequence[ImplRef],
    *,
    policy: Policy = DFLT_POLICY,
    available_filters: Optional[frozenset[str]] = None,
) -> ImplRef:
    """Choose an implementation for ``effect``, or raise saying why not.

    In order: honour an explicit ``impl`` or ``backend`` pin, drop anything the
    environment cannot run, drop anything the policy refuses, drop anything that
    cannot be gated when the effect has a span, then take the lowest tier and
    break ties on :attr:`ImplRef.preference`.

    **A pin narrows, it never permits.** A pinned implementation the policy
    refuses is still refused — otherwise the pin is a way to assert a tier,
    which is the thing :class:`Effect` deliberately cannot do.

    Raises:
        SpecError: Nothing survived, with the reason.
        SpanUnsupported: Every survivor refuses a span the effect carries.

    Examples:
        >>> from looks.licence import terms_for, Policy, Tier
        >>> ff = terms_for("ffmpeg")[0]
        >>> cands = [ImplRef(effect="blur", impl="blur.ffmpeg.gblur",
        ...                  backend="ffmpeg", terms=ff, requires_filters=("gblur",))]
        >>> select_impl(Effect(name="blur"), cands).impl
        'blur.ffmpeg.gblur'

        A filter this build lacks removes the candidate:

        >>> select_impl(Effect(name="blur"), cands,
        ...             available_filters=frozenset({"scale"}))
        Traceback (most recent call last):
        ...
        looks.spec.SpecError: no implementation of 'blur' survived...
    """
    pool = [c for c in candidates if c.effect == effect.name]
    if not pool:
        raise SpecError(
            f"no implementation is registered for {effect.name!r}; "
            f"candidates offered: {sorted({c.effect for c in candidates})}"
        )
    why: list[str] = []

    if effect.impl is not None:
        pool = [c for c in pool if c.impl == effect.impl]
        why.append(f"pinned impl={effect.impl!r}")
    if effect.backend is not None:
        pool = [c for c in pool if c.backend == effect.backend]
        why.append(f"pinned backend={effect.backend!r}")
    if available_filters is not None:
        pool = [c for c in pool if set(c.requires_filters) <= set(available_filters)]
        why.append("filters this build has")
    if effect.at is not None:
        gated = [c for c in pool if c.timeline]
        if pool and not gated:
            raise SpanUnsupported(
                f"{effect.name!r} carries a span ({effect.at}), and no surviving "
                f"implementation can be gated to one. Apply it to the whole clip, "
                f"or split the clip where the caller already knows the boundary."
            )
        pool = gated
        why.append("timeline-gateable")

    admitted = [c for c in pool if _admits(policy, c)]
    if not admitted:
        detail = f" after {', '.join(why)}" if why else ""
        blocked = ", ".join(
            f"{c.impl} (tier {c.tier.value if c.tier else 'off-ladder'})" for c in pool
        )
        raise SpecError(
            f"no implementation of {effect.name!r} survived{detail} under a "
            f"{policy.max_tier.value!r} ceiling."
            + (f" Refused: {blocked}." if blocked else "")
            + " Raise the ceiling deliberately with look.with_policy(...), pick "
            "another effect, or install an implementation that clears it."
        )
    order = policy.order
    return min(
        admitted,
        key=lambda c: (
            order.index(c.tier) if c.tier in order else len(order),
            c.preference,
            c.impl,
        ),
    )


def _admits(policy: Policy, impl: ImplRef) -> bool:
    """Whether ``policy`` allows ``impl``, delegating the judgement to `licence`.

    Never re-derives the rule. The one place a tier is compared to a ceiling is
    :func:`looks.licence.check`, so a second comparison here could drift from it
    — and drift in a refusal engine means either a false refusal or a false
    permission.
    """
    from looks.licence import LooksLicenceError, check

    try:
        check(classify(impl.terms), policy, impl.impl)
    except LooksLicenceError:
        return False
    return True


@dataclass(frozen=True, slots=True, kw_only=True)
class Step:
    """One compiled operation. A tier appears here, read and not asserted.

    :attr:`payload` is backend-shaped and the asymmetry is deliberate: an
    ``ffmpeg`` payload is fully inspectable (read a stored plan and see the
    exact filtergraph), while ``frame`` and ``external`` payloads are only
    *nameable*.

    **A payload names a registry key, never a ``module:attr`` import path.** A
    plan is a document, documents arrive from places, and a document that can
    name ``os:system`` is a remote-code-execution primitive wearing a schema
    tag.

    :attr:`cpu_seconds` is ``None`` for unknown, **never zero**.

    Examples:
        >>> from looks.licence import terms_for
        >>> impl = ImplRef(effect="lut3d", impl="lut3d.ffmpeg.default",
        ...                backend="ffmpeg", terms=terms_for("ffmpeg")[0])
        >>> from looks.licence import Tier
        >>> s = Step(effect="lut3d", impl=impl, tier=Tier.WEAK_COPYLEFT,
        ...          payload={"filter": "lut3d=look.cube"})
        >>> s.payload["filter"]
        'lut3d=look.cube'
        >>> s.cpu_seconds is None            # unknown, not free
        True
    """

    effect: str
    impl: ImplRef
    tier: Tier
    params: Mapping[str, Any] = EMPTY
    at: Optional[Span] = None
    payload: Mapping[str, Any] = EMPTY
    cpu_seconds: Optional[float] = None
    metadata: Mapping[str, Any] = EMPTY

    def __post_init__(self) -> None:
        leftover = [r for v in self.params.values() for r in _refs_in(v)]
        if leftover:
            raise UnresolvedParameter(
                f"step {self.effect!r} still holds unresolved parameters "
                f"{[r.key for r in leftover]}; a compiled Step is concrete by "
                f"definition. Call resolve() before compiling."
            )
        if self.cpu_seconds is not None and not (self.cpu_seconds >= 0):
            raise SpecError(
                f"cpu_seconds must be non-negative or None, got {self.cpu_seconds!r}"
            )
        object.__setattr__(self, "params", _freeze(self.params))
        object.__setattr__(self, "payload", _freeze(self.payload))
        object.__setattr__(self, "metadata", _freeze(self.metadata))


@dataclass(frozen=True, slots=True, kw_only=True)
class LookPlan:
    """The compiled pipeline: what will run, against which clip and which binary.

    The **env fingerprint belongs here and not on the Look**. A ``Look`` is
    portable data; a ``LookPlan`` is compiled against one binary whose filter
    set and licence are part of what determines the pixels — so it says which
    one, and that enters :func:`plan_hash`. Folding the environment in does not
    break portability, because the portable artifact is the Look.

    **The plan holds no live callables.** A plan with a closure in it cannot be
    serialised, diffed or hashed, which is the entire reason this shape was
    adopted. The callable is resolved from the registry at execution time, by
    the runner.

    Deliberately not modelled: peak memory and streaming shape. Those are the
    executor's invariant, and a plan claiming to predict them is an invitation
    to write the ``looks.render()`` this package is chartered to stay out of.

    Examples:
        >>> plan = LookPlan()
        >>> plan.total_cpu_seconds
        0.0
        >>> plan.has_unknown_costs
        False
        >>> plan.realtime_factor is None     # no clip to divide by
        True
    """

    steps: tuple[Step, ...] = ()
    clip: Optional[ClipSpec] = None
    env: Optional[EnvFingerprint] = None
    look_name: str = ""
    policy: Policy = DFLT_POLICY
    probe: Mapping[str, Any] = EMPTY
    metadata: Mapping[str, Any] = EMPTY
    version: int = PLAN_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps", tuple(self.steps))
        object.__setattr__(self, "probe", _freeze(self.probe))
        object.__setattr__(self, "metadata", _freeze(self.metadata))

    def __len__(self) -> int:
        return len(self.steps)

    def __iter__(self) -> Iterator[Step]:
        return iter(self.steps)

    def __getitem__(self, index):
        return self.steps[index]

    @property
    def total_cpu_seconds(self) -> float:
        """Sum with unknown coerced to ``0.0`` — a documented **lower bound**.

        Total so sums compose. Read it beside :attr:`unknown_step_count`, never
        alone: the true cost is this *plus an unknown amount* spread over that
        many steps.
        """
        return float(sum((s.cpu_seconds or 0.0) for s in self.steps))

    @property
    def known_cpu_seconds(self) -> float:
        """The priced part only — the honest half of the pair."""
        return float(
            sum(s.cpu_seconds for s in self.steps if s.cpu_seconds is not None)
        )

    @property
    def unknown_step_count(self) -> int:
        """How many steps carry no cost at all."""
        return sum(1 for s in self.steps if s.cpu_seconds is None)

    @property
    def has_unknown_costs(self) -> bool:
        """Whether anything is unpriced. A gate reads this, not the sum."""
        return self.unknown_step_count > 0

    @property
    def realtime_factor(self) -> Optional[float]:
        """CPU-seconds per second of output, or ``None`` when anything is unknown.

        The asymmetry against :attr:`total_cpu_seconds` is deliberate: a sum
        must be total to compose, but a headline ratio a human acts on must not
        fabricate. Returning ``0.0`` for "we did not know" is reelee#208's
        failure mode, where a ``$0.00``-because-unknown read as "under the
        threshold, spend freely".
        """
        if self.has_unknown_costs or self.clip is None or not self.clip.duration_s:
            return None
        return self.total_cpu_seconds / self.clip.duration_s


# --- serialisation ----------------------------------------------------------


def _param_to_json(value: Any) -> Any:
    if isinstance(value, Ref):
        out = {REF_MARKER: value.key}
        if value.has_default:
            out["default"] = value.default
        return out
    if isinstance(value, Mapping):
        if REF_MARKER in value:
            raise SchemaError(
                f"a parameter value may not contain the reserved key "
                f"{REF_MARKER!r}; it would be indistinguishable from a Ref"
            )
        return {k: _param_to_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_param_to_json(v) for v in value]
    return value


def _param_from_json(value: Any) -> Any:
    if isinstance(value, Mapping) and REF_MARKER in value:
        extra = set(value) - {REF_MARKER, "default"}
        if extra:
            raise SchemaError(f"a $ref carries unexpected keys: {sorted(extra)}")
        return (
            Ref(value[REF_MARKER], value["default"])
            if "default" in value
            else Ref(value[REF_MARKER])
        )
    if isinstance(value, Mapping):
        return {k: _param_from_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_param_from_json(v) for v in value]
    return value


def _span_to_json(span: Optional[Span]) -> Optional[dict]:
    return None if span is None else {"start": span.start, "end": span.end}


def _span_from_json(d: Optional[Mapping]) -> Optional[Span]:
    return None if d is None else Span(d.get("start"), d.get("end"))


def look_to_dict(look: Look) -> dict:
    """A JSON-able form of a Look, carrying its schema tag.

    Examples:
        >>> d = look_to_dict(Look(name="x", steps=(Effect(name="lut3d"),)))
        >>> d["schema"], d["name"]
        ('looks.look/v1', 'x')
    """
    return {
        "schema": LOOK_SCHEMA,
        "version": look.version,
        "name": look.name,
        "target": look.target.value,
        "policy": {
            "max_tier": look.policy.max_tier.value,
            "allow_field_restricted": sorted(
                f.value for f in look.policy.allow_field_restricted
            ),
        },
        "steps": [
            {
                "name": e.name,
                "params": {k: _param_to_json(v) for k, v in e.params.items()},
                "at": _span_to_json(e.at),
                "impl": e.impl,
                "backend": e.backend,
                "metadata": dict(e.metadata),
            }
            for e in look.steps
        ],
        "metadata": dict(look.metadata),
    }


def look_from_dict(d: Mapping[str, Any]) -> Look:
    """Rebuild a Look. An unrecognised tag is refused; a missing one is v1.

    Examples:
        >>> look = Look(name="x", steps=(Effect(name="lut3d", params={"a": Ref("r")}),))
        >>> back = look_from_dict(look_to_dict(look))
        >>> back.steps[0].params["a"]
        Ref(key='r', default=<object object at ...>)
        >>> look_from_dict({"schema": "looks.look/v9"})
        Traceback (most recent call last):
        ...
        looks.spec.SchemaError: this build reads 'looks.look/v1'...
    """
    tag = d.get("schema", LOOK_SCHEMA)
    if tag != LOOK_SCHEMA:
        raise SchemaError(
            f"this build reads {LOOK_SCHEMA!r}; the document says {tag!r}. "
            f"A newer document needs a newer looks, and refusing loudly beats "
            f"reading half of it."
        )
    from looks.licence import FieldOfUse

    pol = d.get("policy") or {}
    policy = (
        replace(
            DFLT_POLICY,
            max_tier=Tier(pol["max_tier"]),
            allow_field_restricted=frozenset(
                FieldOfUse(v) for v in pol.get("allow_field_restricted", ())
            ),
        )
        if pol
        else DFLT_POLICY
    )
    return Look(
        name=d.get("name", ""),
        version=d.get("version", LOOK_VERSION),
        target=Target(d.get("target", Target.EXTERNAL.value)),
        policy=policy,
        metadata=d.get("metadata") or EMPTY,
        steps=tuple(
            Effect(
                name=s["name"],
                params={
                    k: _param_from_json(v) for k, v in (s.get("params") or {}).items()
                },
                at=_span_from_json(s.get("at")),
                impl=s.get("impl"),
                backend=s.get("backend"),
                metadata=s.get("metadata") or EMPTY,
            )
            for s in d.get("steps", ())
        ),
    )


def plan_from_dict(d: Mapping[str, Any], *, impls: Mapping[str, ImplRef]) -> LookPlan:
    """Rebuild a plan, given the implementations its steps name.

    **``impls`` is required, and a step naming one that is absent raises.** A
    serialised step carries its implementation's *key*, not its
    :class:`~looks.licence.Terms` — and reconstructing an ``ImplRef`` from a key
    alone would mean inventing the terms, which is inventing a licence verdict.
    In a package whose thesis is that unknown refuses, a plan that rehydrates
    into a confident tier nobody observed is the worst possible artifact.

    So the caller supplies the registry it trusts, and a plan built against
    implementations this process does not have is a refusal rather than a guess.
    That is also what makes a stored plan safe to receive from elsewhere: it
    cannot name its way into a capability the receiving process did not already
    install.

    Raises:
        SchemaError: An unrecognised schema tag, or a step naming an
            implementation ``impls`` does not carry.

    Examples:
        >>> from looks.licence import terms_for, Tier
        >>> impl = ImplRef(effect="lut3d", impl="lut3d.ffmpeg.default",
        ...                backend="ffmpeg", terms=terms_for("ffmpeg")[0])
        >>> plan = LookPlan(steps=(Step(effect="lut3d", impl=impl,
        ...                             tier=Tier.WEAK_COPYLEFT,
        ...                             payload={"filter": "lut3d=x.cube"}),))
        >>> back = plan_from_dict(plan_to_dict(plan), impls={impl.impl: impl})
        >>> plan_hash(back) == plan_hash(plan)
        True

        A plan naming an implementation this process lacks is refused, not
        approximated:

        >>> plan_from_dict(plan_to_dict(plan), impls={})
        Traceback (most recent call last):
        ...
        looks.spec.SchemaError: this plan names implementations this process
        does not have: ['lut3d.ffmpeg.default']...
    """
    tag = d.get("schema", PLAN_SCHEMA)
    if tag != PLAN_SCHEMA:
        raise SchemaError(
            f"this build reads {PLAN_SCHEMA!r}; the document says {tag!r}."
        )
    steps_raw = list(d.get("steps", ()))
    unknown = sorted({s["impl"] for s in steps_raw if s["impl"] not in impls})
    if unknown:
        raise SchemaError(
            f"this plan names implementations this process does not have: "
            f"{unknown}. They are not reconstructible from the document, "
            f"because a step carries an implementation's KEY and not its terms "
            f"— and inventing the terms would invent a licence verdict. Install "
            f"them, or pass the registry that has them."
        )
    clip_raw = d.get("clip")
    clip = (
        None
        if clip_raw is None
        else ClipSpec(
            width=clip_raw["width"],
            height=clip_raw["height"],
            fps=clip_raw["fps"],
            duration_s=clip_raw.get("duration_s"),
            pix_fmt=clip_raw.get("pix_fmt"),
            color_range=clip_raw.get("color_range"),
            color_space=clip_raw.get("color_space"),
            sar=tuple(clip_raw["sar"]) if clip_raw.get("sar") else None,
        )
    )
    env_raw = d.get("env")
    return LookPlan(
        version=d.get("version", PLAN_VERSION),
        look_name=d.get("look_name", ""),
        clip=clip,
        env=None if env_raw is None else EnvFingerprint.from_dict(env_raw),
        probe=d.get("probe") or EMPTY,
        metadata=d.get("metadata") or EMPTY,
        steps=tuple(
            Step(
                effect=s["effect"],
                impl=impls[s["impl"]],
                tier=Tier(s["tier"]),
                params={
                    k: _param_from_json(v) for k, v in (s.get("params") or {}).items()
                },
                at=_span_from_json(s.get("at")),
                payload=s.get("payload") or EMPTY,
                cpu_seconds=s.get("cpu_seconds"),
                metadata=s.get("metadata") or EMPTY,
            )
            for s in steps_raw
        ),
    )


def _canonical_blob(payload: Any) -> bytes:
    """Sorted-key JSON, no ``default=str`` fallback, no NaN.

    ``falaw.canonical``'s rule for its reason: a value the form cannot represent
    faithfully must **raise** rather than collide with something else's
    ``repr``.
    """
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def look_hash(look: Look) -> str:
    """Structural identity of the authored **intent**.

    Registry-independent, environment-independent, **policy-independent**.
    ``metadata`` is excluded (labelling, not identity) and so is ``policy``: a
    ceiling changes what a Look may compile to, never what it asks for.

    Examples:
        >>> from looks.licence import Policy, Tier
        >>> a = Look(name="x", steps=(Effect(name="gamma", params={"g": 1.1}),))
        >>> look_hash(a) == look_hash(replace(a, name="y"))       # name IS identity
        False
        >>> look_hash(a) == look_hash(replace(a, metadata={"who": "thor"}))
        True
        >>> look_hash(a) == look_hash(a.with_policy(Policy(max_tier=Tier.PURE)))
        True
    """
    payload = {
        "schema": LOOK_SCHEMA,
        "name": look.name,
        "target": look.target.value,
        "steps": [
            {
                "name": e.name,
                "params": {k: _param_to_json(v) for k, v in sorted(e.params.items())},
                "at": _span_to_json(e.at),
                "impl": e.impl,
                "backend": e.backend,
            }
            for e in look.steps
        ],
    }
    return hashlib.sha256(_canonical_blob(payload)).hexdigest()


def plan_to_dict(plan: LookPlan) -> dict:
    """A JSON-able form of a plan, carrying its schema tag."""
    return {
        "schema": PLAN_SCHEMA,
        "version": plan.version,
        "look_name": plan.look_name,
        "clip": None
        if plan.clip is None
        else {
            "width": plan.clip.width,
            "height": plan.clip.height,
            "fps": plan.clip.fps,
            "duration_s": plan.clip.duration_s,
            "pix_fmt": plan.clip.pix_fmt,
            "color_range": plan.clip.color_range,
            "color_space": plan.clip.color_space,
            "sar": list(plan.clip.sar) if plan.clip.sar else None,
        },
        "env": None if plan.env is None else plan.env.to_dict(),
        "steps": [
            {
                "effect": s.effect,
                "impl": s.impl.impl,
                "impl_version": s.impl.impl_version,
                "backend": s.impl.backend,
                "tier": s.tier.value,
                "params": {k: _param_to_json(v) for k, v in s.params.items()},
                "at": _span_to_json(s.at),
                "payload": dict(s.payload),
                "cpu_seconds": s.cpu_seconds,
                "metadata": dict(s.metadata),
            }
            for s in plan.steps
        ],
        "probe": dict(plan.probe),
        "metadata": dict(plan.metadata),
    }


def plan_hash(plan: LookPlan) -> str:
    """Identity of the compiled pipeline — *will this produce the same pixels?*

    Folds, per step: the implementation key **and its version**, the resolved
    parameters, the span and the compiled payload; plus the clip's geometry
    **and its colour state**, and the environment fingerprint.

    ``impl_version`` folds in **unconditionally**. ``nw`` and ``falaw`` omit
    theirs when it equals its default; that is a *migration device* protecting
    an installed base of cache keys, and `looks` has no installed base. Do not
    copy the sentinel.

    Examples:
        >>> plan_hash(LookPlan()) == plan_hash(LookPlan())
        True
        >>> a = LookPlan(clip=ClipSpec(width=2, height=2, fps=1.0))
        >>> b = LookPlan(clip=ClipSpec(width=2, height=2, fps=1.0,
        ...                            color_range="full"))
        >>> plan_hash(a) == plan_hash(b)      # colour state is identity
        False
    """
    d = plan_to_dict(plan)
    payload = {
        "schema": PLAN_SCHEMA,
        "clip": d["clip"],
        "env": d["env"],
        "steps": [
            {
                "effect": s["effect"],
                "impl": s["impl"],
                "impl_version": s["impl_version"],
                "params": s["params"],
                "at": s["at"],
                "payload": s["payload"],
            }
            for s in d["steps"]
        ],
    }
    return hashlib.sha256(_canonical_blob(payload)).hexdigest()


def output_key(plan: LookPlan, source_digest: str) -> str:
    """The content-addressed key of what this plan makes from these bytes.

    ``source_digest`` is a digest of the source's **content**, never its path or
    its URL. That signature is `falaw`'s D1 defect stated as a type: keying on
    upstream *URLs* made a byte-identical regeneration miss the cache.

    `looks` computes the formula and **refuses to open the file**, because
    reading bytes is execution.

    Examples:
        >>> k = output_key(LookPlan(), "a" * 64)
        >>> len(k)
        64
        >>> k == output_key(LookPlan(), "b" * 64)
        False
        >>> output_key(LookPlan(), "/path/to/clip.mp4")
        Traceback (most recent call last):
        ...
        looks.spec.SpecError: source_digest must be a content digest...
    """
    if "/" in source_digest or "\\" in source_digest or "." in source_digest:
        raise SpecError(
            f"source_digest must be a content digest, not a path: "
            f"{source_digest!r}. Keying on a path rather than on bytes is how a "
            f"byte-identical regeneration misses its own cache entry."
        )
    return hashlib.sha256(
        _canonical_blob({"plan": plan_hash(plan), "source": source_digest})
    ).hexdigest()
