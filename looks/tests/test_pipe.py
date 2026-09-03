"""The pipe: what runs, in how many processes, and the one place folding lies.

The load-bearing test here is
:meth:`TestRule27IsReal.test_folding_a_gated_step_moves_it_to_the_wrong_second`,
which does not assert anything about `looks` at all — it measures **ffmpeg**, to
show that the rule this module exists to enforce describes something real. A
guard against a hazard nobody has demonstrated is a guard against a belief.

Measured there, on a flat source with a gate at t=4..5 and an output-side seek
of 3 s:

===========================  ==============  ====
arrangement                  bright frames   n
===========================  ==============  ====
unfolded (the truth)         10-20           11
folded, gate unchanged       **40-49**       10
folded, rebased by 3.0       10-20           11
===========================  ==============  ====

The wrong answer is not slightly wrong. It is a different second of the clip,
for a different duration, at exit 0 with an empty stderr.
"""

import json
import shutil
import subprocess

import pytest

from looks import ClipSpec, Effect, Look, compile_look, probe
from looks.licence import terms_for
from looks.pipe import (
    DFLT_PIPE_PIX_FMT,
    FilterSegment,
    FrameSegment,
    PipeError,
    PipePlan,
    describe,
    pipe_plan,
    runs,
)
from looks.registry import EffectRegistry
from looks.spec import ImplRef, Span

CLIP = ClipSpec(width=64, height=48, fps=10)
SEEKED = ClipSpec(width=64, height=48, fps=10, origin_s=3.0)


def _ffmpeg_or_skip():
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not on PATH")


@pytest.fixture
def env():
    e = probe()
    if not e.available:
        pytest.skip("ffmpeg not usable")
    return e


@pytest.fixture
def registry():
    """The built-ins plus one frame operation, so a pipe has something to hold.

    Registered here rather than shipped: a frame `flatten` needs `Terms` for the
    provider that implements it, and this package's own decisions document says
    the OpenCV tier is the owner's adjudication and not `looks`' to make.
    """
    from looks.ffmpeg import register_defaults

    reg = register_defaults(EffectRegistry())
    reg.register(
        ImplRef(
            effect="meanshift",
            impl="meanshift.frame.reference",
            backend="frame",
            terms=terms_for("ffmpeg")[0],
        ),
        lambda params, **kw: {"op": "meanshift.frame.reference"},
    )
    return reg


def plan_of(steps, *, registry, env, clip=CLIP):
    return compile_look(Look(steps=tuple(steps)), clip=clip, env=env, registry=registry)


class TestRunsAndFolding:
    def test_an_empty_plan_arranges_to_nothing(self, env, registry):
        arranged = pipe_plan(plan_of([], registry=registry, env=env), source="in.mp4")
        assert len(arranged) == 0 and arranged.boundaries == 0

    def test_pure_ffmpeg_is_one_process_and_no_boundary(self, env, registry):
        plan = plan_of(
            [Effect(name="blur", params={"sigma": 2}), Effect(name="sharpen")],
            registry=registry, env=env,
        )
        assert len(runs(plan)) == 1
        arranged = pipe_plan(plan, source="in.mp4")
        assert arranged.boundaries == 0
        assert isinstance(arranged.segments[0], FilterSegment)
        assert "gblur" in arranged.segments[0].vf and "unsharp" in arranged.segments[0].vf

    def test_ffmpeg_either_side_of_a_frame_op_is_ONE_boundary(self, env, registry):
        """The fold. Three runs become one process pair, not three processes —
        which is the difference between one decode and three."""
        plan = plan_of(
            [
                Effect(name="blur", params={"sigma": 2}),
                Effect(name="meanshift"),
                Effect(name="posterize", params={"levels": 6}),
            ],
            registry=registry, env=env,
        )
        assert len(runs(plan)) == 3, "three runs before folding"
        arranged = pipe_plan(plan, source="in.mp4")
        assert arranged.boundaries == 1, "but only one raw-frame crossing"
        segment = arranged.segments[0]
        assert isinstance(segment, FrameSegment)
        assert "gblur" in " ".join(segment.decode), "the before-run folded into decode"
        assert "lutrgb" in " ".join(segment.encode), "the after-run folded into encode"

    def test_two_frame_ops_back_to_back_are_refused(self, env, registry):
        registry.register(
            ImplRef(effect="other", impl="other.frame.reference", backend="frame",
                    terms=terms_for("ffmpeg")[0]),
            lambda params, **kw: {"op": "other.frame.reference"},
        )
        plan = plan_of(
            [Effect(name="meanshift"), Effect(name="other")], registry=registry, env=env
        )
        with pytest.raises(PipeError, match="back to back"):
            pipe_plan(plan, source="in.mp4")


