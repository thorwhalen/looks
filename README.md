# looks

Named video effects that compile to a backend command, each carrying a **licence tier** — so you can demand commercial-safe-only and get a **refusal** rather than a surprise.

```python
from looks.environment import needs_gpl

needs_gpl(["scale", "eq", "lut3d"])  # -> ('eq',)
```

`eq` is the obvious brightness/contrast/gamma filter. It exists **only in a GPL build of ffmpeg**. Nothing in the ffmpeg CLI will tell you, because the binary on your machine runs it fine — and the LGPL-clean way to do the same thing (`curves`, `colorlevels`, `exposure`) is one substitution away. That gap is what this package is for.

`pip install looks` — **zero dependencies.** ffmpeg is shelled out to, never linked.

## What it does today

```python
from looks.geometry import Size, placement, ffmpeg_chain, social_size

# a vertical phone clip, filled into a 16:9 frame
p = placement(Size(480, 850), social_size("youtube"), mode="fill")
ffmpeg_chain(p)
# 'scale=1920:3400,crop=1920:1080:0:1160'
```

```python
from looks.lut import Ramp, gradient_map, write_cube

# a look, as a colour ramp indexed by lightness
look = gradient_map(
    Ramp.from_hex(
        [
            (8.2, "#2E0C18"),  # the shadow floor — NOT black
            (46.8, "#D5254A"),
            (100.0, "#FEF0DC"),  # the highlight — NOT white
        ]
    )
)
write_cube(look, "look.cube")  # ffmpeg: -vf lut3d=look.cube
```

```python
from looks.measure import measure, dispersion

# how far apart do three sources look, after the effect?
stats = [measure(clip, source_id=name, vf="lut3d=look.cube") for name, clip in sources]
dispersion(stats)  # 2.98 -> the spread you are trying to close
```

```python
# a Look whose flattening scale must be MEASURED per clip, not guessed
look = looks.Look(
    name="que_calor",
    target=looks.Target.SET_RELATIVE,  # the target is the set's own spread
    steps=(looks.Effect(name="flatten", params={"scale": looks.Ref("flatten_scale")}),),
)
looks.resolve(look, {"flatten_scale": 0.5})  # -> refused: one clip cannot answer it
looks.resolve_across(look, probes)  # -> one resolved Look per clip
```

## Why it exists

PyPI has a dozen ffmpeg wrappers. Surveyed, **none of them carries a named-effect registry, and none carries any licence awareness at all** — not a field, not a check, not a warning. Meanwhile the licence facts are genuinely surprising:

- **`eq`, `boxblur`, `cropdetect`, `hqdn3d` and 34 others exist only in a GPL ffmpeg.** Only three of the 38 are colour operations, and each has an LGPL substitute in the same binary — so nothing you want is *unreachable*. But the gated ones are exactly the obvious first reach, and `eq` is the first thing anyone types.
- **`libx264` and `libx265` are FFmpeg's only software H.264/HEVC encoders**, both GPL. So an LGPL-tier *deliverable* is AV1, VP9, ProRes/FFV1 or hardware. Never x264. The wall is in the encoders, not the filters.
- **`geq` is not GPL** and has not been since FFmpeg 4.3, contrary to widespread belief.
- **`av`, `imageio-ffmpeg` and `opencv-python`'s macOS wheels all declare permissive licences while shipping GPL binaries.** For `av`, three layers disagree: the metadata says BSD-3, FFmpeg's own `avutil_license()` says LGPLv3, and `otool -L` shows GPL `libx264` and `libx265` actually linked. A licence check that trusts a declared field is not a check.

## Design

**Pure-data specs, separable from execution.** A `Look` is inspectable, persistable, diffable and *costable* before anything runs — the shape `falaw.Plan` has, except the cost unit is **CPU-seconds, not dollars**.

**Unknown is a refusal, never a warning.** That applies to a licence tier, to an ffmpeg build whose `-L` output matches nothing known, and to a clip whose colour range is untagged.

**Two things are deliberately out of scope**, and one of them is enforced rather than documented:

> **Every ffmpeg process `looks` starts ends in `-f null -`.**

That admits every measurement, probe and diagnostic; it excludes every render, encode, mux and concat, and therefore `looks.render()` — which cannot be written without violating it. A convenience render function *will* get used and *will* rebuild one whole-timeline `-filter_complex`, which is a measured 2.3 GB regression on the box this ecosystem deploys to. `looks` emits the chain; you run it. The other exclusion is cut/EDL decisions: an effect says *where a look applies*, never where a cut is.

**Parameters resolve against the clip they apply to.** This is the package's most expensive lesson, and it is not a nicety. Building the first real look, one global flattening scale made the *softest* of three sources softer still — 46 → 38, where the other two went 35 → 72 and 117 → 114 — so it became the softest thing on screen, and it was the one the viewer complained about. The rule that follows is counter-intuitive: **normalise the OUTPUT across sources, not the input.** Don't sharpen the soft one; measure post-effect and pick parameters that land the clips in family. Full resolution was available and sharper, and was deliberately *not* used, because it would have made the softest source the sharpest thing in the edit — a new mismatch rather than a fix.

## Status

Building. Shipped so far:

| module | what it does |
|---|---|
| `looks.spec` | `Effect` / `Look` / `Ref` / `Step` / `LookPlan` — what a stylization *is*, before anything runs |
| `looks.environment` | probe an ffmpeg build's licence and capabilities; FFmpeg's own gate table |
| `looks.licence` | four axes, a ladder that is an explicitly replaceable policy, a 33-row evidence ledger, and refusals that name the alternative |
| `looks.geometry` | fit / fill / stretch, crop, pad, social presets — pure arithmetic, compiles to any backend |
| `looks.lut` | gradient-map `.cube` generation, at zero dependencies |
| `looks.measure` | clip statistics via `ffprobe`, with identity fields that refuse a wrong comparison |
| `looks.frame_dependency` | "can this effect flicker?", decided by four ffmpeg probes |
| `looks._run` | the single process chokepoint, and the invariant guard |

**548 tests.** They compose — `looks/tests/test_integration.py` walks the whole stack through the public surface: probe the environment, check the chain against the default ceiling, place a vertical clip into 16:9, verify the look cannot flicker, measure at source and post-effect, and confirm the two are correctly *incomparable*.

Next: the registry, the compiler, and the effect catalogue — see [looks#2](https://github.com/thorwhalen/looks/issues/2).

The design of record is [`docs/decisions_and_rationale.md`](docs/decisions_and_rationale.md), backed by the research notes in [`docs/research/`](docs/research/) — thirteen investigations, each adversarially reviewed by a second reader who re-ran every command rather than taking it on trust. That review found a **false permission** in the first version of the gate table (five filters are GPL-gated *indirectly*, through `EXTERNAL_LIBRARY_GPL_LIST`, with no `gpl` token on their own line), which is the kind of error this package exists to prevent and is therefore worth reading about.

## A note on what this is not

`looks` is not legal advice, and a licence tier is a **mechanical reading of published metadata and source**, not an opinion about your situation. What it can do is refuse to let a chain reach a filter your declared ceiling forbids, and tell you which substitution gets you the same result. What it cannot do is know what you are shipping, to whom, under what agreement.

## License

MIT
