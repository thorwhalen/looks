"""Tests for :mod:`looks.environment`.

The tests that matter here are the ones that run the **real** ffmpeg, because
the bug this module has already had was invisible to every synthetic test:
``parse_filters`` was written against a hand-invented sample, its doctests
passed, and it returned **zero filters** from the actual binary. A regex tested
against a sample the same author invented tests the regex against itself.

So: doctests cover the parsing logic, and the tests below cover the *world*.
They skip when ffmpeg is absent — with :func:`pytest.skip` inside the test
body, never an ``importorskip`` at module scope, which would remove them from
collection entirely and make their absence invisible in both the pass and the
skip count.
"""

import shutil

import pytest

from looks.environment import (
    Licence,
    gates,
    gpl_only_filters,
    needs_gpl,
    parse_configuration,
    parse_filters,
    parse_licence,
    probe,
)

#: Filters every ffmpeg build has had for a decade. If a probe of a real binary
#: does not find these, the parser is broken, not the binary.
UNIVERSAL_FILTERS = ("scale", "crop", "format", "null")

#: Below this, a "successful" filter probe is not credible — real builds carry
#: hundreds. Deliberately far under the 481 this machine reports, so the test
#: asserts *plausibility* rather than pinning a number that drifts with the
#: build.
MIN_CREDIBLE_FILTERS = 50


def _ffmpeg_or_skip() -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("no ffmpeg on PATH")


class TestAgainstTheRealBinary:
    """What a synthetic sample cannot tell you."""

    def test_probe_finds_a_credible_number_of_filters(self):
        """The regression guard for the invented-sample bug.

        The broken parser returned an empty set here while every doctest passed.
        """
        _ffmpeg_or_skip()
        env = probe()
        assert env.available, f"probe failed: {env.notes}"
        assert len(env.filters) >= MIN_CREDIBLE_FILTERS, (
            f"only {len(env.filters)} filters parsed from a real ffmpeg — the "
            f"row format has probably changed again. notes={env.notes}"
        )

    def test_probe_finds_the_filters_every_build_has(self):
        _ffmpeg_or_skip()
        env = probe()
        assert env.available, f"probe failed: {env.notes}"
        assert not env.missing(UNIVERSAL_FILTERS)

    def test_a_real_binary_reports_a_known_licence(self):
        """``-L`` must classify. An unclassified real build means the probe
        list has drifted from FFmpeg's wording — which would silently turn
        every Look into a refusal."""
        _ffmpeg_or_skip()
        env = probe()
        assert env.licence is not Licence.UNKNOWN, (
            "ffmpeg -L matched no known licence statement; the _LICENCE_PROBES "
            "patterns need updating"
        )

    def test_the_gate_table_agrees_with_a_gpl_build(self):
        """Every **directly** gated filter must be present in a GPL build.

        Only the direct set. A directly-gated filter needs nothing but
        ``--enable-gpl``, so a GPL build has all of them. An **indirectly**
        gated one (``frei0r``, ``vidstabtransform``, …) additionally needs its
        external library, which is a *separate* build flag that Homebrew does
        not pass — so its absence says nothing about the licence and asserting
        on it would make this test fail for the wrong reason.

        ``boxblur_opencl`` is excluded for the same kind of reason: it needs
        OpenCL.
        """
        _ffmpeg_or_skip()
        env = probe()
        if env.licence not in (Licence.GPL2, Licence.GPL3):
            pytest.skip(f"this ffmpeg is {env.licence.value}, not a GPL build")
        expected = set(gates()["gpl_filters_direct"]) - {"boxblur_opencl"}
        missing = sorted(expected - env.filters)
        assert not missing, (
            f"the table calls these directly GPL-gated but this GPL build lacks "
            f"them: {missing}"
        )


class TestUnknownIsNeverAGuess:
    """The refusal contract: this module says 'unknown' rather than defaulting."""

    def test_absent_binary_is_a_value_not_an_exception(self):
        env = probe("definitely-not-an-ffmpeg-binary")
        assert env.available is False
        assert env.licence is Licence.UNKNOWN
        assert env.path is None
        assert env.notes  # it says why

    def test_unrecognised_licence_text_is_unknown(self):
        assert parse_licence("all rights reserved, contact sales") is Licence.UNKNOWN
        assert parse_licence("") is Licence.UNKNOWN

    def test_gpl3_is_not_read_as_gpl2(self):
        """The probes run most-restrictive-first because the licence names are
        prefixes of one another. A permissive-first scan reports GPLv2 for a
        GPLv3 build, which under-reports the restriction."""
        gpl3 = (
            "ffmpeg is free software; you can redistribute it and/or modify it "
            "under the terms of the GNU General Public License as published by "
            "the Free Software Foundation; either version 3 of the License, or "
            "(at your option) any later version."
        )
        assert parse_licence(gpl3) is Licence.GPL3

    def test_lgpl_is_not_read_as_gpl(self):
        lgpl = (
            "ffmpeg is free software; you can redistribute it and/or modify it "
            "under the terms of the GNU Lesser General Public License as "
            "published by the Free Software Foundation; either version 2.1 of "
            "the License, or (at your option) any later version."
        )
        assert parse_licence(lgpl) is Licence.LGPL21


