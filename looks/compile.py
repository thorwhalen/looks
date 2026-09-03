"""A Look plus a clip plus a binary, compiled into a plan — and re-checked.

:func:`compile_look` is the join: a portable ``Look`` (what was asked for) meets
a ``ClipSpec`` (what it is being applied to) and an ``FfmpegEnv`` (what this
machine can actually do), and the result is a ``LookPlan`` — a document saying
what will run, at which tier, against which binary.

## An ffmpeg step's tier belongs to the binary, so the binary is required

An ``ImplRef`` declares ``terms`` — what was observed about the implementation.
For an **ffmpeg-backed** implementation that declaration cannot be the whole
answer, because there is not one ffmpeg on a machine: measured here, ``PATH``
is 8.1 / GPL-3 / 481 filters while ``imageio-ffmpeg``'s bundled binary is 7.1 /
GPL-2 / 484, and the filter sets are non-nested. The same registered
implementation is a different licence position on each.

So the compiler **substitutes the probed binary's terms** into every ffmpeg
candidate before selection, and selection, the step's tier, and a later
:func:`audit` all read that one substituted value. The consequence is that
``env`` is **required** for an ffmpeg step: without it the tier is unknown, and
unknown is a refusal rather than a default.

What this deliberately does *not* do is raise a step's tier because it uses a
GPL-gated filter. :mod:`looks.licence` settles that — *"a GPL-gated filter does
not raise the tier; the binary already has it"* — and the mechanism that keeps
an ``eq`` look off an LGPL build is simpler and stronger: on such a build ``eq``
is not compiled in at all, so it is absent from ``env.filters`` and selection
drops the candidate. A licence ceiling and a missing capability are different
refusals, and :func:`unmet_filters` keeps them apart.

## Why :func:`audit` exists, and why it re-derives instead of reading

A ``LookPlan`` is data, so it travels: written to a file, sent across a process
boundary, stored in a graph, replayed a week later. Every one of those is a gap
in which the thing that vouched for it stopped being present.

So a plan carries both its :class:`~looks.licence.Policy` (the ceiling it was
compiled under) and, on each step, a ``tier``. **The audit trusts neither of
them about the step's actual position.** It goes back to the implementation's
``terms`` — what was *observed* about the licence — and re-derives the tier from
those. A plan whose stored tier disagrees with what its terms classify to is not
a plan with a stale field; it is a plan asserting a position it is not entitled
to, and it is refused by name.

That is the same argument that keeps a tier off ``Effect`` and off ``ImplRef``:
anything that can declare its own tier can declare itself acceptable. A stored
plan is just the version of that with a filesystem in between.

The audit also refuses a plan naming an implementation this process does not
have, or one whose ``impl_version`` has moved. Both mean the same thing — the
plan describes behaviour this build does not implement — and guessing a
substitute is exactly the failure the version lock exists to prevent.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

import dataclasses

from looks.environment import FfmpegEnv
from looks.licence import Policy, classify, check, ffmpeg_terms
from looks.registry import REGISTRY, EffectRegistry, UnknownImpl
from looks.spec import (
    ClipSpec,
    Effect,
    EMPTY,
    Look,
    LookPlan,
    SpecError,
    Step,
    resolve,
    select_impl,
)


class CompileError(SpecError):
    """A Look that cannot be compiled against this clip and this binary."""


class PlanRefused(SpecError):
    """A stored plan that may not be run as it stands. Never a warning."""


def compile_look(
    look: Look,
    *,
    clip: Optional[ClipSpec] = None,
    env: Optional[FfmpegEnv] = None,
    policy: Optional[Policy] = None,
    probe: Mapping[str, Any] = EMPTY,
    registry: Optional[EffectRegistry] = None,
) -> LookPlan:
    """Compile a Look into a plan. No process is started and no file is written.

    Args:
        look: What was asked for. Portable data.
        clip: What it is being applied to. Needed by any effect whose answer
            depends on the frame — its absence is only an error if an effect
            asks for it.
        env: Which binary. When given, an implementation whose filters this
            build lacks is dropped from selection rather than discovered at
            run time.
        policy: The ceiling. Defaults to the Look's own.
        probe: Measurements that :class:`~looks.spec.Ref` parameters resolve
            against.
        registry: Which implementations exist. Defaults to
            :data:`looks.registry.REGISTRY`.

    Returns:
        A :class:`~looks.spec.LookPlan` holding no live callables — the runner
        resolves each step's code from the registry by key.

    Raises:
        CompileError: If an effect has no admissible implementation. The
            message says which constraint emptied the pool, because "no
            implementation available" alone is the least useful refusal in the
            package.
        looks.licence.LooksLicenceError: If the selected implementation exceeds
            the ceiling. Selection already filters by policy, so this fires
            only when nothing admissible existed.
    """
    reg = REGISTRY if registry is None else registry
    ceiling = look.policy if policy is None else policy
    concrete = resolve(look, probe) if probe else look
    available = None if env is None or not env.available else env.filters

    steps = []
    for effect in concrete.steps:
        impl = _select(effect, reg, policy=ceiling, available=available, env=env)
        payload = _payload(reg, impl, effect, clip=clip, env=env)
        steps.append(
            Step(
                effect=effect.name,
                impl=impl,
                tier=_tier(impl),
                params=effect.params,
                at=effect.at,
                payload=payload,
                cpu_seconds=_cost(reg, impl, effect, clip=clip, env=env),
                metadata=effect.metadata,
            )
        )
    return LookPlan(
        steps=tuple(steps),
        clip=clip,
        env=None if env is None else env.fingerprint(),
        look_name=concrete.name,
        policy=ceiling,
        probe=probe,
    )


def _select(
    effect: Effect,
    registry: EffectRegistry,
    *,
    policy: Policy,
    available: Optional[frozenset],
    env: Optional[FfmpegEnv],
) -> Any:
    candidates = registry.implementations(effect.name)
    if not candidates:
        raise CompileError(
            f"no implementation is registered for {effect.name!r}. This "
            f"process has {sorted(registry.effects())}. An effect nobody "
            "implements is a refusal, not a no-op."
        )
    grounded = tuple(_ground(c, env) for c in candidates)
    return select_impl(effect, grounded, policy=policy, available_filters=available)


def _ground(impl, env: Optional[FfmpegEnv]):
    """An ffmpeg implementation, re-stated in terms of the binary that will run it.

    The substitution is the point. An ``ImplRef``'s declared terms are what a
    registrant observed; which ffmpeg is present is what actually determines
    the licence position, and the two are not the same fact. Selection, the
    step's tier and a later audit then all read one value — the probed one.
    """
    if impl.backend != "ffmpeg":
        return impl
    if env is None:
        raise CompileError(
            f"{impl.impl!r} runs on ffmpeg, and an ffmpeg step's licence "
            "position is a property of the binary, not of the effect — this "
            "machine has more than one. Pass env=looks.probe(). An unknown "
            "binary is a refusal, not a default."
        )
    if not env.available:
        raise CompileError(
            f"{impl.impl!r} runs on ffmpeg and the probed binary is not usable"
            + (f": {'; '.join(env.notes)}" if env.notes else ".")
        )
    return dataclasses.replace(impl, terms=ffmpeg_terms(env))


def _tier(impl) -> Any:
    """The step's tier, **derived** from terms — never read off anything."""
    assessment = classify(impl.terms)
    if assessment.tier is None:
        raise CompileError(
            f"{impl.impl!r} classifies to no tier ({assessment.verdict.value}). "
            "Three regions sit off the ladder on purpose and no ceiling "
            "reaches them, so there is nothing to compile against."
        )
    return assessment.tier