class TestWhatIsEmitted:
    @pytest.fixture
    def segment(self, env, registry):
        plan = plan_of(
            [Effect(name="blur", params={"sigma": 2}), Effect(name="meanshift")],
            registry=registry, env=env,
        )
        return pipe_plan(plan, source="in.mp4").segments[0]

    def test_neither_half_names_an_encoder(self, segment):
        """The codec, container and destination are the host's. This is also
        what keeps the package's own AST perimeter satisfied by construction."""
        text = " ".join(segment.decode) + " " + " ".join(segment.encode)
        for tell in ("-c:v", "-vcodec", "-crf", "-preset", "libx264", "-b:v"):
            assert tell not in text, tell

    def test_the_encoder_stops_at_its_filter_chain(self, segment):
        assert segment.encode[-2] == "-vf" or segment.encode[-1] == "-i" or (
            "-i" in segment.encode
        )
        assert not any(str(a).endswith(".mp4") for a in segment.encode)

    def test_both_halves_are_refused_by_this_packages_own_chokepoint(self, segment):
        """`looks` does not merely decline to run these — it cannot. Asserted
        because 'we simply never call it' is a convention, and a refusal is a
        mechanism."""
        from looks._run import InvariantViolation, check_analysis_only

        for argv in (segment.decode, segment.encode):
            with pytest.raises(InvariantViolation):
                check_analysis_only(list(argv))

    def test_the_pixel_contract_is_explicit(self, segment):
        """rawvideo has no header, so a reader that guesses the stride gets a
        sheared picture rather than an error."""
        assert segment.pix_fmt == DFLT_PIPE_PIX_FMT
        assert segment.frame_bytes == 64 * 48 * 3
        assert "-s" in segment.decode and "64x48" in segment.decode

    def test_the_rate_is_declared_on_BOTH_halves(self, segment):
        """Omitted, the rawvideo demuxer defaults to 25 — which rescales every
        time-based expression in the folded chain without saying so."""
        assert "-r" in segment.decode and "-r" in segment.encode
        assert segment.encode[segment.encode.index("-r") + 1] == "10"

    def test_the_op_is_a_registry_key(self, segment):
        """Never a `module:attr` import path — a plan is a document, and a
        document that can name `os:system` is an RCE primitive with a schema."""
        assert segment.op == "meanshift.frame.reference"
        assert ":" not in segment.op

    def test_the_arrangement_is_json(self, env, registry):
        plan = plan_of([Effect(name="meanshift")], registry=registry, env=env)
        document = pipe_plan(plan, source="in.mp4").to_dict()
        assert json.loads(json.dumps(document))["boundaries"] == 1


