# The `mixing` → `looks` refactor: the geometry tier and the transitions, moved without moviepy

*2026-09-02. Research note 12. Every measurement below was run on this machine against ffmpeg 8.1 (homebrew, `--enable-gpl --enable-version3`), moviepy 2.2.1, Pillow 11.3.0, opencv-contrib 4.13.0, numpy 2.2.6, CPython 3.12.12. Nothing here is proposed code — `looks/` is untouched.*

## Verdict

The move is safe and the tension dissolves cleanly, but **the kickoff's shopping list is wrong in three specific places, and each correction is load-bearing.** (1) `video_util.py` is not "entire": `get_video_dimensions` is a *probe*, not geometry, and it is the one moved symbol with a real external consumer — `paces` calls `mixing.get_video_dimensions` at three sites behind an explicit `mixing>=0.0.39` floor whose comment names the function. It stays. (2) What *is* geometry — `resize_to_dimensions`, `normalize_video_dimensions`, `thumbnail._cover_resize` — extracts to about 90 lines of stdlib arithmetic that I verified reproduces `mixing.resize_to_dimensions` **pixel-for-pixel across 60 source/target/method combinations** through a moviepy adapter, and reaches the identical output dimensions through an ffmpeg `scale,crop,pad` chain across 80 combinations including a genuinely odd 641×481 source. So the same `Placement` really does compile to both backends, measured, not argued. (3) The six transitions are not six things: under the rule "a look says what the pixels look like, never which pixels exist", **only two of them are effects at all** — and I measured that one of those two (`crossfade_transition`) and one of the four EDL edits (`overlap_blend`) render a **hard cut** through `mixing.concatenate_videos`, because moviepy 2.x's `concatenate_videoclips` defaults to `method="chain", padding=0` and never composites the crossfade masks those functions set. Moving them as-is would move a bug. `looks` should own one parameterised `Transition` over ffmpeg `xfade`'s 58 named kinds (`fade` and `fadeblack` both verified to blend correctly), `mixing` should gain one `looks` dependency and one moviepy adapter that *refuses* what moviepy cannot express, and four of the six names should simply be deleted. Cost of the whole thing: `mixing` gains exactly one new dependency edge (`looks`, zero-dep), `paces` is untouched, and no other package in the tree imports any moved symbol.

---

## 1. Call-site census

`rg` across the whole projects tree (`/Users/thorwhalen/Dropbox/py/proj`), excluding `__pycache__`. "Docs" means a markdown mention with no import; "memory" means a `_priv_claude_sync` transcript archive, which is not code and does not constrain anything.

| Symbol | Defined in | Importers **outside** `mixing` | Importers **inside** `mixing` | Docs / memory mentions | Verdict |
|---|---|---|---|---|---|
| `SOCIAL_SIZES` | `video_util.py` | **none** | `video/__init__.py` (re-export), `tests/test_guard_video_util.py` | `mixing/README.md`, `looks/KICKOFF.md` | free to move |
| `get_video_dimensions` | `video_util.py` | **`paces`** — `paces/derivation.py:694`, `:889`, `:923`; `paces/tests/test_vertical_slice.py:105`, `:150`; version floor in `paces/pyproject.toml:60` names it | `video/__init__.py`, `mixing/__init__.py` (lazy facade), `tests/test_gif_and_crop_box.py`, `tests/test_guard_video_util.py` | `mixing/video/README.md`, two fleet-inventory docs | **DOES NOT MOVE** |
| `resize_to_dimensions` | `video_util.py` | **none** | `video/__init__.py`, `mixing/__init__.py`, `tests/test_guard_video_util.py` | `mixing/video/README.md`, fleet inventories, `KICKOFF.md` | free to move |
| `normalize_video_dimensions` | `video_util.py` | **none** | `video_concat.py:325` (inside `concatenate_videos`), `video/__init__.py`, `mixing/__init__.py`, `tests/test_guard_video_util.py` | fleet inventories, `KICKOFF.md` | free to move; **one internal rewire** |
| `_cover_resize` | `thumbnail.py:118` | **none** | `thumbnail.py` only (private) | — | free to fold into the tier |
| `crossfade_transition` | `video_concat.py:389` | **none** | `video/__init__.py`, `mixing/__init__.py`, `tests/test_video_transitions.py` | fleet inventories, two memory files, `KICKOFF.md` | free to move — but see §5, it is a measured no-op |
| `trim_and_crossfade` | `video_concat.py:414` | **none** | same three | `mixing/video/README.md:405`, fleet inventories, memory | free to move; splits |
| `fade_through_black` | `video_concat.py:439` | **none** | same three | fleet inventories, memory | free to move |
| `slow_motion_blend` | `video_concat.py:461` | **none** | same three | fleet inventories, memory | **DOES NOT MOVE** (retiming) |
| `overlap_blend` | `video_concat.py:500` | **none** | same three | fleet inventories, memory | collapses; see §5 |
| `trim_first_frame_from_subsequent_clips` | `video_concat.py:380` | **none** | `video/__init__.py`, `mixing/__init__.py` | — | **DOES NOT MOVE** (pure EDL) |

**The only external consumer of anything on the list is `paces`, and only of `get_video_dimensions`.** `reelee` touches `mixing.concatenate_videos` (stubbed in `tests/test_e2e_chain.py:120`, `tests/test_assemble_animatic.py:96`, `tests/test_chain.py:255`) and nothing else from either module; `nw`, `an`, `illustration`, `burns`, `walkthru`, `artful`, `muvid` and `braidio` import none of these names. `braidio`'s many `crossfade` hits are its own **audio** crossfades in `braidio/weave.py` and friends, unrelated to `mixing.video`.

### What `paces` actually does, and why it settles `get_video_dimensions`

`paces/derivation.py` calls `mixing.get_video_dimensions(str(path))` in three places to record the width and height of a produced clip into a document's refs, and `paces/pyproject.toml:56-60` pins `mixing>=0.0.39` with the comment *"Floor 0.0.39: `make_gif`, `crop_box=` and path-accepting `get_video_dimensions` ship there."* Two things follow. First, moving the name is a breaking change to a *published* consumer (paces 0.0.5, mixing 0.0.40) that buys nothing, because second — `get_video_dimensions` is not geometry. It computes nothing. It opens a container (`cv2.VideoCapture` for a path, `clip.w`/`clip.h` for a moviepy clip) and reports two integers. It is the *input* to the geometry tier, not part of it. A `looks` that owned it would have to own either cv2 or a moviepy type, and it is allowed neither.

`looks` needs its own answer to "how big is this file", and the answer is `ffprobe` via `looks.environment`, which already exists and already shells out. That is a **second, differently-implemented probe, not a move** — and the two are allowed to coexist because they resolve their binaries differently on purpose (§7).