def _payload(
    registry: EffectRegistry, impl, effect: Effect, *, clip, env
) -> Mapping[str, Any]:
    payload = registry.compiler(impl.impl)(effect.params, clip=clip, env=env)
    if not isinstance(payload, Mapping):
        raise CompileError(
            f"{impl.impl!r} returned {type(payload).__name__}, not a mapping. "
            "A payload is about to be hashed and serialised, so it is plain "
            "data by definition."
        )
    return payload


def _cost(registry: EffectRegistry, impl, effect: Effect, *, clip, env):
    """CPU-seconds, or ``None`` for unknown — which is never zero."""
    estimator = registry.cost(impl.impl)
    if estimator is None:
        return None
    return estimator(effect.params, clip=clip, env=env)


def audit(
    plan: LookPlan,
    *,
    policy: Optional[Policy] = None,
    registry: Optional[EffectRegistry] = None,
) -> None:
    """Re-check a plan against its own declared ceiling. Raises, or returns None.

    Call this on any plan that crossed a boundary — read from a file, received
    over a wire, replayed from a graph. It answers one question: *may this run
    here, now, as it stands?*

    Nothing the plan says about its own position is believed. Each step's tier
    is re-derived from the implementation's ``terms`` and compared to what the
    step claims; a disagreement is a refusal naming the step, not a field to
    refresh.

    Args:
        policy: The ceiling to check against. Defaults to the plan's own —
            which is the right default and the weaker check, since a plan
            carrying a permissive policy vouches for itself. Pass your own to
            ask whether it may run under *your* ceiling.
        registry: Which implementations exist here.

    Raises:
        PlanRefused: If a step names an implementation this process lacks, or
            one whose ``impl_version`` has moved, or one whose stored tier
            disagrees with its terms.
        looks.licence.LooksLicenceError: If a step exceeds the ceiling.
    """
    reg = REGISTRY if registry is None else registry
    ceiling = plan.policy if policy is None else policy

    for index, step in enumerate(plan.steps):
        where = f"step {index} ({step.effect!r} via {step.impl.impl!r})"
        try:
            known = reg.impl(step.impl.impl)
        except UnknownImpl as e:
            raise PlanRefused(f"{where}: {e}") from None
        if known.impl_version != step.impl.impl_version:
            raise PlanRefused(
                f"{where} was compiled against impl_version "
                f"{step.impl.impl_version!r}; this process has "
                f"{known.impl_version!r}. A version lock moves when behaviour "
                "changes, so running it here would produce different pixels "
                "under the same plan hash."
            )
        derived = classify(step.impl.terms)
        if derived.tier != step.tier:
            raise PlanRefused(
                f"{where} claims tier {step.tier.value!r}, but its own terms "
                f"classify to "
                f"{derived.tier.value if derived.tier else derived.verdict.value!r}"
                ". A plan that could assert its position could assert itself "
                "acceptable."
            )
        check(derived, ceiling, f"{where} in plan {plan.look_name or '<unnamed>'}")