class TestTheRebase:
    """Rule 27, as `looks` implements it."""

    def test_a_span_after_the_frame_op_is_rebased_by_the_origin(self, env, registry):
        plan = plan_of(
            [
                Effect(name="meanshift"),
                Effect(name="blur", params={"sigma": 2}, at=Span(4.0, 5.0)),
            ],
            registry=registry, env=env, clip=SEEKED,
        )
        encode = " ".join(pipe_plan(plan, source="in.mp4").segments[0].encode)
        assert "between(t,1,2)" in encode, encode

    def test_a_span_BEFORE_the_frame_op_is_left_alone(self, env, registry):
        """Folding into the decoder is always safe — it reads a container and
        keeps the host's timeline. Rebasing it would be the bug."""
        plan = plan_of(
            [
                Effect(name="blur", params={"sigma": 2}, at=Span(4.0, 5.0)),
                Effect(name="meanshift"),
            ],
            registry=registry, env=env, clip=SEEKED,
        )
        decode = " ".join(pipe_plan(plan, source="in.mp4").segments[0].decode)
        assert "between(t,4,5)" in decode, decode

    def test_an_origin_of_zero_rebases_to_itself(self, env, registry):
        """The common case — an input-side seek already starts the timeline at
        0 — so the fold is a semantic no-op and must stay one."""
        plan = plan_of(
            [
                Effect(name="meanshift"),
                Effect(name="blur", params={"sigma": 2}, at=Span(4.0, 5.0)),
            ],
            registry=registry, env=env,
            clip=ClipSpec(width=64, height=48, fps=10, origin_s=0.0),
        )
        encode = " ".join(pipe_plan(plan, source="in.mp4").segments[0].encode)
        assert "between(t,4,5)" in encode

    def test_an_UNDECLARED_origin_under_a_gated_fold_is_refused(self, env, registry):
        """Not assumed to be 0. That is right for an input-side seek and wrong
        for an output-side one, and the difference is a look on the wrong
        frames with no error anywhere."""
        plan = plan_of(
            [
                Effect(name="meanshift"),
                Effect(name="blur", params={"sigma": 2}, at=Span(4.0, 5.0)),
            ],
            registry=registry, env=env, clip=CLIP,
        )
        with pytest.raises(PipeError, match="origin_s"):
            pipe_plan(plan, source="in.mp4")

    def test_an_undeclared_origin_is_fine_with_no_gate(self, env, registry):
        """The refusal is about spans, not about pipes. A plan with nothing
        gated needs no origin and must not be asked for one."""
        plan = plan_of(
            [Effect(name="meanshift"), Effect(name="blur", params={"sigma": 2})],
            registry=registry, env=env, clip=CLIP,
        )
        assert pipe_plan(plan, source="in.mp4").boundaries == 1

    def test_a_foreign_enable_in_a_filter_string_is_refused(self, env, registry):
        """`looks` rebases a span it generated and refuses one it did not:
        rewriting an arbitrary ffmpeg expression cannot be checked."""
        import dataclasses

        plan = plan_of(
            [Effect(name="meanshift"), Effect(name="blur", params={"sigma": 2})],
            registry=registry, env=env, clip=SEEKED,
        )
        smuggled = dataclasses.replace(
            plan.steps[1],
            at=Span(1.0, 2.0),
            payload={"filter": "gblur=sigma=2:enable='lt(t,3)'"},
        )
        forged = dataclasses.replace(plan, steps=(plan.steps[0], smuggled))
        with pytest.raises(PipeError, match="carries an `enable=`"):
            pipe_plan(forged, source="in.mp4")