### The guard test — what must happen to `mixing/tests/test_guard_video_util.py`

It is a 13-function characterization suite written to pin exactly this refactor. It **splits three ways**, and none of the three is "delete":

- **9 functions become arithmetic tests in `looks`, with no moviepy at all.** Everything asserting `(resized.w, resized.h) == (200, 200)`, the empty-list short-circuit, the reference-index/explicit-dimension resolution, and the unknown-method `ValueError` are statements about numbers. In `looks` they become assertions on a `Placement` and need no video file, no `make_color_video` fixture, and no `pytest.importorskip("moviepy")` — which is a strict improvement, because a moviepy-gated module-level `importorskip` removes tests from *collection*, so a missing backend silently shrinks the suite rather than skipping visibly.
- **3 functions stay in `mixing` and get narrower.** `test_resize_to_dimensions_default_method_is_fit` and `test_resize_to_dimensions_stretch_preserves_videofileclip_type` assert moviepy *types* (`CompositeVideoClip` vs `VideoFileClip`), and `test_normalize_uses_first_video_as_default_reference` asserts clip **identity** (`out[0] is v1`, the already-correct-size pass-through). Those are properties of the moviepy adapter, and they belong wherever the adapter lives.
- **1 function moves or dies with `SOCIAL_SIZES`.** `test_social_sizes_presets_and_export` pins the five presets *and* the re-export identity `mv.SOCIAL_SIZES is SOCIAL_SIZES`. See §4.

The three that stay need `make_color_video` (`mixing/conftest.py:81`), which is shared with `test_ambient_bed.py`, `test_guard_thumbnail.py`, `test_guard_video_ops_more.py` and `test_guard_video_class.py`, so the fixture is not going anywhere either way.

---

## 2. The central tension, and the shape that resolves it

`video_util.py` imports `numpy`, `VideoFileClip`, `VideoClip`, `ImageClip`, `CompositeVideoClip` at module top and reaches for `PIL.ImageFilter` and `moviepy.vfx` inside `method="social"`. `looks` declares zero dependencies. A literal move is impossible. But reading the function, the moviepy is thin: 90% of its body is integer arithmetic over four numbers, and the moviepy calls are five lines of application at the end of each branch.

**The separation is: `looks` owns the answer, the consumer owns the doing.**

```
source Size + target Size + FitMode      ← pure inputs
              │
              ▼  looks.geometry (stdlib, ~90 lines)
        Placement(scale, crop, offset)   ← pure data: inspectable, diffable, JSON-able
              │
      ┌───────┴────────┐
      ▼                ▼
  ffmpeg chain    moviepy calls          ← application; each lives with its own dependency
```

`Placement` says the three things a backend needs and nothing more: *scale the source to this size; then take this box out of it; then put it at this offset on the target canvas.* Both crop and offset are `None` when the pass is a no-op, which reproduces `resize_to_dimensions`'s own short-circuits rather than emitting identity filters.

### Verified: the same `Placement` drives both backends

Harness: four sources (320×240, 1920×1080, 1080×1920, and a genuinely odd 641×481 encoded as FFV1/yuv444p because libx264 refuses odd dimensions, see §8) × five targets × four methods, dimensions read back with `ffprobe` and with moviepy's own `.w`/`.h`.

```
80 cases  |  failures: 0
```

The 60 non-`social` cases additionally asserted **pixel identity** between `moviepy_apply(clip, placement(...))` and today's `mixing.resize_to_dimensions(clip, ...)` — `np.array_equal` on the frame at t=0. All 60 passed. So the extracted arithmetic is not merely equivalent-looking; it reproduces the current output bit for bit.

Emitted chains, odd source, so the rounding is exercised:

```
641x481 -> 1920x1080  fit     scale=1439:1080,pad=1920:1080:240:0:color=0x000000        → 1920x1080
641x481 -> 1920x1080  fill    scale=1920:1440,crop=1920:1080:0:180                      → 1920x1080
641x481 -> 1080x1080  fill    scale=1439:1080,crop=1080:1080:179:0                      → 1080x1080
641x481 -> 200x200    fit     scale=200:150,pad=200:200:0:25:color=0x000000             → 200x200
641x481 -> 641x481    fit     scale=641:481                                             → 641x481   (short-circuit)
```

and `social`, which is the one that needs a graph rather than a chain:

```
[0:v]split=2[bgsrc][fgsrc];
[bgsrc]scale=1439:1080,crop=1080:1080:179:0,gblur=sigma=15,colorchannelmixer=rr=0.7:gg=0.7:bb=0.7[bg];
[fgsrc]scale=1080:810[fg];
[bg][fg]overlay=0:135[vout]                                                             → 1080x1080
```

That graph is a direct transcription of what `method="social"` does in moviepy — `fill` for the backdrop, `fit` for the foreground, blur, multiply by 0.7, centre — with two substitutions that matter:

- **`gblur`, never `boxblur`.** `boxblur` is GPL-gated in ffmpeg n8.1; `gblur` is not [1]. `sigma=15` is the nominal match for Pillow 11.3.0's `ImageFilter.GaussianBlur(radius=15)`, whose docstring states the radius *is* the standard deviation — but Pillow implements it as "a sequence of extended box filters, which approximates a Gaussian kernel", so the two are the same *parameterisation*, not the same pixels. **Unverified:** I did not measure whether the two backdrops are perceptually equivalent, and the note should not claim they are.
- **`colorchannelmixer=rr=0.7:gg=0.7:bb=0.7`, never `eq=brightness=…`.** This is the exact analogue of moviepy's `vfx.MultiplyColor([0.7, 0.7, 0.7])` and it is LGPL-safe. `eq` is GPL-gated [1]. Worth flagging as a live instance: `muvid/visualize/canvas.py:224` builds its blurred-cover background with `eq=brightness=…:saturation=…`, so **muvid's background chain is GPL-gated today** and would fail an LGPL ceiling. That is not this refactor's problem to fix, but it is exactly the class of surprise `looks` exists to make loud.

### The one measured divergence: floor versus round

ffmpeg can express `fit` and `fill` **without knowing the source size at all**, using `scale=W:H:force_original_aspect_ratio=decrease` (or `increase`) with expression offsets — the form `muvid` already uses in `muvid/footage/assemble.py:269` and `muvid/visualize/canvas.py:222`. It is tempting, and it is *nearly* identical. Measured:

