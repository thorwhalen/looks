"""The ffmpeg backend, checked by handing every fragment to ffmpeg.

An effect that compiles to a plausible string and fails at run time is worse
than one that refuses, because the failure surfaces in a render rather than a
plan. So :class:`TestEveryRegisteredEffectConfigures` sweeps the whole registry
and asks the binary — the same posture as `test_motion.py`, applied to the
catalogue rather than to one compiler.

The escaping tests are first-hand: a `.cube` file is written with a comma and a
colon in its name, and both the failing and the working invocation are run.

Offline and free: every clip is `lavfi`, and every process ends in `-f null -`.
"""

import shutil
import subprocess

import pytest

import looks
from looks.compile import compile_look
from looks.environment import probe
from looks.ffmpeg import (
    FfmpegBackendError,
    escape_filter_value,
    filter_string,
    gated,
    register_defaults,
    vf,
)
from looks.registry import EffectRegistry
from looks.spec import ClipSpec, Effect, Look, Span

#: A ramp with a real floor, so writing a cube does not trip the
#: package's own "do not end a ramp at black" warning — which is a rule
#: about looks, not about escaping, and its noise here would be misread.
QUE_CALOR_STOPS = [(8.2, "#2E0C18"), (46.8, "#D5254A"), (100.0, "#FEF0DC")]

SOURCE = "testsrc2=size=320x240:rate=10:duration=0.5"
CLIP = ClipSpec(width=320, height=240, fps=10)

#: One set of parameters per registered effect that is enough to compile it.
PARAMS = {
    "lut3d": {"cube": None},  # filled in by the fixture with a real file
    "gradient_map": {
        "stops": [[8.2, "#2E0C18"], [46.8, "#D5254A"], [100.0, "#FEF0DC"]],
        "size": 9,
    },
    "saturation": {"amount": 1.4},
    "contrast": {"amount": 1.2},
    "gamma": {"gamma": 1.2},
    "levels": {"black": 0.02, "white": 0.98},
    "posterize": {"levels": 6},
    "flatten": {"spatial": 20, "range": 0.05},
    "blur": {"sigma": 2},
    "sharpen": {"amount": 1.0},
    "fit": {"target": "320x240"},
    "fill": {"target": "shorts"},
    "stretch": {"target": "square"},
    "motion": {"keyframes": [(0.0, (0, 0, 0.5, 0.5)), (0.5, (0.5, 0.5, 0.5, 0.5))]},
}


def _ffmpeg_or_skip():
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not on PATH")


def configure(fragment):
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", SOURCE,
         "-vf", fragment, "-f", "null", "-"],
        capture_output=True, text=True,
    )


@pytest.fixture(scope="module")
def cube(tmp_path_factory):
    ramp = looks.Ramp.from_hex(QUE_CALOR_STOPS)
    path = tmp_path_factory.mktemp("cubes") / "look.cube"
    return looks.write_cube(looks.gradient_map(ramp), path, size=17)


@pytest.fixture
def tmp_cache(tmp_path):
    return tmp_path / "cubes"


@pytest.fixture(scope="module")
def env():
    e = probe()
    if not e.available:
        pytest.skip("ffmpeg not usable")
    return e


class TestEveryRegisteredEffectConfigures:
    """The sweep. A catalogue nobody ran is a catalogue of guesses."""

    def test_every_effect_has_parameters_here(self):
        """So the sweep cannot quietly stop covering a new effect."""
        assert set(looks.effects()) == set(PARAMS), (
            "an effect was registered without being added to this sweep"
        )

    @pytest.mark.parametrize("effect", sorted(PARAMS))
    def test_it_produces_a_fragment_ffmpeg_accepts(self, effect, cube, env, tmp_cache):
        _ffmpeg_or_skip()
        params = dict(PARAMS[effect])
        if effect == "lut3d":
            params["cube"] = str(cube)
        plan = compile_look(
            Look(steps=(Effect(name=effect, params=params),)), clip=CLIP, env=env
        )
        # `gradient_map` compiles to a cube REQUEST, because compiling writes no
        # files. Supplying it is a separate verb, and the sweep exercises both.
        from looks.cache import materialize

        plan = materialize(plan, into=tmp_cache)
        fragment = vf(plan)
        proc = configure(fragment)
        assert proc.returncode == 0, (
            f"{effect} compiled to {fragment!r}, which ffmpeg refused:\n"
            f"{proc.stderr[-800:]}"
        )

    def test_a_whole_chain_of_them_configures(self, cube, env):
        """Composed, not just one at a time — the chain is what ships."""
        _ffmpeg_or_skip()
        look = Look(
            steps=(
                Effect(name="fit", params={"target": "320x240"}),
                Effect(name="lut3d", params={"cube": str(cube)}),
                Effect(name="saturation", params={"amount": 1.2}),
                Effect(name="posterize", params={"levels": 8}),
            ),
            name="que-calor-ish",
        )
        fragment = vf(compile_look(look, clip=CLIP, env=env))
        assert configure(fragment).returncode == 0, fragment


