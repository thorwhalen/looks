# looks — kickoff

*Written 2026-09-02 by the session that built the Que Calor music videos and hit the gap this package fills. Delete this file once `docs/` and `README.md` carry its content.*

## What this is

A **facade over video stylization** — named effects that compile to a backend command, with a per-effect **licence tier** so a caller can demand "commercial-safe only" and get a refusal rather than a surprise.

PyPI has ~8 ffmpeg wrappers. None of them is this. The two missing things:

1. **A registry of named effects carrying a licence tier.** Every existing wrapper assumes you know what you're linking.
2. **Pure-data effect specs, separable from execution** — the `falaw.Plan` shape. A `Look` should be inspectable, persistable, diffable and *costable* before anything runs.

**It is an extraction, not greenfield.** `muvid/visualize/visuals.py` already has ~80% of the shape: a frozen `VisualPlan` (ffmpeg inputs + filter chains + output label), a `register_visual` open-closed registry, and an escape hatch for non-ffmpeg backends that return a rendered path. Generalise that from *audio→video* to *video→video*. Read it before designing anything.

Background: **thorwhalen/muvid#63** is the proposal issue and has a long comment recording a measured design constraint (below). Read both.

## Non-negotiables

- **Zero hard media dependencies.** `pyproject.toml` declares nothing but stdlib; every backend is an optional extra. Specifically **never** depend on `av` (its wheel bundles `libx264`/`libx265` GPL-2.0+ dylibs under BSD-3 metadata) and **never** on `imageio-ffmpeg` (bundles an `--enable-gpl` binary). ffmpeg is *shelled out to*, never linked.
- **The licence tier is a refusal, not a warning**, and it is the default ceiling. `Look.max_tier` defaults to "shells out to a copyleft binary is fine"; a restricted-tier effect **raises** unless explicitly opted into. Same rule the video_gen group states for the falaw licence ledger: unknown is a refusal.
- **Keep two things out** or this becomes a second muvid:
  - **Execution and muxing.** muvid's `assemble.py` owns a bounded-memory invariant won after 30-cut OOM kills. A convenience `looks.render(clip, look)` *will* get used and *will* rebuild one big `-filter_complex`.
  - **Cut/EDL decisions.** An `Effect.at` says *where a look applies*, never *where a cut is*.
- Follow the house style: functional over OOP, dataclasses for data, `Protocol` over ABC, keyword-only past the 3rd argument, no magic numbers, module docstring on every module.

## Validated starting material — a real look, already built