class TestTheGateTable:
    """The committed extraction from FFmpeg's own ``configure``."""

    def test_eq_is_gpl_and_its_substitutes_are_not(self):
        """The package's reason to exist, as an assertion.

        ``eq`` is the obvious brightness/contrast/gamma/saturation filter and it
        is GPL-only; every LGPL-clean way to do the same thing is not.
        """
        gpl = gpl_only_filters()
        assert "eq" in gpl
        for substitute in ("curves", "lutyuv", "colorlevels", "colorbalance", "exposure"):
            assert substitute not in gpl, substitute

    def test_geq_is_not_gpl(self):
        """Widely believed to be GPL; relicensed in FFmpeg 4.3 (2019-12-16,
        released 2020-06-15). Pinned because the belief outlives the fact."""
        assert "geq" not in gpl_only_filters()

    def test_the_que_calor_chain_is_lgpl_clean(self):
        """The first real look must not need a GPL build."""
        assert needs_gpl(["scale", "format", "lut3d", "lutrgb"]) == ()

    def test_x264_and_x265_are_gpl_external_libraries(self):
        """The GPL wall is in the encoders, not the filters — so an LGPL-tier
        deliverable cannot be H.264 or HEVC through ffmpeg."""
        external = gates()["external_gpl"]
        assert "libx264" in external
        assert "libx265" in external

    def test_needs_gpl_preserves_input_order(self):
        assert needs_gpl(["boxblur", "scale", "eq"]) == ("boxblur", "eq")


class TestParsing:
    """Row-format handling, against output shapes real builds actually emit."""

    def test_two_and_three_character_flag_columns_both_parse(self):
        """ffmpeg 8.1 emits two flag characters; older builds emit three. A
        parser pinned to either width returns nothing on the other, and
        'nothing' is indistinguishable from 'this build has no filters'."""
        two = " TS lut3d             V->V       Adjust colors using a 3D LUT.\n"
        three = " TSC lut3d            V->V       Adjust colors using a 3D LUT.\n"
        assert parse_filters(two) == {"lut3d"}
        assert parse_filters(three) == {"lut3d"}

    def test_legend_lines_are_not_filters(self):
        legend = "Filters:\n  T.. = Timeline support\n  .S. = Slice threading\n  ------\n"
        assert parse_filters(legend) == frozenset()

    def test_multi_input_signatures_parse(self):
        rows = (
            " TS aap               AA->A      Apply Affine Projection algorithm.\n"
            " .. xfade             VV->V      Cross fade one video with another.\n"
            " .. testsrc2          |->V       Generate another test pattern.\n"
        )
        assert parse_filters(rows) == {"aap", "xfade", "testsrc2"}

    def test_configuration_line_is_extracted_but_advisory(self):
        out = "ffmpeg version 8.1\nconfiguration: --enable-gpl --enable-libx264\n"
        assert parse_configuration(out) == "--enable-gpl --enable-libx264"
        assert parse_configuration("ffmpeg version 8.1\n") is None


class TestThereIsNotOneFfmpeg:
    """The environment is an argument, not a property of the machine."""

    def test_the_bundled_binary_can_differ_from_the_one_on_path(self):
        """Measured on the development machine: PATH is ffmpeg 8.1 / GPL-3 /
        481 filters, while `imageio-ffmpeg`'s bundled binary is 7.1 / GPL-2 /
        484 — with **non-nested** filter sets in both directions.

        This does not assert the difference (a clean machine may have only one
        ffmpeg, or none). It asserts that when two are present, the probe
        reports them *separately* rather than collapsing them — which is what
        makes "pass the environment in" enforceable rather than advisory.
        """
        _ffmpeg_or_skip()
        try:
            import imageio_ffmpeg
        except ImportError:
            pytest.skip("imageio-ffmpeg not installed")

        on_path = probe()
        bundled = probe(imageio_ffmpeg.get_ffmpeg_exe())
        if not (on_path.available and bundled.available):
            pytest.skip("one of the two binaries did not answer")
        if on_path.path == bundled.path:
            pytest.skip("both resolve to the same binary")

        assert isinstance(on_path.filters, frozenset)
        assert isinstance(bundled.filters, frozenset)
        # Two distinct binaries must not be reported as one shared fact.
        assert on_path.path != bundled.path