class TestTheLgplOneIsTheDefault:
    """Ordering, not a licence judgement — that belongs to Policy."""

    @pytest.mark.parametrize("effect", ["saturation", "contrast", "blur"])
    def test_the_gpl_gated_alternate_sorts_second(self, effect):
        keys = [i.impl for i in looks.REGISTRY.implementations(effect)]
        assert len(keys) == 2, keys
        gated_key = [k for k in keys if looks.REGISTRY.tags(k)]
        assert gated_key, f"{effect}: no alternate is tagged gpl-gated"
        assert keys.index(gated_key[0]) == 1

    def test_a_caller_gets_the_lgpl_one_without_asking(self, env):
        plan = compile_look(
            Look(steps=(Effect(name="saturation", params={"amount": 1.2}),)),
            clip=CLIP, env=env,
        )
        assert plan.steps[0].impl.impl == "saturation.ffmpeg.colorchannelmixer"

    def test_but_can_still_pin_the_other(self, env):
        plan = compile_look(
            Look(
                steps=(
                    Effect(
                        name="saturation",
                        params={"amount": 1.2},
                        impl="saturation.ffmpeg.eq",
                    ),
                )
            ),
            clip=CLIP, env=env,
        )
        assert plan.steps[0].impl.impl == "saturation.ffmpeg.eq"

    def test_the_lgpl_substitute_actually_saturates(self, env):
        """A substitute that does nothing is worse than a refusal.

        Measured against the source rather than asserted: a saturation of 0
        must move the picture, and by more than a no-op would.
        """
        _ffmpeg_or_skip()
        grey = vf(
            compile_look(
                Look(steps=(Effect(name="saturation", params={"amount": 0.0}),)),
                clip=CLIP, env=env,
            )
        )
        proc = subprocess.run(
            ["ffmpeg", "-v", "info", "-f", "lavfi", "-i", SOURCE,
             "-f", "lavfi", "-i", SOURCE,
             "-lavfi", f"[0:v]{grey}[a];[1:v]null[b];[a][b]psnr",
             "-f", "null", "-"],
            capture_output=True, text=True,
        )
        import re

        match = re.search(r"average:(inf|[0-9.]+)", proc.stderr)
        assert match, proc.stderr[-600:]
        assert match.group(1) != "inf", "desaturating did nothing"
        assert float(match.group(1)) < 40, (
            f"desaturating barely moved the picture ({match.group(1)} dB)"
        )


class TestEscaping:
    """First-hand: the failing form and the working form are both run."""

    def test_a_comma_in_a_path_breaks_the_unescaped_form(self, tmp_path, env):
        _ffmpeg_or_skip()
        ramp = looks.Ramp.from_hex(QUE_CALOR_STOPS)
        path = tmp_path / "id,with:comma.cube"
        looks.write_cube(looks.gradient_map(ramp), path, size=17)
        raw = configure(f"lut3d=file={path}")
        assert raw.returncode != 0, "the unescaped form was expected to fail"

    def test_and_the_escaped_form_works(self, tmp_path, env):
        _ffmpeg_or_skip()
        ramp = looks.Ramp.from_hex(QUE_CALOR_STOPS)
        path = tmp_path / "id,with:comma.cube"
        looks.write_cube(looks.gradient_map(ramp), path, size=17)
        plan = compile_look(
            Look(steps=(Effect(name="lut3d", params={"cube": str(path)}),)),
            clip=CLIP, env=env,
        )
        proc = configure(vf(plan))
        assert proc.returncode == 0, f"{vf(plan)!r}\n{proc.stderr[-600:]}"

    def test_a_quote_and_a_bracket_survive_too(self, tmp_path, env):
        _ffmpeg_or_skip()
        ramp = looks.Ramp.from_hex(QUE_CALOR_STOPS)
        path = tmp_path / "it's [one].cube"
        looks.write_cube(looks.gradient_map(ramp), path, size=17)
        plan = compile_look(
            Look(steps=(Effect(name="lut3d", params={"cube": str(path)}),)),
            clip=CLIP, env=env,
        )
        assert configure(vf(plan)).returncode == 0

    def test_percent_is_deliberately_not_escaped(self):
        """The recorded negative. Escaping it produced a backslash that was
        unescaped away again, so it never did anything."""
        assert escape_filter_value("100%") == "100%"

    def test_the_two_levels_are_escaped_in_mirror_order(self):
        r"""A literal colon needs two backslashes and a literal comma one,
        because the graph parser runs first and the option parser second."""
        assert escape_filter_value(":") == "\\\\:"
        assert escape_filter_value(",") == "\\,"


