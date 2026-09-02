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
        """Every filter the committed table calls GPL-only must be present in a
        GPL build. (The converse does not hold — a GPL build may also lack a
        filter for reasons of its own, like a missing external library.)"""
        _ffmpeg_or_skip()
        env = probe()
        if env.licence not in (Licence.GPL2, Licence.GPL3):
            pytest.skip(f"this ffmpeg is {env.licence.value}, not a GPL build")
        # boxblur_opencl needs OpenCL and is legitimately absent from most builds.
        expected = gpl_only_filters() - {"boxblur_opencl"}
        missing = sorted(expected - env.filters)
        assert not missing, (
            f"the table calls these GPL-only but this GPL build lacks them: {missing}"
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