def unmet_filters(plan: LookPlan, env: FfmpegEnv) -> tuple[str, ...]:
    """Filters this plan needs that this binary does not have.

    Separate from :func:`audit` on purpose: a licence refusal is about what a
    caller may do, and a missing filter is about what a machine can do. They
    fail for different reasons, are fixed by different people, and collapsing
    them produces a message that helps neither.
    """
    if not env.available:
        return tuple(
            sorted({f for step in plan.steps for f in step.impl.requires_filters})
        )
    needed = {f for step in plan.steps for f in step.impl.requires_filters}
    return tuple(sorted(needed - set(env.filters)))


def payloads(plan: LookPlan, backend: Optional[str] = None) -> tuple[Mapping, ...]:
    """Every step's payload, optionally for one backend.

    The reading surface for a stored plan: an ``ffmpeg`` payload is fully
    inspectable, so this is how a caller sees the exact filtergraph a plan
    stands for without running anything.
    """
    return tuple(
        step.payload
        for step in plan.steps
        if backend is None or step.impl.backend == backend
    )


def describe(plan: LookPlan) -> str:
    """A plan as a few lines of text — for a CLI, a log, or a review.

    Deliberately not a round-trippable format. Serialisation is
    :func:`looks.spec.plan_to_dict`'s job, and a second one would be a second
    thing to keep in sync.
    """
    if not plan.steps:
        return "(empty plan)"
    lines = []
    for index, step in enumerate(plan.steps):
        cost = "unknown" if step.cpu_seconds is None else f"{step.cpu_seconds:.3f}s"
        span = "" if step.at is None else f"  at={step.at}"
        lines.append(
            f"{index}. {step.effect} via {step.impl.impl} "
            f"[{step.tier.value}] cpu={cost}{span}"
        )
    total = plan.total_cpu_seconds
    lines.append(
        "total cpu: unknown (some steps do not estimate)"
        if plan.has_unknown_costs
        else f"total cpu: {total:.3f}s"
    )
    return "\n".join(lines)


def compile_all(looks_: Sequence[Look], **kwargs) -> tuple[LookPlan, ...]:
    """Compile several Looks under one set of arguments.

    A convenience with one real property: it compiles **all or none**. A
    partially-compiled batch invites a caller to run the half that worked,
    which for a set-relative Look is precisely the mistake ``resolve_across``
    exists to prevent.
    """
    return tuple(compile_look(look, **kwargs) for look in looks_)
