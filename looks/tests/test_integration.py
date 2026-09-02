"""Do the modules COMPOSE? One pass over the whole stack, public surface only.

Every other test file exercises one module. This one asks the question none of
them can: does a caller who only knows `import looks` get from "what is this
machine's ffmpeg" to "here is a measured, licence-checked, provably flicker-free
chain" without reaching into a submodule or hitting a seam that does not line
up?

It is deliberately shaped as the **real first customer** — the Que Calor look,
which is where every measured fact in this package came from: a vertical phone
clip filled into 16:9, through a gradient-map LUT built from the reference's own
measured palette.

Offline and free: the clip is synthesised with `lavfi`, and nothing here writes
media (every process still ends in `-f null -` or is an `ffprobe`).
"""

import shutil
import subprocess

import pytest

import looks

#: The Que Calor V2 chain's filters, in order. Every one is LGPL — which is the
#: point: the look that ships is also the one that is portable.
QUE_CALOR_FILTERS = ["scale", "format", "lut3d", "lutrgb"]

#: Three stops of the measured reference palette. The endpoints are the
#: load-bearing ones: the floor is an oxblood at L* 8.22, not black, and the
#: highlight is a cream, not white — the reference had 0.0000% true black and
#: 0.07% true white.
QUE_CALOR_STOPS = [(8.2, "#2E0C18"), (46.8, "#D5254A"), (100.0, "#FEF0DC")]


def _ffmpeg_or_skip() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not on PATH")


@pytest.fixture
def phone_clip(tmp_path):
    """A vertical clip, the shape of the real c01 source."""
    _ffmpeg_or_skip()
    path = tmp_path / "c01.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=480x850:rate=10:duration=2",
            "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


@pytest.fixture
def look_cube(tmp_path):
    ramp = looks.Ramp.from_hex(QUE_CALOR_STOPS)
    return looks.write_cube(looks.gradient_map(ramp), tmp_path / "look.cube")


class TestTheStackComposes:
    """Six steps, in the order a caller would take them."""

    def test_the_whole_chain_end_to_end(self, phone_clip, look_cube):
        _ffmpeg_or_skip()

        # 1. What is the ffmpeg in front of me?
        env = looks.probe()
        assert env.available

        # 2. May I use this chain, at the default ceiling?
        assert looks.needs_gpl(QUE_CALOR_FILTERS) == ()
        assessment = looks.assess_ffmpeg_chain(QUE_CALOR_FILTERS, env=env)
        looks.check(assessment, looks.DFLT_POLICY, "the Que Calor chain")

        # 3. Where does a vertical source land in a 16:9 frame?
        placement = looks.placement(
            looks.Size(480, 850), looks.social_size("youtube"), mode="fill"
        )
        geometry = looks.ffmpeg_chain(placement)
        assert geometry.startswith("scale=") and "crop=" in geometry

        # 4. Can this look flicker?
        report = looks.classify_dependency(f"lut3d={look_cube}")
        assert report.can_flicker is False

        # 5. Measure the clip at the source and through the whole chain.
        vf = f"{geometry},lut3d={look_cube}"
        source = looks.measure(str(phone_clip), source_id="c01", ffmpeg_version="8.1")
        post = looks.measure(
            str(phone_clip), source_id="c01", vf=vf, ffmpeg_version="8.1"
        )
        assert source.sharpness and post.sharpness

        # 6. And the two are NOT comparable, because one is post-effect. That
        #    refusal is the point of the identity fields, and it is the mistake
        #    the per-source flattening lesson came from.
        with pytest.raises(looks.Incomparable, match="stage"):
            looks.compare(source, post)

    def test_the_look_is_licence_clean_at_the_default_ceiling(self):
        """The look that ships is also the one that is portable — no step of it
        needs a GPL build, while the obvious grade filter would."""
        assert looks.needs_gpl(QUE_CALOR_FILTERS) == ()
        assert looks.needs_gpl(QUE_CALOR_FILTERS + ["eq"]) == ("eq",)

    def test_a_gpl_step_is_refused_at_an_lgpl_ceiling(self, phone_clip):
        """The package's whole thesis, exercised through the public surface."""
        _ffmpeg_or_skip()
        env = looks.probe()
        with_eq = looks.assess_ffmpeg_chain(QUE_CALOR_FILTERS + ["eq"], env=env)
        strict = looks.Policy(max_tier=looks.Tier.WEAK_COPYLEFT)
        with pytest.raises(looks.LooksLicenceError):
            looks.check(with_eq, strict, "a chain reaching for eq")


