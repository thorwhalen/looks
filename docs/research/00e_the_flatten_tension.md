# Evidence: the flagship look's flattener, and why its tier is platform-dependent

*2026-09-02, by the orchestrating session. This is a **cross-note synthesis**, not a new measurement: notes 08 and 13 each measured half of it and neither could see the whole, because they were asked different questions.*

## The finding, as note 13 states it

> **`flatten` has no permissive implementation and the LGPL one is not an equivalent**: `cv2.pyrMeanShiftFiltering` sits at `COPYLEFT_SHIPPED` and is therefore *refused by the default ceiling*, so the first look `looks` ships cannot run at its own default.

If that stands unqualified it is the most awkward fact in the programme: the package's flagship example is refused by the package's own default.

## The qualification note 08 supplies

Note 08 and its adversarial review measured the opencv wheels **per platform**, and they are not the same artifact:

| wheel | bundles FFmpeg? | tier |
|---|---|---|
| `macosx_*_arm64` | **yes** — `--enable-gpl --enable-version3 --enable-libx264 --enable-libx265` | copyleft, shipped |
| `macosx_14_0_x86_64` | **no FFmpeg at all** (`FFMPEG: NO`; 4 vendored dylibs, all permissive) | permissive |
| `manylinux` | **no** x264/x265; LGPL-2.1-or-later | weak copyleft, shipped |

So `COPYLEFT_SHIPPED` is the verdict for **one platform's wheel**, not for OpenCV, and not for `pyrMeanShiftFiltering`. **OpenCV the library is Apache-2.0, and the mean-shift function is main-module code that never calls FFmpeg** — the GPL binary is there for `cv2.VideoCapture`/`VideoWriter`, which `looks` does not use.

## What this changes

1. **The flagship look runs at the default ceiling on Linux and on Intel macOS, and is refused on Apple-silicon macOS.** That is a strange sentence, and it is *correct* — which is the whole argument for note 08's conclusion that **a static extras declaration cannot tell the truth about this package and a runtime probe must**. A tier printed in `pyproject.toml` would be wrong on two of three platforms whichever value it took.
2. **The refusal is right, and it is also fixable by the caller.** Someone on Apple silicon can install the headless x86_64 wheel under Rosetta, build OpenCV from source, or accept the tier. The package's job is to tell them which of those they are doing, not to decide.
3. **The `bilateral` alternative is a different effect, not a fallback.** Note 13 measured it reaching comparable flattening (`ncol90` 117–165 against mean-shift's 132) at roughly **half** the retained post-look sharpness (23–36 against 54.9). Sharpness retention is precisely the axis the per-clip correction was about, so silently substituting it would re-create the original defect under a new name. Offer it as a named alternative with its measured cost; never as a fallback.

## The rule this argues for

**A tier is a property of the (effect, provider, resolved environment) triple, never of a package name.** The environment includes which *wheel* is installed, not just which library — and on this evidence the wheel is where the licence actually lives.

Which is the same shape as the ffmpeg finding one layer up: there is not one ffmpeg on a machine, and there is not one opencv on PyPI.

## Status

**Reasoned, not re-measured here.** The per-platform wheel contents come from note 08 and its adversarial review, both of which downloaded and inspected real wheels. The synthesis should carry the qualification; if it cannot be confirmed, the unqualified form in note 13 is the safe one to publish, since it errs toward refusal.