class TestRule27IsReal:
    """Measured on ffmpeg, not asserted about `looks`.

    A guard against a hazard nobody has demonstrated is a guard against a
    belief. So this reproduces the hazard itself.
    """

    SIZE = (64, 48)
    GATE = "lutyuv=y='clip(val+80,0,255)':enable='between(t,{a},{b})'"

    def _source(self, tmp_path):
        path = tmp_path / "flat.mp4"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
             "-i", "color=c=gray:s=64x48:r=10:d=8",
             "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", str(path)],
            check=True, capture_output=True,
        )
        return path

    def _bright(self, data):
        w, h = self.SIZE
        per = w * h
        lum = [data[i * per] for i in range(len(data) // per)]
        return [i for i, v in enumerate(lum) if v > lum[0] + 20]

    def test_folding_a_gated_step_moves_it_to_the_wrong_second(self, tmp_path):
        _ffmpeg_or_skip()
        source = self._source(tmp_path)
        gate = self.GATE.format(a=4, b=5)

        truth = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(source), "-ss", "3",
             "-vf", gate, "-f", "rawvideo", "-pix_fmt", "gray", "-"],
            capture_output=True,
        ).stdout
        piped = subprocess.run(
            f'ffmpeg -v error -i "{source}" -ss 3 -an -f rawvideo -pix_fmt bgr24 '
            f'-s 64x48 -r 10 - | ffmpeg -v error -f rawvideo -pix_fmt bgr24 '
            f'-s 64x48 -r 10 -i - -vf "{gate}" -f rawvideo -pix_fmt gray -',
            shell=True, capture_output=True,
        ).stdout

        assert self._bright(truth), "the unfolded gate must fire at all"
        assert self._bright(truth) != self._bright(piped), (
            "folding was expected to move the gate; if this ever passes, the "
            "rule this module enforces has stopped being true and the module "
            "should be revisited rather than the test relaxed"
        )
        assert min(self._bright(piped)) - min(self._bright(truth)) == 30, (
            "the shift should be exactly the origin in frames (3 s at 10 fps)"
        )

    def test_and_the_rebase_puts_it_back(self, tmp_path):
        _ffmpeg_or_skip()
        source = self._source(tmp_path)
        truth = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(source), "-ss", "3",
             "-vf", self.GATE.format(a=4, b=5),
             "-f", "rawvideo", "-pix_fmt", "gray", "-"],
            capture_output=True,
        ).stdout
        rebased = subprocess.run(
            f'ffmpeg -v error -i "{source}" -ss 3 -an -f rawvideo -pix_fmt bgr24 '
            f'-s 64x48 -r 10 - | ffmpeg -v error -f rawvideo -pix_fmt bgr24 '
            f'-s 64x48 -r 10 -i - -vf "{self.GATE.format(a=1, b=2)}" '
            f'-f rawvideo -pix_fmt gray -',
            shell=True, capture_output=True,
        ).stdout
        assert self._bright(rebased) == self._bright(truth)


class TestTheLgplFlatten:
    def test_it_is_registered_and_needs_no_gpl_build(self):
        import looks

        assert "flatten" in looks.effects()
        assert looks.needs_gpl(["bilateral"]) == ()

    def test_it_compiles_and_ffmpeg_accepts_it(self, env, registry):
        _ffmpeg_or_skip()
        from looks.ffmpeg import vf

        fragment = vf(plan_of([Effect(name="flatten")], registry=registry, env=env))
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi",
             "-i", "testsrc2=size=64x48:rate=5:duration=0.2",
             "-vf", fragment, "-f", "null", "-"],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stderr[-400:]

    def test_it_actually_reduces_edge_energy(self, env, registry):
        """A flatten that does not flatten is worse than an absent one."""
        _ffmpeg_or_skip()
        from looks.ffmpeg import vf

        def energy(chain):
            data = subprocess.run(
                ["ffmpeg", "-v", "error", "-f", "lavfi",
                 "-i", "testsrc2=size=320x240:rate=10:duration=0.2",
                 "-vf", chain, "-frames:v", "1",
                 "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                capture_output=True,
            ).stdout
            rows = [data[y * 320 : (y + 1) * 320] for y in range(240)]
            diffs = [abs(r[x + 1] - r[x]) for r in rows for x in range(319)]
            return sum(diffs) / len(diffs)

        flat = vf(plan_of([Effect(name="flatten")], registry=registry, env=env))
        assert energy(flat) < energy("null")

    def test_it_filters_all_three_planes(self, env, registry):
        """bilateral's default is luma only, which smooths the detail and
        leaves the chroma noise the flatten was for."""
        from looks.ffmpeg import vf

        assert "planes=7" in vf(
            plan_of([Effect(name="flatten")], registry=registry, env=env)
        )


class TestDescribe:
    def test_it_says_how_many_boundaries(self, env, registry):
        plan = plan_of(
            [Effect(name="blur", params={"sigma": 2}), Effect(name="meanshift")],
            registry=registry, env=env,
        )
        text = describe(pipe_plan(plan, source="in.mp4"))
        assert "raw-frame boundaries: 1" in text

    def test_a_single_process_says_so(self, env, registry):
        plan = plan_of([Effect(name="blur", params={"sigma": 2})],
                       registry=registry, env=env)
        assert "none: one process" in describe(pipe_plan(plan, source="in.mp4"))

    def test_an_empty_pipe(self):
        assert describe(PipePlan(segments=(), boundaries=0)) == "(empty pipe)"