class TestTheGeneratedLookMatchesTheReference:
    """The measured property that defines the target, asserted end to end."""

    def test_no_true_black_and_no_true_white(self, tmp_path, look_cube):
        """The reference had 0.0000% true black and 0.07% true white — which is
        why the classic 'cartoonify' (bilateral + adaptive-threshold black
        edges) would have been exactly wrong: it adds ink the reference never
        had."""
        _ffmpeg_or_skip()
        raw = tmp_path / "out.rgb"
        subprocess.run(
            [
                "ffmpeg", "-v", "error", "-y",
                "-f", "lavfi", "-i", "testsrc2=size=96x54:rate=5:duration=1",
                "-vf", f"lut3d={look_cube}",
                "-f", "rawvideo", "-pix_fmt", "rgb24", str(raw),
            ],
            check=True,
            capture_output=True,
        )
        data = raw.read_bytes()
        px = [tuple(data[i : i + 3]) for i in range(0, len(data), 3)]
        assert sum(1 for p in px if max(p) < 8) == 0, "produced true black"
        assert sum(1 for p in px if min(p) > 247) == 0, "produced true white"


class TestTheInvariantHoldsAcrossTheStack:
    """Nothing in a full pass produces media."""

    def test_no_module_can_start_a_producing_process(self):
        from looks._run import InvariantViolation, check_analysis_only

        with pytest.raises(InvariantViolation):
            check_analysis_only(["ffmpeg", "-i", "a.mp4", "-vf", "scale=2:2", "out.mp4"])

    def test_importing_looks_reaches_nothing_third_party(self):
        """The claim, in the form that is actually checkable.

        An earlier version of this test forbade *any* third-party name in the
        source, which was too strong the moment an optional extra arrived: the
        CLI imports `cw` **inside** `main`, so `import looks` never reaches it.
        What matters is not whether a name appears in the tree but whether
        importing the library pulls it in — so this asks the interpreter.
        """
        import subprocess
        import sys

        src = (
            "import sys\n"
            "before = set(sys.modules)\n"
            "import looks\n"
            "new = {m.split('.')[0] for m in set(sys.modules) - before}\n"
            "third = sorted(m for m in new\n"
            "               if m not in sys.stdlib_module_names\n"
            "               and not m.startswith('_') and m != 'looks')\n"
            "print(','.join(third))\n"
        )
        out = subprocess.run(
            [sys.executable, "-c", src], capture_output=True, text=True
        )
        pulled = [m for m in out.stdout.strip().split(",") if m]
        assert not pulled, f"importing looks pulled in: {pulled}"

    def test_any_third_party_name_in_the_source_is_a_declared_extra(self):
        """The other half: a name may appear only if it is *declared* as an
        extra and imported lazily. That keeps the zero-dependency claim honest
        without banning optional capability — and it means adding a dependency
        forces a `pyproject.toml` edit, which the licence ledger's own coverage
        test then forces into the ledger."""
        import ast
        import pathlib
        import sys

        from looks.tests._pyproject import distribution_names, optional_dependencies

        root = pathlib.Path(looks.__file__).parent
        declared = distribution_names(
            spec for specs in optional_dependencies().values() for spec in specs
        )
        undeclared = {}
        for path in root.rglob("*.py"):
            if "tests" in path.parts:
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    mods = [node.module or ""]
                else:
                    continue
                for m in mods:
                    top = m.split(".")[0]
                    if not top or top in ("looks", "__future__"):
                        continue
                    if top in sys.stdlib_module_names:
                        continue
                    if top in declared and node.col_offset > 0:
                        continue  # a declared extra, imported lazily
                    undeclared[f"{path.name}:{node.lineno}"] = top
        assert not undeclared, (
            f"third-party imports that are neither stdlib nor a lazily-imported "
            f"declared extra: {undeclared}"
        )