class TestTimelineGating:
    def test_a_span_becomes_an_enable_option(self):
        assert gated("gblur=sigma=2", Span(1.0, 2.0)) == (
            "gblur=sigma=2:enable='between(t,1,2)'"
        )

    def test_every_filter_in_a_chain_is_gated_not_just_the_last(self):
        """`enable` is an option on a filter, not on a chain. Writing it once
        would gate only the final filter — silently."""
        out = gated("scale=2:2,crop=1:1", Span(0.0, 1.0))
        assert out.count("enable=") == 2

    def test_a_gated_fragment_is_accepted_by_ffmpeg(self, env):
        _ffmpeg_or_skip()
        plan = compile_look(
            Look(
                steps=(
                    Effect(
                        name="blur", params={"sigma": 3}, at=Span(0.1, 0.3)
                    ),
                )
            ),
            clip=CLIP, env=env,
        )
        assert configure(vf(plan)).returncode == 0, vf(plan)

    def test_an_ungateable_filter_refuses_the_span_at_COMPILE_time(self, env):
        """`motion` compiles to crop/zoompan, neither of which has timeline
        support — ffmpeg would accept an `enable` option and ignore it, which
        is a look that silently applies everywhere.

        The refusal lands in selection rather than here, which is the better
        place: `timeline` is a candidate FILTER, so an ungateable
        implementation is dropped before a tier is even considered.
        """
        from looks.spec import SpanUnsupported

        with pytest.raises(SpanUnsupported, match="can be gated"):
            compile_look(
                Look(
                    steps=(
                        Effect(
                            name="motion",
                            params=PARAMS["motion"],
                            at=Span(0.1, 0.3),
                        ),
                    )
                ),
                clip=CLIP, env=env,
            )

    def test_and_the_emitter_refuses_too_for_a_plan_built_by_hand(self, env):
        """Belt and braces. A plan is a document; one can be assembled without
        going through selection, and the emitter is the last place to notice."""
        import dataclasses

        plan = compile_look(
            Look(steps=(Effect(name="motion", params=PARAMS["motion"]),)),
            clip=CLIP, env=env,
        )
        forced = dataclasses.replace(
            plan,
            steps=(dataclasses.replace(plan.steps[0], at=Span(0.1, 0.3)),),
        )
        with pytest.raises(FfmpegBackendError, match="no timeline support"):
            vf(forced)


class TestTheBackendStaysOutOfEncoding:
    def test_no_encoder_argument_is_emitted_by_the_module(self):
        """The moment this grows an opinion about an encoder it is the second
        muvid.

        Scanned over string **constants that are not docstrings**, not over the
        raw source: a first draft grepped the file and failed on this module's
        own prose explaining the rule, which would have made the guard read as
        broken rather than as satisfied.
        """
        import ast
        import pathlib

        import looks.ffmpeg

        tree = ast.parse(pathlib.Path(looks.ffmpeg.__file__).read_text())
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            )
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        emitted = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ]
        for forbidden in ("-c:v", "libx264", "-crf", "-preset", "-movflags", "-f"):
            offenders = [s for s in emitted if forbidden in s]
            assert not offenders, f"{forbidden} has no business here: {offenders}"

    def test_a_non_ffmpeg_step_is_refused_rather_than_flattened(self, env):
        reg = register_defaults(EffectRegistry())
        from looks.licence import terms_for
        from looks.spec import ImplRef

        reg.register(
            ImplRef(
                effect="denoise", impl="denoise.frame.numpy", backend="frame",
                terms=terms_for("ffmpeg")[0],
            ),
            lambda params, **kw: {"callable": "denoise.frame.numpy"},
        )
        plan = compile_look(
            Look(steps=(Effect(name="denoise"),)), clip=CLIP, env=env, registry=reg
        )
        with pytest.raises(FfmpegBackendError, match="no filter form"):
            vf(plan)


class TestRegistrationIsIdempotent:
    def test_calling_it_twice_does_not_conflict(self):
        """It runs on import, and a caller may reasonably call it again."""
        before = len(looks.REGISTRY)
        register_defaults()
        assert len(looks.REGISTRY) == before

    def test_a_private_registry_is_independent(self):
        mine = register_defaults(EffectRegistry())
        assert set(mine.effects()) == set(looks.effects())
        assert mine is not looks.REGISTRY


class TestTheFilterStringItself:
    def test_options_with_none_are_dropped(self):
        assert filter_string("scale", {"w": 2, "h": None}) == "scale=w=2"

    def test_no_options_is_the_bare_name(self):
        assert filter_string("null", {}) == "null"


