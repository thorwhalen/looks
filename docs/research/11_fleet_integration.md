# How `looks` reaches the federation: seams, order, and who consumes it first

**Date: 2026-09-02** · research note 11 for `looks` · status: proposal, with two owner questions marked for ratification. Every claim about a version, a filter set, a dependency edge or a call site below was produced by reading source or running a command on this machine on 2026-09-02; anything I could not check is marked **unverified**.

## Verdict

`looks` is a **peer of `burns`, not a peer of `falaw`** — a focused capability the apps and `nw` call directly — and the reason is not taste, it is that the federation already ruled on this question and shipped the ruling: `nw.transforms.cache_key` (nw#54) exists precisely for "a Transform that spends money or CPU **without** going through fal", and `braidio`'s `segment_extraction.ffmpeg` is the reference implementation of that category — a **local-render Transform** whose `plan()` returns a *zero-call* `falaw.Plan` plus a skeleton carrying its own `cache_key`, and whose `execute()` does the local work unless that key already has an artifact [15]. A `looks`-backed stylize step is that shape exactly, so `looks` needs no new mechanism in `nw` and must not become a `falaw` backend: `falaw.Plan` is a consent-to-spend instrument for an irreversible billed call, and a local CPU stage is neither irreversible nor billed. The Transform is therefore hosted by **`muvid` first** (its footage-assembly genre is the only place a per-clip look is wanted today, and `muvid/footage/assemble.py::_render_part` is a single-input `-vf` string that a compiled `Look` splices into unchanged [9]), graduating into `nw` on the rule of three when `reelee` wants it — the same deliberate migration muvid#4 already tracks. `looks` itself hosts **no** Transform, imports **no** federation package, and spawns **no** process. On the two owner questions: **`burns` stays separate and gains a `looks`-backed ffmpeg render backend** — the direction `burns/backends.py` already declares as its intended second backend [6], with `looks` supplying the compiled filter and `burns` running it, because `looks → burns` is *forbidden* (burns declares `moviepy`, which pulls `imageio-ffmpeg`, whose bundled binary I confirmed is built `--enable-gpl`), and the clean dividing line is **authored versus derived geometry**, not "geometry versus pixels"; and **yes, `looks` owns normalisation as well as stylization**, one vocabulary, one tier system, one insertion point, with the API difference being two *resolvers* rather than two Effect types — `resolve(look, probe)` for a target that is external, `resolve_across(look, probes)` for a target that is the set's own distribution, which is the shape the Que Calor measurement demands for stylization too. The single most consequential new finding for the integration is that **this environment contains two different ffmpeg binaries with non-nested filter sets, and `looks` does not get to choose which one runs**: the pip-bundled one (ffmpeg 7.1, 484 filters, has `zscale` and `drawtext`) and the PATH one (ffmpeg 8.1, 481 filters, has neither), so a compiled `Look` is *not* portable across the federation and the capability set must be an argument, never a probe `looks` performs.

---

## 0. Method

Read from source on 2026-09-02, at the paths named in the references. Runtime facts from `ffmpeg -version`, `ffmpeg -filters`, `importlib.metadata`, and `gh issue view`. Fleet edges from `rg` over the projects folder named in the manifest at `$PTH_FILEPATH`.

**Interpreter caution, and it bit me once here too.** A first run of the ffmpeg-binary comparison from `/tmp` failed with `ModuleNotFoundError: No module named 'imageio_ffmpeg'`; the same script run from under `$PP` resolved to `/…/.pyenv/versions/p12/bin/python` (CPython 3.12.12) and worked. Every measured number below is from the second. Note 02 records the same trap [17]; it is real and it is cheap to fall into.

---

## 1. Where `looks` sits

### 1.1 The layering, with `looks` placed

```
                          reelee-web   (the product FE — TS/React)
                                │  HTTP + MCP
              ┌─────────────────┴──────────────────┐
              │                                    │
           reelee                                muvid                  ← application layer
              │                                    │
              └────────────────┬───────────────────┘
                               ▼
                              nw        ProjectGraph · Transform · freshness · genres
                               │        (the A-annotation → B-annotation contract)
     ┌──────────┬──────────────┼──────────────┬────────────┬───────────┐
     ▼          ▼              ▼              ▼            ▼           ▼
  lacing      falaw          burns          mixing       LOOKS       artful …           ← focused capabilities
 (the data   (MONEY:        (AUTHORED      (edits +     (DERIVED
  SSOT)       remote,        camera over    execution)   geometry +
              billed,        a still)                    pixels;
              irreversible)      │                       local, free,
                 │               │                       reversible)
                 ▼               ▼                            │
        execution backends   render backends                  ▼
        (fal · ComfyUI · …)  (pillow · ffmpeg-via-looks)   NOTHING.
                                                           A compiled argv
                                                           fragment, run by
                                                           whoever owns the
                                                           invocation.
```

**There are two façade boundaries in this federation, not one, and they are parallel rather than stacked.**

`falaw.Plan` is the boundary below which *vendors and money* live. Everything about it — cost honesty, `unknown ≠ zero`, the approval gates, the content-addressed cache, the cumulative-bound discussion — exists because a billed remote call cannot be undone and the user must consent before it happens [4].

`looks.LookPlan` is a boundary below which *ffmpeg's vocabulary* lives. It protects a caller from having to know that `pyrMeanShiftFiltering` is not `edgePreservingFilter`, that `eq` is GPL-only, or that `zoompan` has no `t`. It gates nothing, because there is nothing to gate: re-running a look costs CPU-seconds and wall-clock, both of which are recoverable.

### 1.2 Why not a peer of `falaw` — the argument

Four reasons, in ascending order of decisiveness.

**(a) Position in the dependency graph would make muvid's integration an architecture violation.** The federation's standing rule is that *nothing above `falaw.Plan` may know which execution backend is in use* — `falaw/backends.py` states it in its own module docstring and calls a violation "an architecture bug regardless of whether it works" [5]. If `looks` sat at falaw's level, then reaching it would have to go *through* a plan, and `muvid` splicing a compiled `-vf` fragment straight into `_render_part`'s single-input filter string [9] would be exactly the violation that rule forbids. As a `burns`-peer it is instead precisely what `illustration.video` already does with `burns`: an app-level library call, documented as such, with the cycle it avoids stated in the docstring [14].

**(b) A `falaw.CallPlan` is denominated in dollars, and the correct dollar cost of a local ffmpeg run is `$0.00` — which is true, and useless.** Note 03 established that the honest unit for a `looks` plan is **CPU-seconds**, measured at 7.25 CPU-s per second of output for the Que Calor look at shipped settings and 21.14 for the clip that needed a different flattening scale [18]. Putting either number in `estimated_cost_usd` would corrupt the one field every cost gate in the federation reads; putting `0.0` there is correct and communicates nothing about a stage that can dominate a render's wall clock.

**(c) `falaw`'s executor contract does not fit.** `BackendExecutor` is `executor(application, arguments, *, on_event=None) -> dict`, returning "the vendor's *raw* response, in the same shape `falaw.core.call_fal` already returns", and the docstring is explicit that an executor "must not attempt caching (the registry sits below the cache) or artifact conversion" [5]. A local render returns a *file*, not a vendor response document. It is possible to synthesise a response shape; it is not natural, and naturalness is the whole reason the seam is there.

**(d) The decisive one: the federation already decided, and shipped the decision.** `nw.transforms.cache_key`, added in nw#54, opens with this [3]:

> falaw's content-addressed cache covers fal calls; a Transform that spends money or CPU **without** going through fal (ElevenLabs TTS, an ffmpeg extraction) has to carry its own compare-and-skip identity.

`braidio` is the shipped consumer. `braidio/transforms/_segment.py` describes itself in its first line as "**a local-render Transform**": `plan` returns a zero-call `Plan` plus a skeleton carrying a `cache_key`, and `execute` does the ffmpeg work "unless an identical `cache_key` already has an artifact" [15]. `braidio/transforms/_common.py::cached_output` wraps `nw.transforms.cached_output` and says why: "one convention, not one per genre" [15]. There is nothing to invent. A `looks`-backed Transform is a local-render Transform, and the category has a name, a helper, a reference implementation and a shipped issue number.

### 1.3 The one thing this costs, stated plainly

A local-render Transform returns `Plan(calls=())`. That is honest about money and **blind about time**: a dry run, a cost gate, a task tray and an MCP `dry_run` preview all read a `looks` stage as nothing at all, and at 21.14 CPU-seconds per output-second a four-minute stylized edit is roughly 85 CPU-minutes of invisible work. This is not a `looks` defect and `looks` must not fix it by lying in a dollar field. It is a gap in **nw's plan preview**, which is denominated in one currency; I found no open `nw` issue naming it (open issues as of 2026-09-02: #55, #44, #29, #9, #5 — none is this). `looks` is, however, the first package in the federation that can *supply* the missing number, because `LookPlan` carries a CPU estimate computed before a frame is decoded [18]. **Recommendation:** file it on `nw` when the first `looks` Transform lands, and offer `LookPlan.cpu_seconds` as the datum; do not block on it.

### 1.4 The registry deviation, declared rather than discovered

The workspace overview names `xdol.Registry` as "the ecosystem-wide plugin pattern" [2]. `looks` cannot use it: `xdol` depends on `dol`, and `looks`' non-negotiable is a `pyproject.toml` declaring nothing but stdlib (confirmed today: `dependencies = []` at version 0.0.1 [21]). This is **not a new deviation** — `burns.RENDER_BACKENDS` is a plain `dict` [6] and `muvid.visualize._VISUALS` is a plain `dict` [8]; both zero-dep-ish focused packages already do exactly this. Adopt xdol's *semantics* (error on conflict, a tags field reserved for the tier) without the import, and let a consumer mirror the mapping into an `xdol.Registry` if it wants tag search.

This matters more than it looks, because of nw#29. That open decision issue asks whether `nw`'s Transform registry should accept third-party registrations, and its research finding is, verbatim, the `looks` thesis arriving from the other direction: **85.5% of ComfyUI node packs declare no machine-readable licence, the `license` field has 76 distinct raw spellings, and the rule it derives is "any registry field that will later be queried for compliance must be a validated enum, enforced at publish time"** [22]. `looks`' effect registry is the first place in this federation where that rule can actually be implemented — the tier is an enum, resolved rather than declared, and refused when unknown [20]. Whoever writes nw#29's decision should read `looks`' tier module first.

---

## 2. Should `looks` effects be `nw.Transform`s?

**Yes — but `looks` neither defines nor registers one.** The Transform is a *consumer-side* object with three collaborators, and the value of answering this precisely is that each piece has exactly one right owner.

### 2.1 Why a stylize step really is a Transform

It satisfies the contract without strain. `input_kinds` / `output_kind` are body-schema URIs and a stylize step is `clip → clip`; `is_batch` is `False` for per-clip stylization and `True` for a set-level grade (which is why §5's two resolvers matter here); `params_model` is a Pydantic model carrying the look name and its ceiling; `impl_version` is "a lock, not a receipt" and a change to a look's compilation is exactly the "same interface, changed behaviour" case it exists for [3]. Registration refuses an empty `output_kind` loudly, "because an agent's unit of work must have a declared output type" [3] — a rule a stylize step passes trivially.

`generate_when` deserves a note: a `looks` fan-out is **`"static"`**. The work-item list for "stylize every cut in this EDL" is derivable from the graph before the run, which is the condition nw states for the static declaration [3]. That is unusual — the default is `"dynamic"` precisely so an unknown cardinality can never let a gate quote a number — and `looks` is one of the few Transforms that can honestly claim the cheaper answer.

### 2.2 Who owns which piece

| Piece | Owner | Why the arrow runs that way |
|---|---|---|
| `Effect`, `Look`, `ImplRef`, `Step`, `LookPlan`, `Ref`; the tier enum and its resolution; the effect registry; `compile()`; `resolve()` / `resolve_across()` | **`looks`** | Pure data and pure compilation. Zero dependencies is what lets every other row import it without inheriting a media stack. |
| The body-schema URI for "a look was applied to this interval", and its Pydantic model | **`nw`**, in `nw/bodies/` | It is a generic AV body of exactly the shape `render-result/v1` already has [3], and registering it needs `lacing.schema.register_body_schema` — an import `looks` may not make. `looks` embeds its own `SPEC_VERSION` inside the body as an **opaque versioned sub-document**, the way `muvid.genre` carries `params={"visual": …}` opaquely for nw to pass through [25]; `nw` pins `looks.SPEC_VERSION` and the round-trip in a test, so a `looks` wire bump turns `nw` red instead of silently changing a persisted body. That two-owner split is the mitigation for artful's migration-required rule [24] applied to a package that cannot import lacing. |
| The Transform class itself (`clip_to_clip.looks`, name per nw's `<from>_to_<to>[.flavor]` convention [3]) | **`muvid` first; `nw` on the rule of three** | The first customer owns it. Graduation into `nw` when `reelee` becomes the second consumer is muvid#4's shipped, deliberate pattern [2], and `nw`'s own decision guide says "operate on an AV project folder → `nw`" [2]. Do **not** put it in `nw` on day one: nw#29 has not decided whether the registry is open, and a first-party `muvid` registration sidesteps that question entirely. |
| The subprocess that runs the compiled argv | **the consumer** — `muvid.visualize.ffmpeg.run_ffmpeg`, `burns`' new backend, `reelee`'s renderer | `looks` must not execute. This is the kickoff's non-negotiable and §6's rule L3. |
| The compare-and-skip identity | **`nw.transforms.cache_key`** (nw#54) | Shipped, and braidio already uses it. Note it is *not* re-exported at `nw` top level — verified today: `cache_key` and `cached_output` are absent from `dir(nw)` and must be imported from `nw.transforms`. |
| A `falaw` local-execution backend | **nobody, for now** | See §1.2(c). Reconsider only if a second, independent local-render family appears *and* someone wants local stages inside the money plan; the precondition is a decision about what a local `CallPlan`'s `estimated_cost_usd` means. |

### 2.3 The dependency arrows, written out

```
muvid   ──► looks        (app calls library)
burns   ──► looks        (render backend compiles through it — §4)
mixing  ──► looks        (imports the geometry vocabulary — §3.3)
reelee  ──► looks        (via nw, or directly, like it already imports burns [16])
nw      ──► looks        (only once the Transform graduates; looks is stdlib-only so this is cheap)

looks   ──► NOTHING
```

The last line is the load-bearing one and it is enforceable (§6, L1/L2). Three of the packages `looks` integrates with already redistribute a GPL ffmpeg binary through `moviepy → imageio-ffmpeg` — `burns` (declares `numpy`, `moviepy`, `pillow`), `mixing` (declares `moviepy` and prefers the bundled binary at runtime [12]) and `paces[media]` (which explicitly chooses the bundled binary "so CI needs no system ffmpeg" [13]). `looks`' zero-dependency promise is the only thing keeping it out of that closure, and a one-line convenience import would end it.

---

## 3. Consumers, sequenced

### 3.1 The integration table

| # | Consumer | What it wants | What `looks` must expose for the switch | Arrow | Precondition | Effort |
|---|---|---|---|---|---|---|
| 1 | **`muvid`** — footage-assembly genre | Per-cut stylization *and* the in-shot punch-in the design partner asked for (muvid#66) | `compile(look, caps) -> str` returning an **input-index-free** `-vf` fragment; `resolve_across(look, probes)`; a `Probe` protocol; a declared capability set as an *argument* | `muvid → looks` | Rule C1 [19]; the `Probe` shape; `require_filter` available to the consumer | **Small** — one optional field on the EDL entry, one splice in `_render_part` |
| 2 | **`burns`** — as a *supplier*, not a consumer | Its declared-but-unbuilt second render backend [6] | A keyframed-`crop` compiler taking `(t, Rect)` pairs through a structural protocol (never a `burns` import) | `burns → looks` | §4's ratification; the measured `zoompan` negative [17] | **Small-to-medium** |
| 3 | **`mixing`** — the geometry tier | One canonical fit/fill/pad/social vocabulary instead of two implementations | `SOCIAL_SIZES`, the four fit methods as *ffmpeg strings*, even-snap policy, `Rect` convention | `mixing → looks` | **Not a clean move** — see §3.3 | **Medium**, and it needs a decision |
| 4 | **`reelee`** | A stylize stage in the storyboard/animatic pipeline; a look as a persisted decision | The `nw` body schema (§2.2) plus everything muvid needed | `reelee → nw → looks` | The Transform graduating into `nw` | **Small** — `panel_to_clip.kenburns` is the template [16] |
| 5 | **`nw`** | To host the graduated Transform | Nothing new | `nw → looks` | Rule of three satisfied (muvid + reelee) | **Small** |
| — | **`illustration`**, **`walkthru`** | Nothing directly | Nothing | transitive via `burns` | #2 landing | **Zero code change** — they get the ffmpeg fast path for free |
| — | **`paces`** | Candidate: it derives clips [13] and it produced the Que Calor material | Everything muvid needed, plus honesty about *which binary* | `paces → looks` | The capability-set rule (§3.4) | Unscheduled |
| — | **`braidio`** | **Nothing. It is audio-only** [2] | — | — | — | **Non-consumer** — but it is the *pattern donor* (§1.2d) |
| — | **`an`** | **Nothing, by its own declaration** | — | — | — | **Non-consumer** — `an`'s StylePack recolours its own compiler palette and "does **not** recolour SVG art" [1]. `an` styles what it *draws*; `looks` styles what it *receives*. Clean complement, no overlap. |

Two entries in that table correct the brief. **`braidio` is not downstream of `looks` — it has no video path at all**; its role is that it already wrote the local-render Transform pattern `looks` should copy. And **`burns` is a supplier, not a consumer** — the arrow runs from burns into looks, which is the opposite of what "should burns become a looks backend" suggests.

### 3.2 `muvid` first, and the seam is one string

`muvid/footage/assemble.py::_render_part` renders one cut to one intermediate — the single-decoder stage that the whole bounded-memory invariant rests on — and it builds exactly one filter string [9]:

```python
crop = _crop_filter(cut)
vf = (
    f"{crop + ',' if crop else ''}"
    f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
    f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},"
    f"tpad=stop=-1:stop_mode=clone"
)
```

That is the insertion point, and it is the *right* one for three reasons that are not obvious.

It is **already per-cut**, which is precisely where the Que Calor finding says a look's parameters must resolve: `AssemblyCut` is one cut, and `_crop_filter` is already compiling a per-cut normalised window into ffmpeg [10]. A `look` field on the EDL entry, carried through to `AssemblyCut` the way `transition` and `crop` already are [10], reaches `_render_part` with nothing else changed.

It **cannot break the memory invariant**, because a `-vf` fragment adds no decoder. muvid's OOM history is about the *number of inputs* in one `-filter_complex` — ">2.3 GB for a 30-cut edit, OOM-killed on the 3.7 GB production box" [9]. Rule C1 (a compiled `Look` references no container input index [19]) is what keeps that true: a `Look` that wanted a second *file* would have to reach it as `movie=`, a filter, not an `-i`.

And it is the **same insertion point as normalisation**, which is §5's whole argument arriving from the code.

muvid is also where the proposal originated — muvid#63 is the `looks` proposal issue [26], still open — and muvid#66 is the second, independent reason it goes first: a named design partner asked, on 2 September 2026, for "roughly `2N`" in-shot punch-ins, "explicit that it is **not** a transition between two clips: it stays on the same shot", and the issue records that "there is **no** punch-in, zoom or Ken-Burns move anywhere in the footage path" [23]. That is a live user request whose answer is a geometry-over-time effect compiled into that same `-vf` — i.e. the burns↔looks adapter of §4, with a customer already waiting.

### 3.3 `mixing` third, and it is **not** the deprecation-free move the kickoff assumes

The kickoff proposes moving `mixing/video/video_util.py` entire, "deprecation-free… mixing has no external users for these" [21]. **That is not true**, and I checked rather than assumed: `paces` imports `mixing.get_video_dimensions` at **three source call sites** (`paces/derivation.py`, lines 694, 889, 923) and **two test call sites** (`paces/tests/test_vertical_slice.py`, lines 105, 150). Note 02 found the same thing independently [17]. `paces` pins `mixing>=0.0.39` in its `[media]` extra for, among other things, "path-accepting `get_video_dimensions`" [13] — so the function's *path-accepting* signature is a contract paces depends on by version floor.

There is a second, deeper obstruction. `mixing.video_util` is moviepy-through-and-through — its module imports `VideoFileClip`, `VideoClip`, `ImageClip`, `CompositeVideoClip` at the top [11] — and `mixing.util.ffmpeg_exe()` deliberately resolves ffmpeg to `imageio_ffmpeg.get_ffmpeg_exe()` before falling back to `PATH` [12]. Moving that code into `looks` means moving a moviepy dependency into a package that declares none. It cannot happen.

**Recommendation:** `looks` owns the **vocabulary**, `mixing` keeps the **moviepy implementations** and imports the vocabulary back. Concretely, `looks` gets `SOCIAL_SIZES`, the four fit methods as *named, tier-carrying effects compiling to ffmpeg strings* (muvid's `canvas.py` already has the ffmpeg form of exactly these treatments [17]), the even-snap policy, and the normalised-`Rect` convention; `mixing.video_util` keeps `resize_to_dimensions` and `get_video_dimensions` as moviepy functions and takes its constants from `looks`. `paces` breaks nothing. Note 02 reached the same conclusion by a different route and labelled it **PORT, not EXTRACT** [17]; I am agreeing with it and adding the `paces` consumer count and the `ffmpeg_exe` reason as the evidence.

The six transitions in `video_concat.py` are a different case and the kickoff is right about them: they are pure vocabulary (which `xfade` curve, how long) and muvid already curates a 16-of-58 subset in `TRANSITION_CURVES`, refused at validation rather than passed through to ffmpeg [17]. Those move — subject to rule L6 (§6).

### 3.4 The finding that constrains every consumer: two ffmpegs, non-nested

This is new and it is measured. On this machine on 2026-09-02 there are two ffmpeg binaries in routine use by federation packages, and neither is a superset of the other.

| | Bundled (`imageio_ffmpeg.get_ffmpeg_exe()`) | On `PATH` |
|---|---|---|
| Package version | `imageio-ffmpeg` 0.6.0 | homebrew `ffmpeg` 8.1_1 |
| ffmpeg version | **7.1** (2024) | **8.1** (2026) |
| Licence flags | `--enable-gpl`, **no** `--enable-version3` | `--enable-gpl --enable-version3` |
| `--enable-libzimg` | **yes** | **no** |
| Filters enumerated | **484** | **481** |
| Only in this build | `ass`, `drawtext`, `pp`, `subtitles`, `vidstabdetect`, `vidstabtransform`, **`zscale`** (7) | `colordetect`, `premultiply_dynamic`, `transpose_vt`, `yadif_videotoolbox` (4) |

Commands: `python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"` → `…/site-packages/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1`, then `<exe> -version` and `<exe> -hide_banner -filters` against the same two invocations on `ffmpeg`. Filter names taken as field 1 of every line whose field 3 contains `->`. Build identities per [27].

Four consequences, each of which changes something.

**The GPL binary claim is confirmed, and it is worse-shaped than assumed.** The bundled binary is built `--enable-gpl` **without** `--enable-version3`, with `--enable-libx264 --enable-libx265 --enable-libvidstab --enable-postproc`. So `pip install mixing`, `pip install burns` and `pip install paces[media]` each redistribute a GPL-2.0-or-later ffmpeg. That is execution, not linking, so the Python code is not infected — but it *is* redistribution, and it should be a recorded decision rather than an accident. This is the kickoff's known finding [21] verified on the actual artefact.

**Which binary runs depends on which package invoked it, and the capability difference is material.** `mixing` and `paces` reach the bundled 7.1; `muvid` calls `run_ffmpeg` against `PATH` [17]. `zscale` — the correct filter for colour-range and matrix conversion, which note 05 makes central to the `ColorContract` refusal [19] — exists **only** in the pip-bundled build, because the homebrew build has no `--enable-libzimg` (verified: `ffmpeg -version | grep -o -- --enable-libzimg` returns nothing, and `ffmpeg -filters | grep -c zscale` returns 0). `drawtext` exists **only** in the bundled build, which is the reverse of note 02's finding that "the ffmpeg on this machine's PATH cannot draw text" [17] — both statements are true; they are about different binaries.

**Therefore: `looks` must never resolve the binary.** The capability set is an argument to `compile()`, supplied by whoever owns the invocation. This is rule L7 (§6) and it is what makes rule L3 (no subprocess) survivable rather than crippling: `looks` cannot probe, so `looks` must be told.

**And the enumeration itself is a trap.** The `-filters` output format changed between 7.1 and 8.1 such that a regex written against one returns **zero** filters against the other — I wrote two parsers, each of which reported `0` for the version it was not written for, before falling back to muvid's whitespace-field-split approach, which handles both. A capability check that silently returns an empty set either refuses everything or accepts everything, depending on the sense of the comparison. muvid's parser is robust here for a stated reason ("splits on whitespace and takes field 1 rather than slicing columns" [17]); whatever `looks` documents as the expected shape of a capability set, the *derivation* of it belongs to the consumer and should reuse muvid's.

---

## 4. Owner question 1 — `burns`

> **RECOMMENDATION FOR RATIFICATION.** `burns` stays separate. `looks` gains **no** geometry-over-time type. `burns` gains a `looks`-backed **ffmpeg render backend**, which is the third option in the brief and also the direction `burns` already declared for itself.

### 4.1 Why "make `burns` a `looks` backend" is not available

`burns` declares `numpy`, `moviepy`, `pillow` (read from its `pyproject.toml` today). `moviepy` pulls `imageio-ffmpeg`, whose bundled binary is `--enable-gpl` (§3.4). So `looks → burns` would give `looks` a transitive GPL-binary redistribution and a heavy install, ending its zero-dependency promise on the first import. The question is settled by the dependency direction before any design argument is reached.

### 4.2 Why "fold geometry-over-time into `looks`" is not available either

`burns.BurnsPath` — a pure `evaluate(t) -> Rect` with its own `SPEC_VERSION` and easing composed over geometry [7] — is imported across the federation: source-level importers today are `mixing/video/video_ops.py`, `reelee/{kenburns_video,manual_video,transforms/panel_to_clip}.py`, `walkthru/ecosystem/reelee/render_target.py` and `illustration/video.py`, plus tests (my `rg` over `$PP/{t,tt,i}` for `^\s*(from|import)\s+burns`, excluding `t/burns` itself, found 10 files across 4 non-burns packages; note 02 reports 15 files across 6 by a broader match [17] — either way, it is load-bearing). It also has a cross-language contract: the `kenburnz` TS package with golden vectors [2]. And `muvid.footage.edl.CropWindow` deliberately adopts `burns.Rect`'s convention — "top-left origin, window fraction — so a crop authored here and a Ken Burns path computed there interoperate with no rename table" [10]. Two packages have already agreed a convention. A third type would be the mistake that docstring exists to prevent.

### 4.3 The clean line — a rule someone can apply without asking

The brief is right that "no geometry in `looks`" is not the line, because `looks` inherits resize/crop/pad. Nor is it "stills versus video", because `muvid`'s moving crop window is a camera move over *video* [10]. The line that works — and that predicts every case already in the code — is about **who chose the rectangle**:

> **RULE G. If the geometry is AUTHORED — a person or a model chose it as the shot, and changing it changes what the viewer is looking at — it is a camera, and it belongs to `burns`. If the geometry is DERIVED — it falls out of a delivery contract (a target canvas, an aspect ratio, an even-dimension requirement, a measured black-bar boundary) such that any two implementations given the same inputs must compute the same rectangle — it is conformance, and it belongs to `looks`.**

Applied, without ambiguity:

| Effect | Verdict | Why |
|---|---|---|
| Scale + pad to 1080×1920 | `looks` | derived from the target canvas |
| Centre-crop-to-fill at 9:16 | `looks` | derived from the aspect mismatch; nobody *chose* the centre, it is the only defensible default |
| Even-dimension snapping | `looks` | derived from a codec requirement |
| Letterbox removal (`cropdetect`) | `looks` | derived from a measurement of the source, not from taste |
| Ken Burns push-in over a still | `burns` | authored — the whole point is the choice |
| `burns.content_aware_path` / `salient_box` | `burns` | authored, with a saliency model standing in for the human |
| muvid's `CropWindow` / `crop_end` ramp | `burns`-shaped | authored — the scorer or the operator picked which part of a phone recording to show. muvid already uses `burns.Rect`'s convention for it [10], which is the rule predicting existing code rather than being imposed on it |
| muvid#66's in-shot punch-in | `burns`-shaped, compiled by `looks` | authored (someone asked for N of them); executed as a ramped `crop` in a `-vf` — exactly the adapter |
| flatten → LUT → posterise | `looks` | not geometry at all |

The corollary that makes Rule G *productive* rather than merely tidy: **an authored camera path still has to be executed, and over video input the execution is an ffmpeg `crop` with ramped expressions — which is a `looks`-compilable stage.** So the two packages are not competing; one authors, the other compiles.

### 4.4 The adapter, and a measured warning to hand the `burns` owner

`burns/backends.py` already names the target: "adding a backend (an FFmpeg `zoompan` fast-path, a future GPU path) never edits the facade — you `register_backend` it" [6]. The backend contract is `(img_np, img_w, img_h, path: BurnsPath, *, duration, fps, output, out_w, out_h, codec, audio_codec, **kw) -> Path` [6].

Shape of the adapter: `burns` (which may import `looks`, since `looks` is stdlib-only) registers an `"ffmpeg"` backend that samples its `BurnsPath` into keyframes, hands them to `looks` for compilation into a `crop`+`scale` fragment, and runs the resulting argv itself. `looks` never imports `burns`; it accepts a structural `Rect`-shaped protocol, which is what note 02 already recommended [17]. `looks` compiles; `burns` executes. That is the same split as everywhere else in this note.

**The warning — and it should reach the `burns` owner whatever they decide about `looks`:** `zoompan` is the wrong filter for this. `muvid/footage/assemble.py::_crop_filter` records the measurement in its own docstring — *"Not `zoompan`: its expression vocabulary has no `t` at all (it exposes `on`/`in`/`pon`), and it duplicates frames on video input"* [17], and `_crop_filter` therefore compiles a moving window as `crop=w='iw*…':h='ih*…':x='…':y='…'` with a clamped linear ramp in the filter's own `t`, prepending `setpts=PTS-STARTPTS` only in the moving case [9]. For `burns`' actual case — a *still* image looped — `zoompan` may still be viable (its integer-rounding stair-step is what the `pillow` backend's docstring already cites as its own quality advantage [6]), so this is a warning about the *video* case, which is the one muvid#66 needs. **Unverified:** I did not benchmark a `crop`-ramp encode against the `pillow` backend, so the claimed speed advantage of an ffmpeg fast-path is inherited from `burns`' own docstring, not measured here.

### 4.5 What ratifying this costs, and what rejecting it costs

Ratifying: one new backend in `burns` behind an optional `[looks]` extra, and `looks` gains a keyframed-`crop` compiler it needs anyway for muvid#66. Nothing existing changes; `illustration` and `walkthru` get the fast path for free by selecting a backend name.

Rejecting (i.e. `looks` grows its own geometry-over-time type): a third normalised-rect convention in the federation, a second `t → Rect` evaluator to keep in sync with `kenburnz`'s golden vectors, and the exact rename table `muvid.footage.edl`'s docstring was written to prevent.

---

## 5. Owner question 2 — normalisation

> **RECOMMENDATION FOR RATIFICATION.** Yes. One package, one vocabulary, one registry, one tier system, one insertion point. The API difference is **two resolvers, not two Effect types**, and the `intent` field earns its place only because it selects which resolver is legal.

### 5.1 The case for one vocabulary

**They compile to the same place.** Not analogously — literally. `_render_part`'s `vf` string is one comma-chain and both a continuity grade and an extreme look go into it [9]. Two packages would mean two compilers writing into one string, with ordering (which note 05 measured: nothing that resamples may follow something that quantises [19]) negotiated across a package boundary.

**The Que Calor measurement makes them mutually dependent.** The established rule is that the right auto-rule *normalises the output across sources, not the input* — measure post-effect sharpness per source and pick parameters that land them in family (clip A 35→72, B 117→114, C 46→38; spread cut from 2.98× to 1.59× by a per-clip flattening scale) [21]. **You cannot compute the continuity grade without knowing what the stylization does to the clip.** Splitting them puts a measurement loop across a package boundary, which is the one thing a boundary must not do.

**The tier system is identical, and normalisation is where it bites harder.** Note 06 measured that 32 of ffmpeg 8.1's video filters exist only in a GPL build, and that `eq` — *the* brightness/contrast/saturation/gamma filter, the natural implementation of a continuity grade — is one of them, while the Que Calor stylization chain (`lut3d`, `lutrgb`, `curves`, `colorchannelmixer`, `scale`, `format`) is entirely LGPL-clean [20]. So the *normalisation* half is the half more likely to hit a caller's ceiling, and the "here is the LGPL-clean alternative chain" behaviour matters more for it. One tier system, applied to both, with the pressure falling on normalisation.

**Both need the same deferred-parameter machinery.** `Ref` plus a `resolve` pass over a caller-supplied probe [18] serves both without modification.

### 5.2 The case against, taken seriously

**Different intents, and a real hazard.** A style Look is meant to be *the same across an edit* — it is the thing you name and reuse. A grade is *different for every clip by construction*. Putting them in one type risks a `Look` that is silently clip-specific being shipped as if it were reusable.

**Normalisation wants to be automatic, and automatic things drift toward owning measurement and execution** — the two things `looks` must not own.

Both objections are real; neither survives contact with the existing design. The first is answered by §5.3's invariant. The second is already answered by note 03's architecture: `looks` declares what must be measured (a pure-data `Ref`) and consumes a `Probe` the caller supplies; it never measures [18]. Rules L3/L4/L12 (§6) make that mechanical.

### 5.3 What actually differs, and what changes in the API

The honest distinction is **not** "corrective versus expressive" — it is **what the target is**, and that maps onto a distinction the federation already knows from `lookbook`: per-image *scoring* versus set-level *selection* [2].

- A **stylization**'s target is *external and fixed*: a reference image, a palette, a LUT. Each clip is measured against it independently.
- A **normalisation**'s target is *the set itself*: the other clips in the same edit. It is a mutually-constrained N-in/N-out problem, and a grade computed for one clip in isolation is meaningless.

So the API change is one extra entry point, not one extra type:

```
resolve(look, probe)            -> Look           # target external; one clip
resolve_across(look, probes)    -> tuple[Look]    # target = the set's own distribution; N clips, N Looks
```

And the `intent` field — if it exists at all, and it should — belongs on the **`Look`**, valued `"style" | "grade"`, with exactly one mechanical job:

> **RULE N. A `Look` with `intent="grade"` may only be resolved through `resolve_across`. Resolving a grade against a single clip raises.** A `Look` with `intent="style"` may go through either.

That is an intent field that *does something*, rather than documentation that drifts. It also directly encodes the §5.1 hazard: a grade cannot be accidentally treated as a reusable single-clip artefact, because the only resolver that accepts it needs the whole set.

**Does normalisation *need* the clip-aware layer while stylization merely benefits?** Sharpen the question and it answers itself: normalisation needs the **set**-aware layer *by definition* (its target is the set). Stylization needs the **clip**-aware layer *by definition* (its parameters resolve against the clip it applies to). And the Que Calor result is that a *good* stylization needs the set-aware layer too, **by measurement** — the whole finding was that a single global flattening scale made the softest source the mushiest thing on screen, and that full resolution was available, sharper, and deliberately not used because at ~150 Laplacian variance it would have made that same source the *sharpest* thing in the edit [21]. Same layer, reached by two different routes. That is the strongest single argument for one package.

**Does the tier system treat them differently?** No — and it must not. The refusal is a property of the *implementation selected*, never of the request [18]; a caller demanding commercial-safe wants the same answer whether the effect is corrective or expressive. What differs is only empirical pressure (§5.1).

---

## 6. What `looks` must NEVER do

Rules a future agent can check, most of them mechanically. Each names its enforcement.

| | Rule | How to check it |
|---|---|---|
| **L1** | **Declare a runtime dependency.** `[project] dependencies` stays `[]`; every backend is an optional extra. | Assert on the parsed `pyproject.toml` in a test. |
| **L2** | **Import a federation package** — `nw`, `lacing`, `falaw`, `burns`, `mixing`, `muvid`, `reelee`, `dol`, `xdol` — at module top **or** lazily inside a function. The arrow runs one way (§2.3). | AST scan over `looks/` for any `Import`/`ImportFrom` naming them, at any depth. `an/tests/test_licence_perimeter.py` is the fleet's precedent for a perimeter test [17]. |
| **L3** | **Spawn a process.** No `subprocess`, no `os.system`, no `os.popen`, no `shutil.which`. This is what "`looks` does not execute" means when made mechanical — and it is why L7 exists. | AST scan for those names. |
| **L4** | **Touch the filesystem it was not handed.** No `open()` on a path `looks` computed; a LUT is referenced by content digest plus a path the caller supplies. | AST scan for `open`/`Path.read_*`/`Path.write_*`. |
| **L5** | **Emit a container input index in a compiled filter string.** Not `[0:v]`, not `[1:v]` — rule C1 [19]. A second source enters as `movie=` or a lavfi source, never as an `-i`. | Regex over every `compile()` output in the test suite. This is what lets one compiled `Look` splice into muvid's `_render_part`, a bare `-vf`, and a raw-frame pipe's encoder half unchanged. |
| **L6** | **Decide where a cut is.** `Effect.at` is an interval *within* a clip. `looks` may own a transition's *vocabulary and compilation* (which `xfade` curve, how long) but never the boundary it sits on — the boundary is an EDL invariant that stays with the EDL [10]. | Review rule; assert no `looks` API takes a list of clips and returns boundaries. |
| **L7** | **Resolve which ffmpeg binary will run.** The capability set is an argument. Measured: two binaries in this environment with non-nested filter sets (§3.4), and `looks` gets no say in which one a consumer invokes. | Follows from L3. Additionally: assert `compile()` requires an explicit capability argument with no `PATH`-probing default. |
| **L8** | **Downgrade a refusal to a warning.** An unknown licence tier is a refusal [20]. An unknown colour contract is a refusal, escapable only by an explicit recorded `assume=` [19]. Unknown is never permission. | Test that each unknown path raises; mutation-test the guard. |
| **L9** | **Own a second geometry-over-time type.** Authored camera paths are `burns`' (Rule G, §4.3). `looks` accepts a structural `Rect`-shaped protocol and compiles keyframes; it does not define a `Path`. | Review rule; assert no `looks` type stores a trajectory as its primary content. |
| **L10** | **Register itself into another package's registry.** `looks` never calls `nw.register_transform`, `falaw.backends.register` or `burns.register_backend`. The consumer registers. | Follows from L2. |
| **L11** | **Mutate a `Look`.** Frozen dataclasses throughout; `resolve` returns a new `Look` [18]. | `dataclasses.FrozenInstanceError` tests. |
| **L12** | **Measure a clip.** `looks` declares what must be measured (a pure-data `Ref`) and consumes a `Probe` the caller supplies. | Follows from L3/L4; additionally assert no numeric-image dependency ever appears. |
| **L13** | **Grow a convenience `render()`.** The kickoff's non-negotiable [21]: it will get used and it will rebuild one big `-filter_complex`, which is exactly the shape muvid's bounded-memory work eliminated after 30-cut OOM kills [9]. | Assert no public name in `looks.__all__` returns a path or writes a file. |

L13 deserves the last word because it is the rule most likely to be violated by a well-meaning future agent, and the cost is not abstract: `muvid/footage/assemble.py` documents a real production box, a real 2.3 GB peak, and a real OOM kill [9].

---

## 7. Open questions, and what I could not verify

1. **Which body-schema URI, and its exact shape.** §2.2 assigns ownership to `nw` but I did not draft the model. It should follow `render-result/v1`'s shape (small body, heavy data in the referenced Artifact [3]) and carry the `looks` wire document opaquely with its `SPEC_VERSION`. **Owner decision**, and it is migration-required once anything persists it [24].
2. **The Transform's name.** nw's convention is `<from_kind>_to_<to_kind>[.flavor]` [3]. A stylize step is `clip → clip`, which the convention does not obviously spell. `clip_to_clip.looks` is legal and ugly; `stylize.looks` is readable and off-convention. **Owner decision.**
3. **nw#29 (open) may constrain where the Transform can live.** As long as `muvid` (first-party) hosts it, the question does not bind. If the eventual answer is "closed registry", `looks` must never ship a Transform of its own — which L10 already forbids for other reasons. Worth reading `looks`' tier design into that decision (§1.4).
4. **The CPU-cost invisibility gap in nw's plan preview** (§1.3). No issue found; file it when the first `looks` Transform lands.
5. **Unverified: the ffmpeg-fast-path speed claim for `burns`.** §4.4 inherits it from `burns/backends.py`'s own docstring; I ran no benchmark.
6. **Unverified: the ffmpeg build comparison is macOS/arm64 only.** `imageio-ffmpeg` 0.6.0 ships per-platform binaries; the Linux and Windows binaries may differ in version and configure flags from the `ffmpeg-macos-aarch64-v7.1` I inspected. The *rule* it motivates (L7) does not depend on the specific numbers, but do not quote the 484/481 figures as cross-platform.
7. **Unverified: whether the reverse direction — the pip-bundled binary being *more* capable than the system one — holds on the server.** The server is Linux with its own ffmpeg; this was measured only on the Mac.
8. **Unverified: the count of `burns` importers.** My strict `rg` found 10 files across 4 non-burns packages; note 02 reports 15 files across 6 by a broader match [17]. Both support the conclusion (`burns` is load-bearing and must not be absorbed); neither number should be quoted as exact.
9. **`paces` as a consumer is a guess, not a plan.** It derives clips and it produced the Que Calor material, but nothing in `paces` currently asks for stylization. **Owner decision** whether to pursue it.

---

## REFERENCES

[1] video_gen group session root — `CLAUDE.md` (federation notes, the ComfyUI decisions of record, `an`'s StylePack boundary). Path: `$PP/t/priv/data/groups/video_gen/CLAUDE.md`.

[2] video_gen workspace overview — `$PP/t/priv/data/groups/video_gen/workspace_overview.md` (last truth-verified 2026-08-15): the big-picture diagram, the per-package state table, the "where does this go?" decision guide, the cross-cutting invariants, and the `xdol.Registry` convention.

[3] `nw.transforms` — the `Transform` Protocol (`input_kinds` / `output_kind` / `is_batch` / `impl_version` / `params_model` / `generate_when`), `BaseTransform.execute`, `register_transform`'s validation, `stamp_transform_identity`, and `cache_key` (nw#54). Path: `$PP/t/nw/nw/transforms/__init__.py`. Repo: [thorwhalen/nw](https://github.com/thorwhalen/nw).

[4] `falaw.plan` — `CallPlan` / `Plan`, the cost properties, `key_extra` vs `metadata`. Path: `$PP/t/falaw/falaw/plan.py`. Repo: [thorwhalen/falaw](https://github.com/thorwhalen/falaw).

[5] `falaw.backends` — the execution-backend registry, the `BackendExecutor` contract, and the "nothing above `falaw.Plan` may know a specific backend exists" rule. Path: `$PP/t/falaw/falaw/backends.py`.

[6] `burns.backends` — `RenderBackend` Protocol, `pillow_backend`, `RENDER_BACKENDS`, `register_backend`, and the docstring naming "an FFmpeg `zoompan` fast-path" as the intended second backend. Path: `$PP/t/burns/burns/backends.py`. Repo: [thorwhalen/burns](https://github.com/thorwhalen/burns).

[7] `burns.path` — `BurnsPath`, `evaluate(t) -> Rect`, keyframes, easing composed over geometry, `SPEC_VERSION`. Path: `$PP/t/burns/burns/path.py`.

[8] `muvid.visualize.visuals` — `VisualContext`, `VisualPlan`, `register_visual`, `resolve_visual` and the rendered-path escape hatch. Path: `$PP/t/muvid/muvid/visualize/visuals.py`. Repo: [thorwhalen/muvid](https://github.com/thorwhalen/muvid).

[9] `muvid.footage.assemble` — the bounded-memory invariant (three stages, O(1) in cut count, the 30-cut/2.3 GB OOM history), `_crop_filter`, and `_render_part`'s single-input `-vf` string. Path: `$PP/t/muvid/muvid/footage/assemble.py`.

[10] `muvid.footage.edl` — `CropWindow` (adopting `burns.Rect`'s convention deliberately), `Transition`, `TRANSITION_CURVES`, `AssemblyCut`. Path: `$PP/t/muvid/muvid/footage/edl.py`.

[11] `mixing.video.video_util` — `SOCIAL_SIZES`, `get_video_dimensions`, `resize_to_dimensions`, `normalize_video_dimensions`; moviepy imports at module top. Path: `$PP/t/mixing/mixing/video/video_util.py`. Repo: [thorwhalen/mixing](https://github.com/thorwhalen/mixing).

[12] `mixing.util.ffmpeg_exe` — resolution order `imageio_ffmpeg.get_ffmpeg_exe()` → `shutil.which("ffmpeg")`. Path: `$PP/t/mixing/mixing/util.py`.

[13] `paces` — `derivation.py` (three `mixing.get_video_dimensions` call sites at lines 694, 889, 923; the `bundled_ffmpeg` / `system_ffmpeg` readiness check) and `pyproject.toml`'s `[media]` extra pinning `mixing>=0.0.39` for "path-accepting `get_video_dimensions`". Path: `$PP/t/paces/`. Repo: [thorwhalen/paces](https://github.com/thorwhalen/paces).

[14] `illustration.video` — the adapter precedent: renders through `burns` directly and states why it must not route through `walkthru`'s reelee render target (an `illustration → reelee → illustration` cycle). Path: `$PP/t/illustration/illustration/video.py`. Repo: [thorwhalen/illustration](https://github.com/thorwhalen/illustration).

[15] `braidio` — the local-render Transform reference implementation: `transforms/_segment.py` (zero-call `Plan` + `cache_key` skeleton) and `transforms/_common.py::cached_output` ("one convention, not one per genre"). Path: `$PP/t/braidio/braidio/`. Repo: [thorwhalen/braidio](https://github.com/thorwhalen/braidio).

[16] `reelee.transforms.panel_to_clip` — `panel_to_clip.kenburns`, a shipped burns-backed local-render Transform ("No fal call, no cost"). Path: `$PP/tt/reelee/reelee/transforms/panel_to_clip.py`. Repo: [thorwhalen/reelee](https://github.com/thorwhalen/reelee).

[17] `looks` research note 02 — *Local ecosystem prior art*. The fleet sweep, the PORT/EXTRACT/CONSUME/LEAVE verdicts, the `escape_filter_value` and `require_filter` findings, the `zoompan`-has-no-`t` measurement, and the interpreter trap. Path: `$PP/t/looks/docs/research/02_prior_art_fleet.md`.

[18] `looks` research note 03 — *The core type design*. `Effect` / `Look` / `ImplRef` / `Step` / `LookPlan` / `Ref`, the tier-declared-by-implementation rule, the CPU-seconds cost unit and its measured values (7.25 and 21.14 CPU-s per output-second). Path: `$PP/t/looks/docs/research/03_spec_type.md`.

[19] `looks` research note 05 — *Compilation semantics, colour correctness and the backend seam*. Rule C1 (no container input index), the `-vf`-can-branch correction, the two-independent-colour-tags measurement, the raw-frame pipe cost, and the quantise-before-resample ordering rule. Path: `$PP/t/looks/docs/research/05_compilation_and_backends.md`.

[20] `looks` research note 06 — *The licence-tier taxonomy*. The four axes, the resolved-not-declared tier, the 32 GPL-only ffmpeg 8.1 filters including `eq`, and the `opencv-contrib-python` metadata contradiction. Path: `$PP/t/looks/docs/research/06_licence_tiers.md`.

[21] `looks` — `KICKOFF.md` (the mandate, the non-negotiables, the measured Que Calor findings, the mixing refactor order, the two owner questions) and `pyproject.toml` (version 0.0.1, `dependencies = []`). Path: `$PP/t/looks/`. Repo: [thorwhalen/looks](https://github.com/thorwhalen/looks).

[22] thorwhalen/nw issue #29 — [*Decide, before the first third party arrives: does the Transform registry accept third-party registrations?*](https://github.com/thorwhalen/nw/issues/29). Open as of 2026-09-02; source of the ComfyUI registry licence-metadata measurements and the "validated enum, enforced at publish time" rule.

[23] thorwhalen/muvid issue #66 — [*Edit request from the design partner: double the punch-in moments and the cutting speed — and the footage path has no in-shot zoom*](https://github.com/thorwhalen/muvid/issues/66). Filed 2 September 2026; open. The first named customer for a geometry-over-time effect in the footage path.

[24] `artful` — `CLAUDE.md`'s "THE MIGRATION-REQUIRED RULE": body-schema URIs are the federation's carve-out from "clean shape over backward compatibility". Path: `$PP/t/artful/CLAUDE.md`. Repo: [thorwhalen/artful](https://github.com/thorwhalen/artful).

[25] `muvid.genre` — the `music-visualizer` nw Genre: import-safe, no Transforms, Templates carrying opaque `params={"visual": …}` that muvid resolves at render time. Path: `$PP/t/muvid/muvid/genre.py`.

[26] thorwhalen/muvid issue #63 — [*Video stylization: propose a new facade package (`looks`)*](https://github.com/thorwhalen/muvid/issues/63). The proposal issue; open as of 2026-09-02.

[27] [FFmpeg](https://ffmpeg.org/) — versions observed on this machine on 2026-09-02: homebrew `8.1_1` on `PATH` (`--enable-gpl --enable-version3`, no `--enable-libzimg`, 481 filters) and the binary bundled by [imageio-ffmpeg 0.6.0](https://pypi.org/project/imageio-ffmpeg/) (`ffmpeg-macos-aarch64-v7.1`: `--enable-gpl`, no `--enable-version3`, `--enable-libzimg`, 484 filters).

---

## Adversarial review (2026-09-02)

An independent reviewer re-ran every command this note cites, fetched the licence texts it names, and benchmarked the two things it left unverified. Findings are appended, not merged; the author's text above is unchanged.

### Confirmed, first-hand

- **The bundled ffmpeg (§3.4, claim 1).** Re-ran `imageio_ffmpeg.get_ffmpeg_exe()` under CPython 3.12.12 from `$PP` → `…/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1`; `-version` reports `ffmpeg version 7.1`, configuration containing `--enable-gpl --enable-libx264 --enable-libx265 --enable-libvidstab --enable-libzimg --enable-postproc` and **no** `--enable-version3`. GPL-2.0-or-later is the right reading. `imageio-ffmpeg` 0.6.0, `moviepy` 2.2.1 confirmed installed.
- **The two-binary finding (§3.4, claim 2), exactly.** 484 filters bundled / 481 on `PATH`; only-bundled = `ass drawtext pp subtitles vidstabdetect vidstabtransform zscale`; only-`PATH` = `colordetect premultiply_dynamic transpose_vt yadif_videotoolbox`. PATH build is homebrew 8.1_1, `--enable-gpl --enable-version3`, no `--enable-libzimg`, `zscale` absent. Rule **L7 stands.**
- **`nw.transforms.cache_key` (§1.2d) verbatim**, including the "spends money or CPU **without** going through fal (ElevenLabs TTS, an ffmpeg extraction)" sentence; `braidio/transforms/_segment.py` line 1 does say "A **local-render** Transform"; `_common.cached_output` does say "one convention, not one per genre". `python -c "import nw; ..."` → `cache_key` and `cached_output` are **not** in `dir(nw)`; `register_transform`/`Transform`/`BaseTransform` are.
- **`burns` deps** (`numpy`, `moviepy`, `pillow`) and `moviepy`'s hard `imageio_ffmpeg>=0.2.0`. `looks → burns` is correctly forbidden.
- **`paces` → `mixing`** at `derivation.py` 694 / 889 / 923 and `tests/test_vertical_slice.py` 105 / 150, with `mixing>=0.0.39` in `[media]`. *Additionally*: `derivation.py:363` does `from mixing.util import ffmpeg_exe`, which strengthens §3.3 further. `mixing.util.ffmpeg_exe` prefers `imageio_ffmpeg`; `video_util.py` imports moviepy at module top. **§3.3's PORT-not-MOVE verdict is correct.**
- **The licence facts carried forward (claim 8), now verified independently.** AnimeGANv2 has **no LICENSE file** (`gh api repos/... .license` → `null`); its README §License reads *"freely available to academic and non-academic entities for non-commercial purposes"*. White-box Cartoonization likewise has no LICENSE file; README: *"Licensed under the CC BY-NC-SA 4.0 … Commercial application is prohibited."* `ultralytics` 8.4.75 metadata `License: AGPL-3.0`. All three confirmed. **Nuance worth carrying:** the two cartoon models are not merely "non-commercial", they grant **no licence at all** in-repo — which lands them in `looks`' *unknown → refusal* branch, not its *field-of-use* branch.
- **`eq` is GPL-only, from primary source.** `configure` at tag `n8.1` line 4128: `eq_filter_deps="gpl"`. 33 `*_filter_deps=…gpl…` entries total. §5.1's argument holds.
- **muvid#66 and nw#29** read verbatim; open as of 2026-09-02. nw open issues are exactly #55 #44 #29 #9 #5, so §1.3's "no issue names the CPU-invisibility gap" is right.
- **`burns.backends`** docstring, the `RenderBackend` signature, and "an FFmpeg `zoompan` fast-path" as the declared second backend.

### Newly measured — the ffmpeg fast path IS faster (§4.4, §7 item 5, resolved)

3840×2160 source, 5 s, 30 fps, 1920×1080 out, push-in:

| | wall |
|---|---|
| `burns.ken_burns_video(..., backend="pillow")` | **22.49 s** |
| ffmpeg one-pass ramp + `scale`, `libx264` | **2.28 s** (16.0 s user; multithreaded) |

Both 150 frames at 1920×1080/30. **~9.9× wall-clock.** The inherited claim is now measured and holds.

### REFUTED — three findings, one of them fatal to the §4 implementation story

**1. FATAL: an ffmpeg `crop` cannot ramp its SIZE, so a "keyframed-`crop` compiler" cannot compile a zoom.** `crop`'s `w`/`h` are evaluated once at filter configuration; only `x`/`y` are per-frame. Measured on a concentric-ring source (a 2× zoom would be unmistakable):

```
crop=w='iw*(0.5+0.5*min(t/5,1))':h='...':x='(iw-out_w)/2':y='...',scale=960:540
  → PATH 8.1  : mean |frame0 − frame149| = 0.002    (no zoom; encoder noise)
  → bundled7.1: mean |frame0 − frame149| = 0.0019   (no zoom)
crop w/h ramp with no scale → output stream is 3840×2160, i.e. w/h froze at full size.
control, x-only ramp (muvid's shape) → 2.555  (pan works, per-frame, as muvid relies on)
```

This refutes, in order: §4.4's "shape of the adapter … hands them to `looks` for compilation into a `crop`+`scale` fragment"; §4.3's table row *"muvid#66's in-shot punch-in — executed as a ramped `crop` in a `-vf`"*; §3.1's "a keyframed-`crop` compiler taking `(t, Rect)` pairs"; and §4.3's productive corollary *"over video input the execution is an ffmpeg `crop` with ramped expressions"*. **Rule G and "burns stays separate" survive** — they rest on the dependency direction, which is confirmed — but the mechanism that makes Rule G *productive* does not exist as described.

**2. `zoompan` is not the wrong filter — it is the only filter that zooms, and it works on video.** §4.4's warning propagates muvid's `_crop_filter` docstring beyond its evidence. Measured on a real 150-frame 5 s video input:

```
zoompan=z='min(1+0.006*on,1.9)':d=1:x=…:y=…:s=960x540:fps=30
  → 150 frames out of 150 in, duration 5.000000, r_frame_rate 30/1  (NO frame duplication)
  → mean |f0−f74| = 103.2, |f74−f149| = 109.7  (a real zoom)
```

The duplication muvid warns about comes from the **default `d=90`**, not from video input. And "no `t` at all" is literally true but materially misleading: `in_time` (seconds) is accepted and works on **both** binaries — `z='min(1+0.18*in_time,1.9)'` gives first-vs-last diff 103.7, 150 frames, 5.000 s. `zoompan_filter_deps="swscale"` in `configure` n8.1 — **not** GPL-gated. muvid's docstring should be corrected too; note 11 inherited it rather than testing it.

**3. `illustration` and `walkthru` do NOT get the fast path for free.** §3.1's table row (*"Zero code change — they get the ffmpeg fast path for free"*) and §4.5 (*"by selecting a backend name"*) are both wrong, and mutually inconsistent. `burns/backends.py`'s own docstring says the multi-panel renderer *"deliberately does not go through this registry"*, and `inspect.signature` confirms: `ken_burns_film(panels, saveas, fps, audio_path, codec, audio_codec, **write_kwargs)` — **no `backend` parameter**, versus `ken_burns_video(..., backend=…)`. `illustration/video.py:_default_render` returns `ken_burns_film`; `walkthru`'s `render_target` defaults to `reelee.kenburns_video.default_film_renderer`. Only `reelee/transforms/panel_to_clip.py` reaches `ken_burns_video`. A `RENDER_BACKENDS` entry reaches **one** call site in the federation, not three.

### Understated, not wrong

- **§2.3 / §3.4 name the wrong (and milder) GPL route for `mixing`.** `mixing` hard-declares `opencv-contrib-python`. `cv2.abi3.so` **dynamically links** `libavformat/libavcodec/libswscale/libavutil` from `cv2/.dylibs/`, and those carry the embedded configuration `--prefix=/opt/homebrew/Cellar/ffmpeg/7.1.1_3 … --enable-gpl --enable-version3 … --enable-libx264 --enable-libx265 --enable-libopencore-amrnb --enable-frei0r`; `libavcodec` links `@loader_path/libx264.164.dylib` and `libx265.215.dylib`. That is **GPL-3.0-or-later** (version3 + gpl), it is **linking**, not shelling out, and the wheel metadata says `License: Apache 2.0`. Note 06 §7 has this and escalates it correctly; note 11 does not carry it, so §2.3's "through `moviepy → imageio-ffmpeg`" reads as the whole exposure when it is the milder half. This matters directly for `looks`, whose first shipped look needs `cv2.pyrMeanShiftFiltering`.
- **§3.2's "one splice in `_render_part`" is two splices.** The same `vf` template appears at `assemble.py:267` (`_render_part`) and again at `:356` (`_norm`, the transition A/B path), and a look must land identically on both or a cut's two sides disagree.
- **muvid's `_crop_filter` cannot express a zoom even in its own EDL**, and worse, its moving-window predicate is `abs(e.x−c.x)<1e-9 and abs(e.y−c.y)<1e-9` — it never inspects `w`/`h`, so a `crop_end` that changes only size is silently classified as *static* and compiled at the start window. §3.1's **Small** effort estimate for muvid does not cover the muvid#66 half.

### Design objections

- **Rule N (§5.3) misclassifies `looks`' own colour work.** Note 05's `ColorContract` conform is a *normalisation* whose target is **external and fixed** (a delivery spec) and which needs exactly one clip's probe. Under Rule N it must either be labelled `intent="style"` — a lie — or be forced through `resolve_across`, which demands a set it does not need. The honest axis is *where the target comes from* (external vs the set's own distribution), which §5.3 states correctly one paragraph earlier and then collapses onto the style/grade word pair. Either drop `intent` and let the **resolver** be the only distinction, or value it `external | set_relative`.
- **§4.3's Rule G table lists `cropdetect` as a `looks`-owned effect, which rules L3/L12 forbid.** `cropdetect` measures — it prints to the log and crops nothing — so performing it is a subprocess and a measurement. It belongs on the `Probe` side of the seam. (It is also `cropdetect_filter_deps="gpl"`, verified.)
- **The body schema in `nw` on day one contradicts the note's own rule of three.** §2.2 puts the Transform in `muvid` until a second consumer appears, but puts the migration-required body schema in the shared package immediately. Co-locating both in `muvid` and graduating them together is cheaper and keeps the artefact that *needs a migration* out of the shared package until something else reads it.
- **The `looks`-in-the-loop value for a `burns` ffmpeg backend is thinner than §4.5 claims**, now that the filter is known to be `zoompan`: it is not GPL-gated, so tier resolution decides nothing here, and the compiled fragment is a handful of expressions. The backend is still worth building (9.9× measured) — the open question is whether it needs to route through `looks` at all, which §4.5 does not ask.

### One thing not checked by either party

`burns.RenderBackend` takes `img_np: np.ndarray` — **already-decoded pixels**. An ffmpeg backend registered there must first write that array back out (temp PNG or a rawvideo pipe) before ffmpeg can start, which the 2.28 s benchmark above does not include (it read a PNG from disk). The measured speedup is real for the `looks`/muvid path, where the source is already a file; for `burns`' registry it is bounded by a re-encode the contract forces.