The Que Calor V2 stylizer works and is in `~/Downloads/que_calor/work/style/` (see that folder's `README.md` and `LEDGER.md`). It is the first real customer and should become an example. What it established, all measured:

- **The chain that works:** flatten (`cv2.pyrMeanShiftFiltering`) → 3D LUT (`lut3d`) → posterise. Frame-independent by construction — no temporal state, one fixed LUT — so it **cannot flicker**. Measured frame-to-frame change was 0.89–1.12× the source's own.
- **`pyrMeanShiftFiltering`, never `edgePreservingFilter`.** The latter smooths *across* object boundaries and dissolves figures into the background. Mean-shift clusters in colour *and* position, so boundaries survive. This is the difference between a stylised look and the mushy-edges artefact.
- **A gradient-map LUT is the right vehicle when the target's hue tracks its lightness.** Measure the target before assuming a filter. The reference here had **no black, no white and no outlines** — so the classic "cartoonify" (bilateral + adaptive-threshold black edges) would have been exactly wrong.
- **The flattening scale must be per-source, and this is the subtle one.** The downscale/upscale round trip — not the filter's colour radius — governs retained sharpness (measured post-LUT: ~150 at full res, ~85 at 0.75, ~44 at 0.5; the radius barely moves it). A single global setting made the *softest* source softer still, so it became the mushiest thing on screen. **The right auto-rule normalises the OUTPUT across sources, not the input** — don't "sharpen the soft one"; measure post-effect sharpness per source and pick parameters that land them in family. Full detail in the muvid#63 comment.

That last point is the strongest argument for the design: an `Effect`'s parameters must resolve against *the clip they apply to*, not be fixed at the top of a `Look`.

## Refactor out of `mixing`, in this order

1. `mixing/video/video_util.py` entire — `SOCIAL_SIZES`, `resize_to_dimensions` (stretch/fit/fill/social), `normalize_video_dimensions`, plus the duplicated centre-crop in `thumbnail.py`. This is the geometry tier.
2. The six transitions in `video_concat.py` (`crossfade_transition` et al).

Do this as a *deprecation-free* move — the group's prime directive is clean shape over backward compatibility, and mixing has no external users for these.

---

# How to run this session

## 1. Set up the project with `wads` — do this first

Use the `wads` scaffolding, not a hand-rolled `pyproject.toml`:

```bash
python -c "from wads.populate import populate_pkg_dir; populate_pkg_dir('$PP/t/looks', description='A facade over video stylization: named effects with licence tiers', root_url='https://github.com/thorwhalen')"
```

Read `~/.claude/skills/python-project-structure/SKILL.md` and the `wads-migrate` skill first. The CI is driven entirely by `[tool.wads.ci]` in `pyproject.toml`.

## 2. Claim the name on PyPI immediately, at 0.0.0

**Before writing real code.** `looks` was verified free on 2026-09-02, but a name is only yours once published. Publish a stub at version `0.0.0`, confirm it appears, and only then invest.

```bash
gh repo create thorwhalen/looks --public --source=. --remote=origin
priv git_ops set-repo-secrets thorwhalen/looks   # ← BEFORE the first push, or CI 403s on publish
git add -A && git commit -m "looks: scaffolding" && git push -u origin main
```

**`priv git_ops set-repo-secrets thorwhalen/looks` must run before you push.** A repo without `PYPI_PASSWORD` fails the publish step with a 403 and you discover it after the fact — this has bitten several packages in this fleet.

Then watch it: `gh run watch` / `gh run list -R thorwhalen/looks`. Confirm `pip index versions looks` (or the PyPI JSON API) shows 0.0.0 before continuing.

## 3. Then: as soon as anything works, push and let CI publish

Don't batch. The point of steps 2–3 is to prove the whole path — name, secrets, CI, PyPI — while the package is trivial and a failure costs nothing. A merge to the default branch publishes.

## 4. Research before designing

**Search what already exists first**, with `ir` (the local agentic retrieval substrate — load its `ir-search` skill). Search the local ecosystem *and* your own past sessions: this fleet has a lot of prior art on ffmpeg filter chains, colour handling and registries, and `muvid.visualize` is only the most obvious piece.

Then **trigger your own research** into `docs/`, and use it to plan. Concretely:

- Put every research output in `docs/` as a dated, referenced note. Version-anchor claims about fast-moving dependencies — an unanchored finding about a library is a future bug.
- Fan out agents on the questions that actually branch the design. Good candidates: what the effect-spec type should be (survey `falaw.Plan`, `an`'s `VisualPlan`, `burns.BurnsPath`); what the licence tiers should be and how each backend maps onto them; whether the GLSL/shader path is worth a backend; what the state of neural restyling is *with commercially-usable licences* (note AnimeGANv2 and White-box Cartoonization are both non-commercial — that killed the obvious route here).
- **Give agents the measured facts above** rather than letting them rediscover them. They cost real time to establish.

## 5. Land things

Branch → PR → CI green → squash-merge → back to main. Merging publishes; that's intended.

---

## Open questions for the owner

- **Should `burns` become a `looks` backend, or stay separate?** `burns.BurnsPath.evaluate(t) -> Rect` already *is* a pan/zoom spec, render-agnostic and JSON-serialisable, and `burns/backends.py`'s docstring names an ffmpeg fast-path as its intended second backend. There is a real argument that geometry-over-time belongs in `burns` and only *pixel* effects belong here. Decide before writing a second geometry type.
- **Does `looks` own normalisation as well as stylization?** The Que Calor edit needed both — a measured per-clip continuity grade *and* an extreme look. They compile to the same `vf` insertion point. Treating them as one vocabulary is tempting and probably right, but say so deliberately.