class TestAnOpenEndedSpanIsGatedNotCrashed:
    """`Span` declares both ends `Optional`, and `gated` formatted them blind.

    All three open forms raised a bare `TypeError: unsupported format string
    passed to NoneType.__format__` — not a refusal, not a message, just the
    formatter failing. This is the code path a fold's `enable=` rebase would
    have taken, which is how it surfaced.
    """

    @pytest.mark.parametrize(
        "span,expected",
        [
            (Span(1.0, 2.0), "gblur=sigma=2:enable='between(t,1,2)'"),
            (Span(1.0, None), "gblur=sigma=2:enable='gte(t,1)'"),
            (Span(None, 3.0), "gblur=sigma=2:enable='lte(t,3)'"),
            (Span(None, None), "gblur=sigma=2"),
            (None, "gblur=sigma=2"),
        ],
        ids=["closed", "open-end", "open-start", "open-both", "no-span"],
    )
    def test_every_form_of_span(self, span, expected):
        assert gated("gblur=sigma=2", span) == expected

    def test_a_span_open_at_both_ends_emits_no_gate(self):
        """It bounds nothing, so `enable=` would be an option that always
        evaluates true — noise in the string and a lie in a diff."""
        assert "enable=" not in gated("gblur=sigma=2", Span(None, None))

    @pytest.mark.parametrize(
        "span", [Span(0.1, 0.3), Span(0.1, None), Span(None, 0.3)],
        ids=["closed", "open-end", "open-start"],
    )
    def test_ffmpeg_accepts_each_one(self, span, env):
        """The expressions are different per form, so each needs the binary's
        opinion rather than one representative's."""
        _ffmpeg_or_skip()
        assert configure(gated("gblur=sigma=2", span)).returncode == 0


class TestGatingDoesNotCutInsideAnExpression:
    """`gated()` split on every comma — but rule 21's escaping puts `\\,` inside
    filter options routinely, and this package's own effects produce them.

    Gating the shipped `gamma` effect emitted
    ``lutrgb=r=maxval*pow(val/maxval\\:enable='between(t,1,2)',0.83)`` — the gate
    spliced into the middle of the expression, from a perfectly valid Look.
    """

    @pytest.mark.parametrize("effect,params", [
        ("gamma", {"gamma": 1.2}),
        ("posterize", {"levels": 6}),
        ("saturation", {"amount": 1.3}),
        ("contrast", {"amount": 1.2}),
    ])
    def test_a_gated_expression_effect_still_parses(self, effect, params, env):
        _ffmpeg_or_skip()
        plan = compile_look(
            Look(steps=(Effect(name=effect, params=params, at=Span(1.0, 2.0)),)),
            clip=CLIP, env=env,
        )
        fragment = vf(plan)
        assert ":enable=" in fragment
        assert configure(fragment).returncode == 0, fragment

    def test_an_escaped_comma_does_not_split_a_filter(self):
        from looks.ffmpeg import split_filters

        assert split_filters(r"lutrgb=r=pow(val\,2)") == [r"lutrgb=r=pow(val\,2)"]
        assert len(split_filters(r"lutrgb=r=pow(val\,2),gblur=sigma=1")) == 2

    def test_the_gate_lands_after_the_expression_not_inside_it(self):
        got = gated(r"lutrgb=r=maxval*pow(val/maxval\,0.83)", Span(1, 2))
        assert got.endswith(":enable='between(t,1,2)'")
        assert r"pow(val/maxval\,0.83)" in got


class TestGeometryCannotBeGated:
    """`scale` and `pad` have no timeline support, and ffmpeg refuses the graph
    outright. The registry used to declare `timeline=True` for them, which
    defeated `vf()`'s own guard with its own data — the refusal existed and
    never fired, and the binary rejected the command instead."""

    def test_ffmpeg_really_refuses_a_gated_scale(self):
        _ffmpeg_or_skip()
        proc = configure("scale=32:24:enable='between(t,1,2)'")
        assert proc.returncode != 0
        assert "Timeline" in proc.stderr or "not supported" in proc.stderr

    @pytest.mark.parametrize("effect", ["fit", "fill", "stretch"])
    def test_so_looks_refuses_it_at_selection(self, effect, env):
        from looks.spec import SpanUnsupported

        with pytest.raises(SpanUnsupported, match="can be gated"):
            compile_look(
                Look(steps=(Effect(name=effect, params={"target": "320x240"},
                                   at=Span(1.0, 2.0)),)),
                clip=CLIP, env=env,
            )

    @pytest.mark.parametrize("effect", ["fit", "fill", "stretch"])
    def test_and_ungated_they_still_work(self, effect, env):
        _ffmpeg_or_skip()
        plan = compile_look(
            Look(steps=(Effect(name=effect, params={"target": "320x240"}),)),
            clip=CLIP, env=env,
        )
        assert configure(vf(plan)).returncode == 0