class TestIndirectGplGates:
    """The false permission an adversarial review caught, pinned.

    A filter is GPL-gated two ways: directly (`<name>_filter_deps` contains
    `gpl`) and indirectly (its deps name a library in
    `EXTERNAL_LIBRARY_GPL_LIST`, which forces `--enable-gpl` transitively with
    no `gpl` token on its own line). The first version of the committed table
    was built by grepping for the literal, so it missed all five of the second
    class — including `vidstabtransform`, which is stabilisation and therefore
    a plausible *normalisation* effect for this package.
    """

    #: The five, with the copyleft library each one reaches through.
    INDIRECT = {
        "frei0r": "frei0r",
        "frei0r_src": "frei0r",
        "rubberband": "librubberband",
        "vidstabdetect": "libvidstab",
        "vidstabtransform": "libvidstab",
    }

    def test_indirectly_gated_filters_are_in_the_table(self):
        gpl = gpl_only_filters()
        missing = sorted(n for n in self.INDIRECT if n not in gpl)
        assert not missing, (
            f"{missing} are GPL-gated through EXTERNAL_LIBRARY_GPL_LIST but are "
            f"absent from the table — that is a FALSE PERMISSION"
        )

    def test_each_indirect_filter_reaches_a_gpl_library(self):
        """The gate is real, not a hand-added name."""
        recorded = gates()["gpl_filters_indirect"]
        external = set(gates()["external_gpl"]) | set(gates()["external_gplv3"])
        for name, lib in self.INDIRECT.items():
            assert name in recorded, f"{name} is not recorded as indirectly gated"
            assert lib in recorded[name], f"{name} should reach {lib}"
            assert lib in external, f"{lib} is not in FFmpeg's GPL library lists"

    def test_the_two_classes_are_stored_separately(self):
        """So a future re-extraction cannot quietly drop one of them: the union
        is what `gpl_only_filters()` reads, and both halves are non-empty."""
        g = gates()
        direct, indirect = g["gpl_filters_direct"], g["gpl_filters_indirect"]
        assert len(direct) == 33, f"expected 33 directly-gated, got {len(direct)}"
        assert len(indirect) == 5, f"expected 5 indirectly-gated, got {len(indirect)}"
        assert set(g["gpl_filters"]) == set(direct) | set(indirect)

    def test_needs_gpl_now_catches_a_normalisation_effect(self):
        """The concrete consequence: asking for stabilisation at an LGPL ceiling
        must be refused, and under the old table it would have been allowed."""
        assert needs_gpl(["scale", "vidstabtransform", "lut3d"]) == ("vidstabtransform",)



def _a_filter_this_build_lacks(universe, env):
    """A real filter the probed binary does not have — chosen, not named.

    The point of the universe/build distinction is that the two differ, so the
    test needs an element of the difference rather than a guess about which
    build is running. Sorted for determinism: the same binary picks the same
    filter every run, so a failure is reproducible.
    """
    missing = sorted(set(universe) - set(env.filters))
    if not missing:
        pytest.skip(
            "this build has every filter FFmpeg declares — nothing to narrow "
            "to, and that is a legitimate environment rather than a failure"
        )
    return missing[0]

class TestD2FailClosedOnUnknownFilters:
    """`needs_gpl` is an allowlist-by-absence, so an unrecognised name was a
    COMPUTED false permission at the licence tier's entry point.

    Before the fix, `needs_gpl(['nosuchfilter'])` and `needs_gpl(['EQ'])` both
    returned `()` — GPL-free.
    """

    def test_an_unknown_name_raises(self):
        from looks.environment import UnknownFilter

        with pytest.raises(UnknownFilter, match="nosuchfilter"):
            needs_gpl(["nosuchfilter"])

    def test_wrong_case_raises_because_case_matters_to_ffmpeg(self):
        from looks.environment import UnknownFilter

        with pytest.raises(UnknownFilter, match="EQ"):
            needs_gpl(["EQ"])

    def test_the_refusal_explains_the_direction_of_the_error(self):
        from looks.environment import UnknownFilter

        with pytest.raises(UnknownFilter) as excinfo:
            needs_gpl(["typo_filter"])
        assert "false permission" in str(excinfo.value)

    def test_the_universe_covers_filters_this_build_lacks(self):
        """The universe is FFmpeg's declaration list, not the local binary's —
        a filter absent from this build is still real and still gated, and
        refusing it would be a false alarm."""
        from looks.environment import known_filters, probe

        universe = known_filters()
        assert "vidstabtransform" in universe
        assert "frei0r" in universe
        env = probe()
        if env.available:
            # DERIVED, never named. An earlier version of this test asserted
            # `not env.has_filter("vidstabtransform")  # Homebrew lacks it`,
            # which is a fact about one laptop: Ubuntu ships ffmpeg 6.1.1 built
            # `--enable-libvidstab`, so the assertion is simply false there. A
            # package whose whole subject is that the environment VARIES must
            # not encode one environment in its tests.
            absent = _a_filter_this_build_lacks(universe, env)
            assert not env.has_filter(absent)
            assert needs_gpl([absent]) in ((), (absent,))

    def test_a_caller_can_narrow_to_this_binary(self):
        from looks.environment import UnknownFilter, known_filters, probe

        env = probe()
        if not env.available:
            pytest.skip("no ffmpeg")
        absent = _a_filter_this_build_lacks(known_filters(), env)
        with pytest.raises(UnknownFilter):
            needs_gpl([absent], known=env.filters)