| case | resolved chain | deferred chain | pixel-identical |
|---|---|---|---|
| 641×481 → 1920×1080 | `scale=1439:1080,pad=…:240:0` | `scale=1920:1080:force_original_aspect_ratio=decrease,pad=…:(ow-iw)/2:(oh-ih)/2` | **yes** |
| 641×481 → 1080×1080 | `scale=1080:810,pad=…:0:135` | same shape | **yes** |
| 320×240 → 200×200 | `scale=200:150,pad=…:0:25` | same shape | **yes** |
| **1920×1080 → 1080×1920** | `scale=1080:607,pad=…:0:656` | same shape | **NO — maxdiff 255** |

The cause, isolated: `1080 / (1920/1080) = 607.5`. mixing/moviepy computes `int(...)` and gets **607**; ffmpeg's `force_original_aspect_ratio` rounds and gets **608** (confirmed by encoding the intermediate alone and probing it: `1080,608`). One pixel row, and a total black/white difference at the seam.

Two consequences, both design decisions rather than trivia. **First, the rounding rule is part of the spec and must be recorded in the `Placement`, not hidden in an emitter.** A pure-data effect spec whose rendered result depends on which backend read it is not a spec. **Second, the deferred form is a legitimate optimisation but it is not the default**, because a `Placement` that does not know its source size cannot be inspected, diffed or reasoned about — which is the entire premise of the package. The right shape is: resolve against the clip (which is also the kickoff's own strongest measured principle, from the per-source flattening scale), emit the resolved chain, and offer the deferred chain explicitly for the case where the source size is genuinely unknown at plan time.

### Does `looks` ship a moviepy backend? No.

The question asks me to show both compilations, and §2 shows them. But **shipping** the moviepy one would mean a `looks[moviepy]` extra, and I verified what that pulls: moviepy 2.2.1's metadata requires `imageio_ffmpeg>=0.2.0` as a **hard** dependency, and the installed `imageio-ffmpeg 0.6.0` ships `binaries/ffmpeg-macos-aarch64-v7.1`, whose `configuration:` line contains `--enable-gpl` and `--enable-libx264`. So `pip install moviepy` redistributes a GPL ffmpeg binary — the same finding the kickoff records for `burns`, and it applies to `mixing` too, which declares `moviepy` and `burns` in its *base* dependencies. A `looks` optional extra that reintroduces that is a violation dressed as an option.

**So the moviepy adapter lives in `mixing`.** It is about 25 lines. `looks` proves the two-backend claim by *shape* — the `Placement` is complete enough that a consumer writes the adapter without asking `looks` anything — not by shipping the adapter. This is the same relationship `burns` has with its `RenderBackend` registry, inverted: there the facade owns the backends; here the spec is small enough that it does not need to.

---

## 3. The proposed `looks` geometry-tier API

```python
"""looks.geometry — where a source frame lands inside a target frame.

Pure arithmetic. No I/O, no media library, no ffmpeg, no numpy. Every function
here is total: give it two sizes and a mode and it answers, with no file open
and nothing decoded. That is what lets the same answer drive an ffmpeg filter
chain, a moviepy composite, a CSS ``object-fit`` preview, or a cost estimate.

The rounding rule is part of the answer, not an implementation detail: mixing
and moviepy truncate, while ffmpeg's ``force_original_aspect_ratio`` rounds,
and the two disagree by one pixel on real inputs (1920x1080 -> 1080x1920 gives
607 against 608). A spec whose rendered result depends on which backend read it
is not a spec, so the rule travels with the placement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Union

FitMode = Literal["stretch", "fit", "fill"]
Rounding = Literal["floor", "round"]

#: ``"floor"`` reproduces ``mixing.resize_to_dimensions`` pixel-for-pixel
#: (verified over 60 source/target/method cases, 2026-09-02). ``"round"``
#: reproduces ffmpeg ``scale=…:force_original_aspect_ratio=…``.
DFLT_ROUNDING: Rounding = "floor"

#: Backdrop defaults, transcribed from ``resize_to_dimensions(method="social")``.
DFLT_BACKDROP_BLUR_SIGMA = 15.0
DFLT_BACKDROP_DIM = 0.7


@dataclass(frozen=True)
class Size:
    """A pixel size. ``aspect`` is width/height, never height/width.

    >>> Size(1920, 1080).aspect
    1.7777777777777777
    """
    width: int
    height: int

    @property
    def aspect(self) -> float:
        return self.width / self.height


@dataclass(frozen=True)
class Box:
    """An axis-aligned pixel box, top-left origin, y down.

    Deliberately NOT ``burns.Rect``: that one is normalised to [0, 1] over a
    source image and interpolates over time. This one is integer pixels in one
    frame's coordinate system. Two different jobs; conflating them is how the
    same crop arithmetic ended up in four places.
    """
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class Solid:
    """Fill the uncovered area with one colour."""
    rgb: tuple[int, int, int] = (0, 0, 0)


@dataclass(frozen=True)
class BlurredCover:
    """Fill the uncovered area with a blurred, dimmed cover-crop of the source.

    This is what ``mixing``'s ``method="social"`` did. It is a *backdrop*
    choice, not a fourth fit mode — which is why it is a separate field: the
    foreground placement is exactly ``fit`` either way.
    """
    blur_sigma: float = DFLT_BACKDROP_BLUR_SIGMA
    dim: float = DFLT_BACKDROP_DIM


Backdrop = Union[Solid, BlurredCover]


@dataclass(frozen=True)
class Placement:
    """Scale the source to ``scale``; take ``crop`` out of it; put it at ``offset``.

    ``crop`` and ``offset`` are ``None`` when that pass is a no-op, so a
    backend emits nothing for it rather than an identity filter.
    """
    source: Size
    target: Size
    scale: Size
    crop: Box | None = None
    offset: tuple[int, int] | None = None
    rounding: Rounding = DFLT_ROUNDING


@dataclass(frozen=True)
class Reframe:
    """The registered effect: a placement plus what fills what it does not cover."""
    placement: Placement
    backdrop: Backdrop = Solid()


def scaled_size(source: Size, target: Size, *, mode: FitMode = "fit",
                rounding: Rounding = DFLT_ROUNDING) -> Size:
    """The aspect-preserving (or, for ``stretch``, not) size before crop/pad.

    >>> scaled_size(Size(1920, 1080), Size(1080, 1920), mode="fit")
    Size(width=1080, height=607)
    >>> scaled_size(Size(1920, 1080), Size(1080, 1920), mode="fit", rounding="round")
    Size(width=1080, height=608)
    >>> scaled_size(Size(1920, 1080), Size(1080, 1920), mode="fill")
    Size(width=3413, height=1920)
    """


def center_box(inner: Size, outer: Size) -> Box:
    """``inner`` centred in ``outer``, with the same floor-halving mixing used.

    >>> center_box(Size(1439, 1080), Size(1920, 1080))
    Box(x=240, y=0, width=1439, height=1080)
    """


def placement(source: Size, target: Size, *, mode: FitMode = "fit",
              rounding: Rounding = DFLT_ROUNDING) -> Placement:
    """The full answer for one clip.

    >>> p = placement(Size(641, 481), Size(1920, 1080), mode="fill")
    >>> p.scale, p.crop, p.offset
    (Size(width=1920, height=1440), Box(x=0, y=180, width=1920, height=1080), None)
    """


def reframe(source: Size, target: Size, *, mode: FitMode = "fit",
            backdrop: Backdrop = Solid(), rounding: Rounding = DFLT_ROUNDING) -> Reframe:
    """``placement`` plus a backdrop — the shape a ``Look`` stores."""


def snap_even(size: Size) -> Size:
    """Round both axes down to even, the H.264/yuv420p requirement.

    Opt-in and never applied silently: the caller chose the target, and an
    encoder constraint is the encoder's business. Offered here only because
    the arithmetic already exists in three other places in this fleet
    (``burns._frame.even``, ``mixing._helpers._validated_crop_box``, and the
    ``scale=W:-2`` idiom in ``mixing.video.gif``).

    >>> snap_even(Size(641, 481))
    Size(width=640, height=480)
    """
```

The ffmpeg emitter is a separate module — its exact home belongs to the compilation/backends note, not this one — but the contract it must satisfy is fixed here:

```python
def reframe_chain(spec: Reframe, *, src: str = "0:v", dst: str = "vout",
                  resolved: bool = True) -> str:
    """The filtergraph fragment. ``resolved=False`` emits the source-size-free
    ``force_original_aspect_ratio`` form, which is one pixel different on some
    inputs and therefore never the default."""


def filters_used(spec: Reframe) -> tuple[str, ...]:
    """Every ffmpeg filter name this spec will emit, for the licence gate.

    ``Solid``  -> ('scale', 'crop', 'pad')
    ``BlurredCover`` -> ('split', 'scale', 'crop', 'gblur', 'colorchannelmixer', 'overlay')

    All eight are LGPL-safe in n8.1, so ``reframe`` clears every tier above
    'no binary at all'. The point is that the *answer is computed*, by feeding
    this into ``looks.environment.needs_gpl(...)``, rather than assumed.
    """
```

`filters_used` is the join between the geometry tier and the licence tier, and it is what stops geometry from being a special case that lives outside the registry. `looks.environment.needs_gpl` already exists.

---

## 4. `SOCIAL_SIZES`: is it `looks`'s business?

Look at what it actually is:

```python
{"youtube": (1920, 1080), "shorts": (1080, 1920), "square": (1080, 1080),
 "story": (1080, 1920), "tiktok": (1080, 1920)}
```

Five names, **three distinct sizes**. `shorts`, `story` and `tiktok` are the same number. So it is not a geometry table; it is a *naming* table that maps platform vocabulary onto three sizes, and platform vocabulary is exactly the thing that drifts (aspect policies, safe areas and duration caps change on the platforms' schedule, not ours).

The argument for excluding it from `looks` entirely: `looks` is a stylization facade with a licence gate, and platform targeting is a different concern with a different decay rate. The argument for including it: something has to own it, and the alternative — every consumer retyping `(1080, 1920)` — is precisely the mechanism that produced **four independent copies of centre-crop-to-aspect arithmetic in this fleet** (`mixing.video_util` `fill`, `mixing.thumbnail._cover_resize`, `burns._frame._cover_crop_box`, and the `scale=W:-2` idiom in `mixing.video.gif`). Re-declaration is not a hypothetical failure mode here; it already happened for the harder half.

**Recommendation: ship it, in `looks.presets`, under three constraints, and do not put it in `looks`'s top-level namespace.**

1. **It is `dict[str, Size]`, not `dict[str, tuple]`** — so it composes with `placement()` and cannot be mistaken for anything else.
2. **It is dated and marked non-authoritative in its own docstring** ("as of 2026-09; these are conveniences, not contracts, and the platforms do not promise them"). A preset with a date is honest; a preset without one is a slow-motion bug.
3. **It is never the default of anything.** No `looks` function may fall back to a preset. Presets are something a caller *names*; a package that silently reaches for `shorts` has acquired a platform opinion.

And the boundary that keeps this from growing: **a preset that is pure geometry is fine; a preset that encodes platform policy is not.** A `Size` is geometry. A max duration, a bitrate ceiling, a codec allowlist or a safe-area inset is policy, and none of it belongs in `looks`.

The consequence for the guard test: `test_social_sizes_presets_and_export` splits. The five-preset assertion moves to `looks` (rewritten against `Size`); the `mv.SOCIAL_SIZES is SOCIAL_SIZES` re-export-identity half is deleted, because that re-export is exactly what a deprecation-free move removes.

---

## 5. The transitions

### Does a transition belong in `looks` at all?

The kickoff forbids "cut/EDL decisions": *"an `Effect.at` says where a look applies, never where a cut is."* A transition is temporal and takes two clips, so it looks like a violation. It is not, and the rule that separates them is sharp enough to be a test:

> **A `looks` effect answers what the pixels look like, never which pixels exist.** A transition says what the frames *inside an overlap you already decided on* look like. Remove the transition and you must still have the same cuts, just hard ones. **If removing it changes the edit — the total duration, which frames survive, where a clip starts — it is an EDL edit, not a look, and it does not move.**

Two corollaries that keep this honest in code:

- **A `Transition` never stores an absolute time.** It carries `kind` and `duration` (and, if wanted, an alignment: centred on the cut, or beginning at it). ffmpeg's `xfade` wants `offset`, a timeline coordinate — so the *emitter* derives it from the caller-supplied clip durations. The decision stays with the caller; only the arithmetic is ours.
- **A `Transition` presupposes the geometry tier**, and ffmpeg enforces this rather than tolerating it. Measured: `xfade` on mismatched sizes fails with *"First input link main parameters (size 320x240) do not match the corresponding second input link xfade parameters (size 1920x1080)"*, and on mismatched frame rates with *"First input link main timebase (1/30) do not match … (1/20)"*. So a `Transition` compiler must **refuse** at plan time when the two clips have not been normalised, rather than emit a graph that dies mid-encode. That is the same refusal discipline as the licence tier, applied to a different precondition.

### The measured problem: two of the six do not do what they say

Before deciding what moves, I ran them. Two solid clips (pure red 1.0 s, pure green 1.0 s, 20 fps, 64×64) through `mixing.concatenate_videos(paths, transform_clips=…, normalize_dimensions=False)`, sampling the mean RGB of every output frame:

| function | output duration | mean RGB at t=0.95 → 1.00 → 1.05 | what it actually did |
|---|---|---|---|
| `crossfade_transition(duration=0.4)` | 2.000 s | (252,0,0) → (0,254,0) → (0,254,0) | **hard cut. no blend at all.** |
| `fade_through_black(duration=0.4)` | 2.000 s | (30,0,0) → (0,0,0) → (0,30,0) | correct: dips to black and rises |
| `overlap_blend(overlap=0.4)` | 1.600 s | (251,0,0) → (0,252,0) → (0,252,0) | **trimmed 0.4 s off clip B, then hard cut** |
| `trim_and_crossfade(duration=0.4)` | 1.950 s | (252,0,0) → (0,254,0) → (0,254,0) | trimmed one frame (0.05 s), then hard cut |
| `slow_motion_blend(ramp=0.4)` | 2.800 s | red throughout | speed ramp; no blend, and **+0.8 s of runtime** |

Diagnosis, confirmed: `moviepy.concatenate_videoclips` in 2.x has signature `(clips, method='chain', transition=None, bg_color=None, is_mask=False, padding=0)`. `vfx.CrossFadeIn`/`CrossFadeOut` work by setting `clip.mask`; `method="chain"` plays clips end to end without compositing, so the masks are never consulted, and `padding=0` means there is no overlap for them to be consulted *over*. Feeding the identical clips to `concatenate_videoclips(..., method="compose", padding=-0.4)` produces a real blend — (19,235,0) at t=0.90 instead of a pure colour — which isolates the cause to the concatenation call, not to the transition functions.

`mixing.concatenate_videos` passes `**concat_kwargs` straight through, so a caller *can* supply `method="compose", padding=-0.4`. Nothing in the API, the docstrings or `mixing/video/README.md:405-410` says they must, and `tests/test_video_transitions.py` only asserts that a file gets written, so the defect has been green the whole time. (That test was written to catch a *different* real bug — `with_speed` → `with_speed_scaled` in `slow_motion_blend` — and its docstring says so.)

**This is why "move the six" is the wrong instruction.** Moving `crossfade_transition` and `overlap_blend` as they are would carry a name that promises a blend and delivers a cut into a package whose whole premise is that a spec tells you what you are getting.

### Mapping onto ffmpeg `xfade`

`ffmpeg -h filter=xfade` on 8.1 reports `transition <int> … (from -1 to 57)` — **58 named transitions plus `custom`** (an `expr`-driven escape hatch), 59 options in all:

```
custom(-1) fade wipeleft wiperight wipeup wipedown slideleft slideright slideup slidedown
circlecrop rectcrop distance fadeblack fadewhite radial smoothleft smoothright smoothup
smoothdown circleopen circleclose vertopen vertclose horzopen horzclose dissolve pixelize
diagtl diagtr diagbl diagbr hlslice hrslice vuslice vdslice hblur fadegrays wipetl wipetr
wipebl wipebr squeezeh squeezev zoomin fadefast fadeslow hlwind hrwind vuwind vdwind
coverleft coverright coverup coverdown revealleft revealright revealup revealdown
```

`xfade` is **not** in the GPL gate list [1], so the whole vocabulary is LGPL-safe. Its remaining options are `duration` (default 1) and `offset` (default 0, relative to the first input's start). Verified behaviour on the same red/green pair, `duration=0.4:offset=0.6`, decoded to raw RGB and averaged per frame:

```
xfade=fade        duration 1.600s   t=0.65 (222,32,0)  0.80 (127,128,0)  0.95 (31,224,0)   ← linear cross-dissolve
xfade=fadeblack   duration 1.600s   t=0.65 (54,0,0)    0.70 (0,0,0)      0.85 (0,132,0)    ← dips to black, as mixing's does
xfade=dissolve    duration 1.600s   t=0.65 (220,33,0)  0.80 (124,130,0)  0.95 (30,224,0)   ← noise-dithered dissolve
```

Output duration is `d1 + d2 − transition_duration` (1.0 + 1.0 − 0.4 = 1.6), which is the arithmetic the emitter owes the caller.

### The six, decided

| mixing function | Passes the "same cuts, just hard" test? | ffmpeg equivalent | Verdict |
|---|---|---|---|
| `crossfade_transition` | **yes** — pure pixel blend over an overlap the caller chose | `xfade=transition=fade` (verified) | **moves**, as one value of the parameterised `Transition`. Deleted from `mixing`: moving a measured no-op is not a migration, it is propagation. |
| `fade_through_black` | **yes** | `xfade=transition=fadeblack` (verified). For a *hold* on black rather than a dip, two single-input `fade` filters plus `tpad`; `fade` is LGPL-safe. | **moves**, same `Transition`. |
| `overlap_blend` | **no** — it trims `overlap` seconds off clip B, which changes which frames exist | none needed | **collapses.** Strip the EDL half and what remains is `crossfade_transition`, i.e. `xfade`'s `offset`. Not a separate effect. Deleted. |
| `trim_and_crossfade` | **no** — trims one frame off clip B | none for the trim | **splits.** The fade half is already covered; the trim half is `trim_first_frame_from_subsequent_clips`, which already exists. The composite is deleted. |
| `slow_motion_blend` | **no** — retimes, measurably (2.0 s → 2.8 s), and its own docstring admits it | `setpts` is a *timeline* operation, not a look | **stays in `mixing`.** |
| `trim_first_frame_from_subsequent_clips` | **no** — pure EDL, and honestly named | — | **stays in `mixing`.** |

So: **`looks` gains one `Transition` type covering 58 kinds; `mixing` keeps two of the six names and deletes four.**

### What has no ffmpeg equivalent, and why

- **The retimings.** `slow_motion_blend` needs `setpts=PTS/0.5` on sub-ranges plus a re-concat, which is a *timeline rewrite*. ffmpeg can do it; `xfade` cannot, and neither can a two-input pixel effect, because the operation is not about pixels.
- **The frame trims.** `trim_and_crossfade` and `overlap_blend`'s trims are `-ss`/`trim` on an input — an EDL edit expressed as a filter. Not absent from ffmpeg; absent from *this vocabulary*.
- **moviepy cannot express most of `xfade`.** `vfx` has `CrossFadeIn`/`CrossFadeOut`/`FadeIn`/`FadeOut`, so a moviepy adapter can serve `fade` and `fadeblack` and nothing else out of 58. That asymmetry must be a **refusal**, not a silent substitution — the same rule as the licence tier, for the same reason.

---

## 6. Migration order and the exact edits

Six steps. Steps 1–2 land in `looks` alone and change nothing downstream; step 3 is the only one that touches a published consumer's behaviour.

### Step 1 — `looks`: land the geometry tier (no consumer changes)

- **New** `looks/geometry.py` — §3 verbatim. Stdlib only. Module docstring (D100 is on). Doctests on `scaled_size`, `center_box`, `placement`, `snap_even`, which is where the floor-versus-round rule becomes executable documentation.
- **New** `looks/presets.py` — `SOCIAL_SIZES: dict[str, Size]`, dated, non-authoritative, defaulted by nothing (§4).
- **Extend** the ffmpeg emitter module with `reframe_chain` and `filters_used`, wired into `looks.environment.needs_gpl`.
- **New** `looks/tests/test_geometry.py` — the 9 arithmetic tests ported from `mixing/tests/test_guard_video_util.py`, plus one that pins the 607/608 divergence in both directions, because that is the number a future contributor will "fix".
- Publish. `mixing` cannot depend on `looks` until `looks` is on PyPI.

### Step 2 — `looks`: land the transition tier

- **New** `looks/transitions.py` — a frozen `Transition(kind, duration, alignment)` with `kind` validated against the 58 names, **no absolute time stored**, and an emitter that derives `xfade`'s `offset` from caller-supplied clip durations and **refuses** mismatched size or frame rate at plan time (the two errors measured in §5).
- The 58 names are data, not a hand-typed literal: parse them out of `ffmpeg -h filter=xfade` the way `looks.environment.parse_filters` already parses `-filters`, and fall back to a committed snapshot when ffmpeg is absent. A hand-typed list of 58 strings is a future divergence.
- Publish.

### Step 3 — `mixing`: the geometry rewire (the breaking step)

| File | Edit |
|---|---|
| `pyproject.toml` | add `"looks"` to `[project.dependencies]`. This is the **only** new dependency edge in the whole refactor, and it is free: `looks` declares nothing. |
| `mixing/video/video_util.py` | **delete** `SOCIAL_SIZES`, `resize_to_dimensions`, `normalize_video_dimensions`. **Keep** `get_video_dimensions` — which is the whole file's remaining content, so the honest move is to rename the module to what it now is (`mixing/video/_probe.py`) or fold the function into `mixing/video/_helpers.py`, which already holds `_validated_crop_box`. |
| `mixing/video/_reframe.py` | **new**, ~25 lines: `apply_placement(clip, placement, *, backdrop)` — the moviepy application from §2, and `normalize_clips(clips, …)` — the `normalize_video_dimensions` loop, now computing `looks.placement(...)` per clip and applying it. The identity pass-through for already-correct-size clips is preserved (three of the kept guard tests assert it). |
| `mixing/video/video_concat.py:325-334` | the local `from mixing.video.video_util import normalize_video_dimensions` becomes `from mixing.video._reframe import normalize_clips`. Keep it a *local* import — that is what keeps `import mixing.video` from paying for moviepy. |
| `mixing/video/thumbnail.py:118` | `_cover_resize` becomes a `looks.placement(..., mode="fill")` plus the same two PIL calls. Its own centre-crop arithmetic goes. |
| `mixing/video/__init__.py:37-42` | drop the three names from the `video_util` import block; keep `get_video_dimensions` from its new home. |
| `mixing/__init__.py:66-69, 148-151` | drop `resize_to_dimensions` and `normalize_video_dimensions` from `_LAZY` and from the `TYPE_CHECKING` block. `get_video_dimensions` stays in both — **this is what keeps `paces` working untouched.** |
| `mixing/tests/test_guard_video_util.py` | 9 tests deleted (they live in `looks` now), 3 rewritten against `_reframe.apply_placement`, 1 (`SOCIAL_SIZES`) deleted. Rename the file to match what it now guards. |
| `mixing/README.md:124` | drop `SOCIAL_SIZES` from the `mixing.video` row. |
| `mixing/video/README.md:378-395` | rewrite the "Dimension Normalization" section: geometry comes from `looks`, application from `mixing`. |

**`paces` requires no change and no version-floor bump.** That is the single best argument for keeping `get_video_dimensions`, and it is worth writing into the PR description so nobody "finishes the job" later.

### Step 4 — `mixing`: the transition rewire

- **Delete** `crossfade_transition`, `trim_and_crossfade`, `overlap_blend` from `video_concat.py`, and their entries in `mixing/video/__init__.py` and `mixing/__init__.py` (`_LAZY` and `TYPE_CHECKING`).
- **Keep** `slow_motion_blend` and `trim_first_frame_from_subsequent_clips` exactly as they are. They are EDL/retiming helpers and they are honestly named.
- **New** `mixing/video/_reframe.py` (same module, or a sibling): `apply_transition(clips, transition)`, consuming a `looks.Transition`, implementing `fade` and `fadeblack` via `concatenate_videoclips(..., method="compose", padding=-duration)` — **the fix for the measured no-op** — and raising a `ValueError` naming the kind and the ffmpeg path for the other 56.
- `mixing/tests/test_video_transitions.py` (2 functions, one parametrized over 5 names) becomes a parametrization over the 2 kinds moviepy can serve, plus **a new test asserting the blend actually happens** — sample the mean RGB at the midpoint and assert it is neither pure red nor pure green. That assertion is what the old suite lacked, which is why the bug lived.
- `mixing/video/README.md:405-410` updates.

### Step 5 — the fallback, if step 4 is judged too aggressive

Deleting the transition names leaves `concatenate_videos` — a real consumer, stubbed in three `reelee` tests — with no in-package transition story. The smaller move is to keep `fade_through_black` (the only one measured to work) in `mixing` and delete only the three broken/EDL-tangled names. It is defensible; it costs one duplicated vocabulary entry. It should be a deliberate choice recorded in the PR, not a drift.

### Step 6 — the consolidation this opens, and does not do

With `looks` on PyPI at zero dependencies, `burns` (which depends on moviepy, numpy and Pillow) *could* depend on `looks` and delete `burns/_frame.py`'s `_cover_crop_box` and `even`, retiring the third and fourth copies of this arithmetic. **Out of scope here** — `burns` is a published package with its own golden vectors and a documented cross-language crop contract, and folding it in is its own change with its own review. Flagging it so the duplication is a known debt rather than a rediscovery.

---

## 7. What must not move, and why

| Stays in `mixing` | Why |
|---|---|
| `get_video_dimensions` | It is a **probe**, not geometry — it computes nothing. It needs cv2 (for paths) or a moviepy type (for clips), and `looks` may have neither. And it has the refactor's only real external consumer (`paces`, three call sites, plus a version floor whose comment names it). `looks` gets its own `ffprobe`-based probe; two probes, deliberately, because they resolve their binaries differently — see the next row. |
| `mixing.util.ffmpeg_exe` | Its documented resolution order **prefers** the pip-bundled `imageio-ffmpeg` binary, which I verified is built `--enable-gpl --enable-libx264` (imageio-ffmpeg 0.6.0, `ffmpeg-macos-aarch64-v7.1`). That is a reasonable trade for `mixing`, which already redistributes it via moviepy. It is the exact opposite of `looks`'s policy, where unknown provenance is a refusal. `looks.environment.probe()` must never call this. |
| `concatenate_videos`, `ensure_videoclip_iterable`, `_ensure_video_clip`, `_iter_video_files` | Execution and muxing. The kickoff's first "keep out" rule. |
| `verify_frame_continuity`, `_save_frame_comparison` | A *cut-quality* diagnostic (does A's last frame match B's first?) that renders a labelled PIL comparison sheet. Measurement plus rendering, about the EDL, needing numpy and Pillow. Three reasons, any one sufficient. |
| `slow_motion_blend`, `trim_first_frame_from_subsequent_clips` | Fail the "same cuts, just hard" test. Retiming and EDL. |
| `make_thumbnail`, `_overlay_text`, `_load_font`, `_wrap` | Pillow rendering with system-font probing. Only `_cover_resize`'s four lines of arithmetic are replaced by a `Placement`. |
| `make_gif` | A two-pass `palettegen`/`paletteuse` encode. Execution, and it owns a real invariant (the zero-byte-palette backstop) won the hard way. |
| Anything named `render` | The kickoff's own warning. A convenience `looks.render(clip, look)` will get used and will rebuild one big `-filter_complex`, against which `muvid/footage/assemble.py` holds a bounded-memory invariant won after 30-cut OOM kills. A `Placement` and a `Transition` are *per-clip* and *per-boundary* by construction, which is exactly the shape that keeps a per-clip encode possible. |

| Stays where it is, elsewhere | Why |
|---|---|
| `burns.Rect`, `burns.BurnsPath` | Normalised to [0, 1] and time-varying; `looks.Box` is integer pixels in one frame. Different jobs. Merging them would give `looks` a second geometry type, which the kickoff's own open question warns against. The relationship is one-directional and future: `Rect.to_pixels(w, h)` can *feed* a `Placement`. |
| `an`'s `StylePack` | It recolours `an`'s own compiler palette and explicitly refuses to touch source art. `looks` is the opposite — it only ever touches source art. No overlap. |
| `muvid`'s `force_original_aspect_ratio` chains | They are inside an assembler that owns memory bounds and a frame-exactness invariant (`tpad=stop=-1:stop_mode=clone`). Their geometry could later be expressed as a `Placement`; their surroundings must not move. Note separately that `muvid/visualize/canvas.py:224` uses `eq`, a **GPL-gated** filter [1] — a live finding, not this refactor's job. |

---

## 8. Verification log

Everything below was executed in this session. Sources are lavfi `testsrc2` renders except `src_odd.mkv`, which is a 1282×962 `testsrc2` scaled to 641×481 and stored as FFV1/yuv444p — necessary because `testsrc2=size=641x481` silently reports 640×480 (the generator draws in even blocks), which is itself the kind of thing that makes a naive harness pass for the wrong reason. My first run of this harness had exactly that defect and produced three false mismatches.

**Geometry, both backends, three-way against today's behaviour.** 4 sources × 5 targets × 4 methods; ffmpeg dimensions read with `ffprobe`, moviepy dimensions read from `.w`/`.h`, and the 60 non-`social` cases additionally compared pixel-for-pixel against `mixing.resize_to_dimensions` with `np.array_equal`:

```
80 cases  |  failures: 0
```

**Resolved versus deferred ffmpeg form.** Identical pixels in 3 of 4 probes; the fourth diverges by one pixel row:

```
src_odd.mkv       -> 1920x1080: identical=True  maxdiff=0
src_odd.mkv       -> 1080x1080: identical=True  maxdiff=0
src_1920x1080.mp4 -> 1080x1920: identical=False maxdiff=255
src_320x240.mp4   ->  200x200 : identical=True  maxdiff=0

force_original_aspect_ratio=decrease intermediate: 1080,608
floor(1080/(1920/1080)) = 607   round = 608
```

**H.264's even-dimension constraint, and the `-2` idiom.**

```
$ ffmpeg -i src_odd.mkv -vf "scale=641:481" -c:v libx264 -pix_fmt yuv420p …
[libx264] width not divisible by 2 (641x481)
[vost#0:0/libx264] Error while opening encoder …

$ ffmpeg -i src_odd.mkv -vf "scale=460:-2" -c:v libx264 -pix_fmt yuv420p …
460,346
```

Odd *intermediates* inside a filter graph are fine — `scale=1439:1080` and `scale=1080:607` both encode once padded — and odd `overlay` offsets (`overlay=179:135`, `overlay=0:135`) produce no warning under yuv420p. **Only the encoded frame must be even**, which is why `snap_even` is opt-in and belongs to whoever encodes.

**What `mixing`'s transitions actually render** — mean RGB per frame, red→green, 20 fps, through `concatenate_videos`:

```
crossfade_transition(0.4)  duration=2.000   t=0.95 (252,0,0)   t=1.00 (0,254,0)    ← hard cut
fade_through_black(0.4)    duration=2.000   t=0.95 (30,0,0)    t=1.00 (0,0,0)      ← correct
overlap_blend(0.4)         duration=1.600   t=0.95 (251,0,0)   t=1.00 (0,252,0)    ← trim + hard cut
trim_and_crossfade(0.4)    duration=1.950   t=0.95 (252,0,0)   t=1.00 (0,254,0)    ← 1-frame trim + hard cut
slow_motion_blend(0.4)     duration=2.800   red throughout                          ← retiming, +0.8 s
```

**The cause, isolated.** Same clips, same transition function, different concatenation call:

```
moviepy 2.1.2 (module) / 2.2.1 (dist metadata)
concatenate_videoclips sig: (clips, method='chain', transition=None, bg_color=None, is_mask=False, padding=0)

crossfade_transition + chain (what mixing does):      t=0.90 (252,0,0)  t=0.95 (252,0,0)   ← no blend
crossfade_transition + compose + padding=-0.4:        t=0.90 (19,235,0) t=0.95 (4,250,0)   ← blend
```

*(Anchoring note: the installed moviepy reports `moviepy.__version__ == "2.1.2"` while its dist-info says `2.2.1` — `site-packages/moviepy/version.py` was not bumped in the 2.2.1 release. Anchor to the distribution metadata; `__version__` is wrong here.)*

**`xfade` in ffmpeg 8.1** — 59 options (58 named + `custom`), verified by counting the option rows in `ffmpeg -h filter=xfade`. Three run and sampled:

```
xfade=fade       1.600s   t=0.65 (222,32,0)  0.80 (127,128,0)  0.95 (31,224,0)
xfade=fadeblack  1.600s   t=0.65 (54,0,0)    0.70 (0,0,0)      0.85 (0,132,0)
xfade=dissolve   1.600s   t=0.65 (220,33,0)  0.80 (124,130,0)  0.95 (30,224,0)
```

**`xfade`'s preconditions, which the geometry tier must satisfy:**

```
[Parsed_xfade_0] First input link main parameters (size 320x240) do not match the
                 corresponding second input link xfade parameters (size 1920x1080)
[Parsed_xfade_0] First input link main timebase (1/30) do not match the
                 corresponding second input link xfade timebase (1/20)
```

**The local binary tells you nothing about licences.** Both GPL-gated filters run silently on this build, with no warning of any kind:

```
$ ffmpeg -i t0.mp4 -vf "boxblur=5"        -frames:v 1 -f null -   → accepted
$ ffmpeg -i t0.mp4 -vf "eq=contrast=1.2"  -frames:v 1 -f null -   → accepted
$ ffmpeg -L | head -3
ffmpeg is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 3 of the License, or …
```

**moviepy's transitive GPL binary:**

```
moviepy 2.2.1 requires: ['decorator…', 'imageio…', 'imageio_ffmpeg>=0.2.0', 'numpy…', …]
imageio-ffmpeg 0.6.0 → …/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1
  --enable-gpl present: True     libx264 present: True
```

### Explicitly unverified

- **Whether ffmpeg `gblur=sigma=15` and Pillow `GaussianBlur(radius=15)` produce perceptually equivalent backdrops.** Pillow 11.3.0's docstring confirms the radius *is* the standard deviation, so the parameterisation matches; but Pillow implements it as a stack of extended box filters approximating a Gaussian, so the pixels will differ. I measured nothing here. If the `social` backdrop must match today's output, measure it before shipping.
- **Behaviour on Windows and Linux.** Everything above ran on macOS/arm64. The arithmetic is stdlib and platform-independent; the ffmpeg behaviour should be too, but "should be" is not a measurement. `mixing` and `looks` both run `test_on_windows = true`.
- **Whether any *unpublished* or out-of-tree consumer imports a moved symbol.** The census covers `/Users/thorwhalen/Dropbox/py/proj`. A notebook, a scratch script or a server-side checkout outside that tree would not appear.
- **The exact behaviour of `xfade`'s remaining 55 transitions.** I ran three. The other 55 are reported by the binary; I did not exercise them.

---

## REFERENCES

1. [FFmpeg licence gates extracted from `configure` at tag `n8.1`](00_ffmpeg_licence_gates_evidence.md) — sibling research note in this folder, with [`ffmpeg_n81_licence_gates.json`](ffmpeg_n81_licence_gates.json) as its machine-readable companion. The source is [FFmpeg `configure`, tag `n8.1`](https://raw.githubusercontent.com/FFmpeg/FFmpeg/n8.1/configure).
2. [FFmpeg Filters Documentation — `xfade`](https://ffmpeg.org/ffmpeg-filters.html#xfade) — the transition vocabulary, `duration` and `offset` semantics. Cross-checked against `ffmpeg -h filter=xfade` on the local 8.1 build.
3. [FFmpeg Filters Documentation — `scale`](https://ffmpeg.org/ffmpeg-filters.html#scale-1) — `force_original_aspect_ratio`, `force_divisible_by`, and the `-2` sizing idiom.
4. [FFmpeg License and Legal Considerations](https://ffmpeg.org/legal.html) — why `--enable-gpl` makes the resulting binary GPL, which is what makes `ffmpeg -L` the only honest self-report.
5. `/Users/thorwhalen/Dropbox/py/proj/t/mixing/mixing/video/video_util.py` — the geometry tier as it stands; `SOCIAL_SIZES` at :16, `get_video_dimensions` at :25, `resize_to_dimensions` at :50, `normalize_video_dimensions` at :219.
6. `/Users/thorwhalen/Dropbox/py/proj/t/mixing/mixing/video/video_concat.py` — the six transitions at :380, :389, :414, :439, :461, :500; the `normalize_video_dimensions` call site at :325.
7. `/Users/thorwhalen/Dropbox/py/proj/t/mixing/mixing/video/thumbnail.py` — `_cover_resize` at :118, the fourth copy of centre-crop-to-aspect.
8. `/Users/thorwhalen/Dropbox/py/proj/t/mixing/mixing/tests/test_guard_video_util.py` — the 13-function characterization suite written for this refactor.
9. `/Users/thorwhalen/Dropbox/py/proj/t/mixing/mixing/tests/test_video_transitions.py` — the 2-function transition suite, which asserts a file is written but never that a blend occurred.
10. `/Users/thorwhalen/Dropbox/py/proj/t/mixing/mixing/util.py` — `ffmpeg_exe` at :26, whose resolution order prefers the pip-bundled GPL binary.
11. `/Users/thorwhalen/Dropbox/py/proj/t/paces/paces/derivation.py` — `mixing.get_video_dimensions` at :694, :889, :923; the floor is declared at `/Users/thorwhalen/Dropbox/py/proj/t/paces/pyproject.toml:56-60`.
12. `/Users/thorwhalen/Dropbox/py/proj/t/muvid/muvid/footage/assemble.py:269` and `/Users/thorwhalen/Dropbox/py/proj/t/muvid/muvid/visualize/canvas.py:222,239` — the source-size-free `force_original_aspect_ratio` form already in the fleet; `canvas.py:224` is the live `eq` (GPL-gated) usage.
13. `/Users/thorwhalen/Dropbox/py/proj/t/burns/burns/_frame.py` — `even` at :32 and `_cover_crop_box` at :68, the third copy of this arithmetic; `/Users/thorwhalen/Dropbox/py/proj/t/burns/burns/rect.py:30` is the normalised `Rect` that `looks.Box` is deliberately not.
14. `/Users/thorwhalen/Dropbox/py/proj/t/looks/looks/environment.py` — `probe`, `parse_licence`, `parse_filters`, `needs_gpl`; already the right join point for `filters_used`.
15. [moviepy on PyPI](https://pypi.org/project/moviepy/) — installed 2.2.1 (dist metadata; `moviepy.__version__` reports 2.1.2), hard-requires `imageio_ffmpeg>=0.2.0`.
16. [imageio-ffmpeg on PyPI](https://pypi.org/project/imageio-ffmpeg/) — installed 0.6.0, ships `ffmpeg-macos-aarch64-v7.1` built `--enable-gpl --enable-libx264`.
17. [Pillow `ImageFilter.GaussianBlur`](https://pillow.readthedocs.io/en/stable/reference/ImageFilter.html#PIL.ImageFilter.GaussianBlur) — installed 11.3.0; radius is the standard deviation, implemented as extended box filters approximating a Gaussian.
