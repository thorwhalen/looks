# Evidence: the colour trap in an ffmpeg colour chain is RANGE, not pixel format

*2026-09-02. Measured by the orchestrating session on ffmpeg 8.1 (homebrew, `--enable-gpl --enable-version3`), independently of the research agents. Every command below was run; the hashes are real.*

## Verdict

The trap everyone warns about — "insert `format=rgb24` before your LUT or you will grade in YUV" — **is not a trap in ffmpeg 8.1**. Filter format negotiation handles it, and an explicit `format=` before `lut3d` is a byte-for-byte no-op. So the compiler does **not** need to sprinkle `format=` conversions, and doing so would be cargo cult.

The trap that IS real is **colour range**, and it is silent. A source whose range is untagged (`color_range=unknown`, which is what `ffmpeg` itself produces by default, and what phone footage generally carries) is *assumed* limited. If it is actually full-range — common for screen recordings and some cameras — every colour operation downstream is applied to wrongly-expanded values, with **no warning anywhere**. Measured on a 160×90×10-frame probe, the same LUT under the two assumptions differs on **99.6% of bytes**, by up to **15/255**, mean **6.05/255**.

That is not a rounding difference. It is a visible shift, it is invisible in the command line, and nothing in the pipeline reports it.

**The rule this buys `looks`:** a clip's `color_range` is part of its measured state, and "untagged" is a **third value**, not a synonym for "limited". A spec layer that reports it is doing the one thing the execution layer structurally cannot.

## The experiment

```bash
# a deliberately non-identity 2x2x2 gradient-map .cube (probe.cube)
ffmpeg -y -f lavfi -i "testsrc2=size=160x90:rate=10:duration=1" \
       -c:v libx264 -crf 0 -pix_fmt yuv420p src.mp4

ffmpeg -i src.mp4 -vf "lut3d=probe.cube"                               -f rawvideo -pix_fmt rgb24 C.rgb
ffmpeg -i src.mp4 -vf "format=rgb24,lut3d=probe.cube"                  -f rawvideo -pix_fmt rgb24 D.rgb
ffmpeg -i src.mp4 -vf "scale=in_range=limited:out_range=full,format=rgb24,lut3d=probe.cube" -f rawvideo -pix_fmt rgb24 E.rgb
ffmpeg -i src.mp4 -vf "scale=in_range=full:out_range=full,format=rgb24,lut3d=probe.cube"    -f rawvideo -pix_fmt rgb24 F.rgb
```

| variant | md5 of decoded RGB | reading |
|---|---|---|
| C — `lut3d` alone | `e8eefff5c336…` | the baseline |
| D — explicit `format=rgb24` first | `e8eefff5c336…` | **identical to C.** The conversion is automatic; the explicit one is a no-op |
| E — declared `in_range=limited` | `e8eefff5c336…` | **identical to C.** Limited is what ffmpeg assumes for untagged yuv420p |
| F — declared `in_range=full` | `ae8197856052…` | **different.** 99.6% of bytes, max 15/255, mean 6.05/255 |

And the source itself:

```
$ ffprobe -select_streams v:0 -show_entries stream=color_range,color_space,pix_fmt -of default=nw=1 src.mp4
pix_fmt=yuv420p
color_range=unknown
color_space=unknown
```

`ffmpeg` produced that file seconds earlier and did not tag it. The untagged case is the **normal** case, not the exotic one.

## A second, unrelated finding from the same setup: `lavfi` is bit-exact

```bash
for i in 1 2; do ffmpeg -f lavfi -i "testsrc2=size=160x90:rate=10:duration=1" -f rawvideo -pix_fmt rgb24 raw$i.rgb; done
md5 -q raw1.rgb raw2.rgb
# 7dd42378b1b3305bf1ccb8151bb1bafa
# 7dd42378b1b3305bf1ccb8151bb1bafa
```

`testsrc2` is byte-reproducible across runs, so **the test suite needs no committed media**: synthesise a source, apply a Look, hash the decoded frames. Free, hermetic, deterministic — the same shape as `an`'s golden corpus, without the repository weight. Any golden that survives this is comparing *decoded pixels*, never encoded bytes, which is the only comparison that holds across machines (an encoded mp4 is not byte-comparable across builds — see the fleet's `ffmpeg/x264 colour tags` note).

## What this does NOT establish

Only `lut3d` was probed for the format question. A filter that accepts *both* RGB and YUV — `eq` (GPL-only anyway), `hue`, `curves` — may negotiate YUV and give a different result from the same operation in RGB, because the operation itself is defined on whatever plane it gets. That is a per-filter fact and belongs in the effect catalogue, effect by effect, measured. It is **unverified** here.

## REFERENCES

1. [FFmpeg Filters Documentation — `lut3d`](https://ffmpeg.org/ffmpeg-filters.html#lut3d) — accessed 2026-09-02.
2. [FFmpeg Filters Documentation — `scale`, `in_range` / `out_range`](https://ffmpeg.org/ffmpeg-filters.html#scale-1) — accessed 2026-09-02.

---

## Correction (same day): it is TWO tags, not one

This note found the range half and stopped there. Research note [`05_compilation_and_backends.md`](05_compilation_and_backends.md) measured the full picture, and **range alone is not the fix**. On an untagged full-range source, the max channel error against a correctly-tagged reference is:

| what you fix | max channel error |
|---|---|
| neither | 27 / 255 |
| range only | **19 / 255** |
| matrix only | **20 / 255** |
| both | 2 / 255 |

So `color_range` and `color_space` (the YUV↔RGB matrix) are **two independent unknowns**, and fixing either alone leaves most of the error. My probe compared range assumptions against each other and could not see the matrix term at all, because both sides of my comparison carried the same matrix assumption. That is a real methodological hole: **a comparison between two wrong answers cannot reveal a third variable held constant across both.**

The rule that follows is stronger than the one this note proposed. Not "report that the range is untagged" but: **an unknown colour contract is a refusal**, in exactly the way an unknown licence tier is, escapable only by an explicit recorded `assume=`. Read note 05's `ColorContract` section, not this section, for the design.

What survives from this note unchanged: `format=rgb24` before `lut3d` is a no-op (the framework converts), and `lavfi` sources are bit-reproducible so the suite needs no committed media.
