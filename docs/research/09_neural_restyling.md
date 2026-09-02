# Neural restyling with commercially-usable licences — 2026 state of the art

**Date: 2026-09-02**
**Scope:** whether `looks` should have a neural backend in v1. Surveys neural video restyling filtered hard by commercial usability, treats code licence and weights licence as separate facts, and tests every candidate against a second bar — temporal stability — that is measured here rather than assumed.

## Verdict (stop here if you only read one paragraph)

**No. Ship no neural backend and declare no neural seam.** Both known kills are confirmed from the licence text itself, and the field behind them is worse than the brief suggested: neither AnimeGANv2 nor White-box Cartoonization is merely "non-commercial", and the canonical fast-style-transfer repo (`jcjohnson/fast-neural-style`, 4.4k stars) is *also* non-commercial, as are Rerender-A-Video and FRESCO (S-Lab License 1.0). What *is* commercially clean divides cleanly by where it runs: the best-licensed 2026 local video-to-video model, ByteDance's **Bernini-R** (Apache-2.0, released 2026-06-02), requires **8 GPUs via `torchrun`** for its video tasks — only its image tasks are single-GPU — so it is not a laptop backend at any licence tier; and the one neural stylizer that is both commercially clean and CPU-runnable, the **ONNX Model Zoo `fast_neural_style` set (BSD-3-Clause code and weights)**, is locked to a **fixed 224×224 input** and, measured here across 3 clips × 4 styles, amplifies frame-to-frame change to **1.20×–2.82× the source's own** where the shipped Que Calor chain sits at **0.70×**. It fails the flicker bar it was the last candidate for. The decisive structural finding is that the licence vocabulary `looks` is assembling — FFmpeg's `gpl / nonfree / version3` — **cannot express any of the four things that actually bind a neural effect**: the code/weights split, a non-commercial tier (distinct from `nonfree`, which means *unredistributable*), patent encumbrance (Ebsynth is public-domain code inside an Adobe PatchMatch patent live until **2030-08-16**), and whether the licence binds *us* or the host. The most-downloaded model carrying Hugging Face's `video-to-video` tag, **MiniMax-H3** (5,532,597 downloads), publishes a Community License whose "Applicable Territory" is **worldwide excluding the European Union, the United Kingdom, South Korea and the United States** — so for a US or EU product it is not licensed at all, at any revenue, and nothing in its metadata (`license: other`) says so. That single row is the argument for refusal-by-default in one line. The hosted route is real and cheap (fal.ai's `decart/lucy-restyle`, video-to-video at $0.01 per source second) but it is **`falaw`'s job, not `looks`'** — and falaw today has **zero** `video_to_video` records among its 40 models and its licence ledger (falaw#16) is filed and unbuilt. What `looks` should declare instead are two things that are not stubs because both already have an implementation to point at: **`Effect.temporal`**, a measured temporal class whose instrument is the 12-line numpy metric already used to validate the flagship look, and a **licence record carrying the four fields FFmpeg's vocabulary omits**, whose eventual replacement is falaw#16's `(model, backend)` ledger, specified in detail and citable today.

---

## 1. The two known kills — confirmed, from the licence text

Both verdicts hold, and both are **worse** than "non-commercial licence": neither repository has a `LICENSE` file at all. The GitHub API returns `license: null` for both (checked 2026-09-02), so the only licence statement is prose in the README. A tool that reads packaging metadata sees nothing.

**AnimeGANv2** [1] — README §License, verbatim:

> This repo is made freely available to academic and non-academic entities for non-commercial purposes such as academic research, teaching, scientific publications. Permission is granted to use the AnimeGANv2 given that you agree to my license terms. Regarding the request for commercial use, please contact us via email to help you obtain the authorization letter.

**White-box Cartoonization** [2] — README §License, verbatim:

> Copyright (C) Xinrui Wang All rights reserved. Licensed under the CC BY-NC-SA 4.0 license (https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode). Commercial application is prohibited, please remain this license if you clone this repo

Two extensions of the finding, both of which would trap someone who checked only the obvious repo:

- **AnimeGANv3 carries the identical clause** [3] — the successor is not an escape. Its README §License repeats the AnimeGANv2 wording word for word, and it too has no `LICENSE` file. It is the actively-maintained one (last push 2025-08-23) and the one people reach for.
- **`bryandlee/animegan2-pytorch` declares MIT and is still unusable commercially** [4]. This is the port most people actually run (4.4k stars, `torch.hub`-loadable), and GitHub reports its licence as MIT — but its README §"Weight Conversion from the Original Repo" instructs you to clone `TachibanaYoshino/AnimeGANv2` and run `convert_weights.py`. The MIT covers the *conversion code*; the weights it produces are derived from non-commercial weights. **This is the code/weights split in its purest form, and a metadata scan gets it exactly backwards.**

White-box Cartoonization's CC BY-NC-SA 4.0 carries a second problem beyond `NC`: **`SA` is copyleft for media.** Even a permitted non-commercial use obliges you to license the adaptation under the same terms. A "non-commercial" tier that does not also record share-alike is under-describing this row.

---

## 2. What is commercially usable, as of 2026

Every row below was checked at the primary source on 2026-09-02 — the Hugging Face model API's `cardData`, the licence file in the repository, or the GitHub licence API — never from a blog or an aggregator. Where the two disagree, both are shown, because the disagreement is the finding.

### 2.1 The rule this table exists to enforce

**Code licence and weights licence are separate facts and disagree constantly.** ControlNet's code is Apache-2.0 while its v1.1 weights card says `openrail`; `animegan2-pytorch` is MIT over non-commercial weights; InstantStyle has *no licence file at all* and defers its checkpoints to IP-Adapter's. A single `license` column is not a description of a neural effect — it is a guess.

### 2.2 Image models (the per-frame stylizer, whatever wraps it)

| Model | Code licence | Weights licence | Commercial? | CPU? | Source |
|---|---|---|---|---|---|
| **FLUX.1-schnell** | Apache-2.0 | **Apache-2.0** | **Yes, unconditionally** | Impractical (12B) | [5] |
| FLUX.1-dev | Apache-2.0 (inference repo) | FLUX.1 [dev] Non-Commercial License | **No** for the model; **yes** for Outputs | No | [6] |
| FLUX.1-Kontext-dev | — | `flux-1-dev-non-commercial-license` | **No** | No | [7] |
| FLUX.2-dev | — | `flux-non-commercial-license` | **No** | No | [8] |
| **Qwen-Image-Edit** | Apache-2.0 | **Apache-2.0** | **Yes** | Impractical (20B) | [9] |
| SD 1.5 | — | CreativeML OpenRAIL-M | Yes, with use restrictions | Slow but possible | [10] |
| SDXL base 1.0 | — | OpenRAIL++-M | Yes, with use restrictions | Slow | [11] |
| SDXL-Turbo | — | **card says `sai-nc-community`; the repo's `LICENSE.md` is the Stability AI Community License** | **Contradictory — see below** | Slow | [12] |
| SD 3.5 (large / medium) | — | Stability AI Community License | Yes **under $1M annual revenue**; licence *terminates* above it | No | [13] |
| SDXL-Lightning | — | OpenRAIL++ | Yes, with use restrictions | Slow | [14] |
| LCM-LoRA-SDXL | — | OpenRAIL++ | Yes, with use restrictions | Slow | [15] |
| ControlNet | Apache-2.0 | `openrail` (v1.1 card) | Yes, with use restrictions | Slow | [16] |
| IP-Adapter | Apache-2.0 | Apache-2.0 (card) | Yes | Slow | [17] |
| InstantStyle | **no LICENSE file** | "follows the license in IP-Adapter" (README disclaimer only) | **Unknown → refuse** | Slow | [18] |
| StyleAligned | Apache-2.0 | training-free (no weights of its own) | Yes for the method | Depends on base model | [19] |

**Three things in that table deserve to be pulled out.**

**SDXL-Turbo's metadata contradicts its own licence file, and the direction is unusual.** The Hugging Face card declares `license: other, license_name: sai-nc-community` — a *non-commercial* marker — while the `LICENSE.md` actually sitting in the repository is the **Stability AI Community License Agreement, "Last Updated: July 5, 2024"**, which grants a commercial licence free under $1M annual revenue [12]. Stability's own licence page also lists SDXL Turbo among the Community-licensed core models [13]. The reelee-web house rule is *the licence text is the authority, the metadata field is not* — that rule was written for the dangerous direction (a permissive field over copyleft text), and this is the same rule firing in the safe direction. **Either way the metadata is wrong, and either way an automated field scan produces the wrong answer.**

**The Stability Community License terminates rather than upgrades.** §3 is explicit: "If at any time You or Your Affiliate(s) … generate more than USD $1,000,000 in annual revenue … **any licenses granted to You under this Agreement shall terminate as of such date**" [12]. It is not a price tier you graduate into; it is a cliff. A ledger row that records only `commercial_use: allowed` is materially misleading for this family.

**"Unknown" is not rare.** InstantStyle — 2k stars, widely deployed — ships **no licence file whatsoever**, and the only statement anywhere is a README *disclaimer* pointing at another project's checkpoints [18]. Under any defensible reading that is all-rights-reserved code. It is exactly the row a "refuse on unknown" rule exists for.

### 2.3 Video models (2025–2026 arrivals)

| Model | Weights licence | Commercial? | Runs where | Source |
|---|---|---|---|---|
| **Bernini-R** (ByteDance, 2026-06-02) | **Apache-2.0** | **Yes, unconditionally** | **8 GPUs (`torchrun`) for `v2v`; H100 recommended**; only `t2i`/`i2i` are single-GPU | [20] |
| **Wan 2.2** (T2V-A14B, TI2V-5B) | **Apache-2.0** | **Yes, unconditionally** | Single GPU (5B variant) | [21] |
| **Wan2.2-Animate-14B** | **Apache-2.0** | **Yes** | GPU | [22] |
| **Mochi-1-preview** | **Apache-2.0** | **Yes** | GPU | [23] |
| **SeedVR2-3B** (ByteDance, restoration) | **Apache-2.0** | **Yes** | GPU | [24] |
| CogVideoX-2b | **Apache-2.0** | **Yes** | GPU | [25] |
| CogVideoX-5b | CogVideoX License | Registration required; free commercial use **under 1M visits/month** | GPU | [26] |
| HunyuanVideo | Tencent Hunyuan Community | Conditional | GPU | [27] |
| LTX-Video (0.9.6+) | LTXV Open Weights License 0.X, dated **2025-04-15** | RAIL-style use restrictions; **no revenue threshold in this version** | GPU | [28] |
| LTX-2.3 / LTX-2.5 | LTX-2.x Community License, dated **2026-08-11** | Free below **$10,000,000** annual revenue; above it a paid Commercial Use Agreement is **required** | GPU | [29] |
| **MiniMax-H3** | MiniMax H3 Community License, dated **2026-08-02** | **Territorially excluded — see below** | GPU | [30] |

**MiniMax-H3 is the row that should be quoted in `looks`' own documentation.** It is the most-downloaded model carrying Hugging Face's `video-to-video` tag (5,532,597 downloads, observed 2026-09-02). Its licence opens: "The scope of this License Agreement is expressly limited to the 'Applicable Territory'", and defines, verbatim:

> 3. "Applicable Territory" means worldwide, excluding the Excluded Territories.
> 5. "Excluded Territories" means the European Union, the United Kingdom, the Republic of Korea and the United States of America.

For a product sold in the US or the EU **there is no licence at all** — not a restricted one, not a revenue-gated one. And there is a $20M revenue clause *and* a mandatory attribution clause ("You shall prominently display 'MiniMax H3' on the user interface") layered on top for everyone else [30]. The Hugging Face metadata for this says `license: other`. **A field scan, a revenue check and a copyleft check all pass this model. Only reading the text catches it.**

The recurring shape across the 2026 arrivals is that the *good* licences are genuinely good — Wan 2.2, Bernini-R, Mochi-1, SeedVR2 and CogVideoX-2b are plain Apache-2.0 with no thresholds, no territories and no attribution obligations — and the *conditional* ones are conditional in four mutually-incompatible ways (revenue, monthly visits, monthly active users, territory). No single scalar tier orders them.

### 2.4 The classic style-transfer route — and the one clean CPU option

This is where the survey found its only candidate that clears the licence bar *and* runs on a laptop, so it is worth the detail.

| Route | Code licence | Weights licence | Commercial? | CPU? | Source |
|---|---|---|---|---|---|
| Gatys optimisation (`jcjohnson/neural-style`) | MIT | none (uses VGG-19) | Code yes; VGG-19 weights **unverified** | Yes, very slow | [31] |
| **`jcjohnson/fast-neural-style`** | **no LICENSE file**; README: *"Free for personal or research use; for commercial use please contact me"* | same | **No** | Yes | [32] |
| `pytorch/examples/fast_neural_style` | **BSD-3-Clause** | trained by the user | **Yes** | Yes | [33] |
| **ONNX Model Zoo `fast_neural_style`** | Apache-2.0 (repo); **the model directory declares `SPDX-License-Identifier: BSD-3-Clause`** | **BSD-3-Clause** | **Yes** | **Yes — 0.07 s/frame at 224×224 on this machine** | [34] |
| AdaIN (`naoto0804/pytorch-AdaIN`) | MIT | derived from a VGG encoder; **unverified** | Code yes | Yes | [35] |
| Magenta arbitrary style transfer | Apache-2.0 (`magenta` repo, **archived 2026-01-06**) | Kaggle Models; licence field **not exposed by the API — unverified** | Probably, **unconfirmed** | Yes | [36] |

**The canonical repo is the one that is unusable.** `jcjohnson/fast-neural-style` is the 4.4k-star reference implementation everybody links to, and it is non-commercial by README prose with no `LICENSE` file [32] — the same failure shape as AnimeGANv2. The clean substitute is one hop away and almost nobody names it: the ONNX Model Zoo's copies were converted from **`pytorch/examples`**, which is **BSD-3-Clause**, and the model directory's README carries an explicit `SPDX-License-Identifier: BSD-3-Clause` header and a `## License / BSD-3-Clause` section [34]. **Code and weights are both BSD-3-Clause, and they run through `cv2.dnn.readNet` or `onnxruntime` on CPU.** OpenCV is Apache-2.0 and the flagship Que Calor look already requires it for `pyrMeanShiftFiltering`, so this route adds **no dependency `looks` does not already have** — which is precisely the test the house's seam rule applies.

That makes it the only serious candidate, so §3 tests it rather than trusting it.

Two caveats recorded honestly. The models were trained on **COCO 2014** [34]; the copyright status of training data is a separate and unresolved question everywhere in this survey and is **not** addressed by the BSD-3-Clause grant on the weights. And the set is five fixed styles (`mosaic`, `candy`, `udnie`, `rain-princess`, `pointilism`) — it is not promptable, so it can never be the general "restyle to X" the word *neural* implies to a caller.

---

## 3. The flicker bar — measured, not assumed

The house finding is that the shipped Que Calor chain is frame-independent by construction and therefore cannot flicker, and that per-frame neural stylisation is exactly the failure mode. The first half is established. The second half was an expectation, so it was tested here against the one candidate that clears the licence bar.

**Instrument.** The metric is the one already in `~/Downloads/que_calor/work/style/flicker.py` — the mean absolute inter-frame difference across channels (written `mean-abs-delta` below), plus its 99th percentile, each reported as a **ratio to the same measure on the unstyled source**. Self-normalising, so a busy clip and a still clip are comparable. Reproduction, in full — `d = [np.abs(a.astype(np.int16) - b.astype(np.int16)).mean(axis=2) for a, b in zip(seq, seq[1:])]`, then `np.mean([x.mean() for x in d])` and `np.mean([np.percentile(x, 99) for x in d])`, each divided by the same two numbers computed on the untouched source frames. Inputs are `~/Downloads/que_calor/footage/Que Calor 0{1,2,3}.mp4`, 2 s each from 20 s / 15 s / 10 s, all frames resized to **224×224** because the ONNX models are fixed-shape and every arm must see identical input. `onnxruntime` 1.23.1, `opencv-contrib-python` 4.13.0, ffmpeg 8.1, CPU only.

**Per-clip results.** Each cell is `mean-abs-delta ratio to source / p99 ratio to source`; the last column averages the mean-abs-delta ratio over the three clips.

| Arm | QC01 | QC02 | QC03 | averaged |
|---|---|---|---|---|
| SOURCE | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00× |
| **Que Calor chain** (meanshift → `lut3d` → posterise) | 0.61 / 1.15 | 0.91 / 1.31 | 0.56 / 1.00 | **0.70×** |
| LUT only (pure per-pixel baseline) | 1.07 / 1.13 | — | — | ~1.07× |
| neural `mosaic-9` | 1.69 / 1.73 | 2.77 / 2.21 | 4.02 / 3.27 | **2.82×** |
| neural `candy-9` | 1.25 / 1.43 | 2.13 / 1.71 | 3.53 / 2.59 | **2.30×** |
| neural `rain-princess-9` | 1.16 / 1.11 | 1.73 / 1.11 | 3.07 / 1.88 | **1.99×** |
| neural `udnie-9` | 0.66 / 0.99 | 0.89 / 0.75 | 2.06 / 1.64 | **1.20×** |

**Four readings, in order of how much they matter.**

**The excess is added by the model, not tracked from the source, and that is flicker's signature.** Look at `mosaic-9`'s *absolute* mean-abs-delta: 34.97, 16.25, 27.02 across the three clips, while the source's own falls 20.74 → 5.87 → 6.72. The stylizer's temporal energy is roughly independent of how much the source is actually moving. That is why the ratio climbs from 1.69× on the busiest clip to **4.02× on the calmest** — the calmer the shot, the more visible the flicker, which is the opposite of what a well-behaved effect does and exactly what an editor notices on a held frame.

**The pure per-pixel baseline lands where the theory says it must.** LUT-only measures 1.07× / 1.13×. A stateless per-pixel map reproduces the source's own temporal change and adds essentially nothing. That is the control, and it passing is what makes the neural numbers interpretable rather than an artifact of the metric.

**The Que Calor chain is not merely neutral — it *suppresses* temporal change**, 0.70× on average and 0.56× on the calmest clip, because mean-shift clustering plus posterisation collapses small frame-to-frame variation into the same flat region. Its p99 sits slightly above 1.0 (1.00–1.31×), which is the honest cost: where a pixel does cross a posterisation boundary the jump is larger than the source's. That is a *banding* artifact, not flicker, and it is bounded.

**One honest exception, and it does not rescue the route.** `udnie-9` averages 1.20× and is at or below source on two of three clips. So "all per-frame neural stylisation flickers" is too strong as stated — some styles are gentle. But `udnie` still reaches **2.06× on the calmest clip**, the direction is the same in every style, and the property is a per-style accident rather than a guarantee. The Que Calor chain's stability is *structural* — no temporal state, one fixed LUT — and a structural guarantee is a different kind of object from a favourable measurement on four checkpoints.

**A second, independent disqualification.** Both opset variants (`-8` and `-9`) of every ONNX Model Zoo `fast_neural_style` model declare `input1: [1, 3, 224, 224]` — **fixed**, not dynamic (verified against both files, 2026-09-02). There is no resolution at which this is a video effect without re-exporting the models from `pytorch/examples` yourself. That is a real option, it stays BSD-3-Clause, and it is a training-and-export project, not a backend.

**So: is there a neural option that clears both bars today? No.** The licence-clean CPU option fails the flicker bar by 1.20×–2.82× and is locked to 224×224. The licence-clean 2026 video models that would clear the flicker bar natively (Bernini-R, Wan 2.2) need a GPU cluster or at minimum a serious GPU. Nothing occupies the intersection.

---

## 4. Temporal-consistency techniques, and what each costs

The reason no local neural option clears the flicker bar is not a gap in the literature — it is that every technique that closes it costs something `looks` cannot pay.

| Technique | Representative work | Code licence | Commercial? | What it costs |
|---|---|---|---|---|
| **Frame-independence by construction** | the Que Calor chain | n/a | n/a | **Nothing.** Measured 0.70×. This is what `looks` already has |
| Post-hoc temporal filtering | ffmpeg `deflicker`, `tmix`, `tblend`, `atadenoise`, `minterpolate` | LGPL-safe in n8.1 (verified in `configure`) [37] | Yes | Cheap, but it blurs real motion as readily as flicker; `hqdn3d`, `owdenoise` and `vaguedenoiser` are **GPL-gated** [37] |
| Optical-flow blending (model-free) | FastBlend | Apache-2.0 (`sd-webui-fastblend`; the code was **removed** from current DiffSynth-Studio) [38] | Yes | Needs flow estimation per frame; the standalone repo has not been pushed since 2024-08-14 |
| Blind deflickering with a learned atlas | All-In-One-Deflicker (CVPR 2023) | Apache-2.0 [39] | Yes | Per-video optimisation; needs a GPU; weights are a separate download whose licence is **unverified** |
| Cross-frame attention | Text2Video-Zero | CreativeML Open RAIL-M [40] | Yes, with use restrictions | Reduces but does not remove flicker; still a diffusion model per frame |
| Attention-map fusion | FateZero | MIT [41] | Yes (code) | Inference-time cost; base-model weights carry their own licence |
| Token/feature propagation | TokenFlow | MIT [42] | Yes (code) | Needs the whole clip in memory; base-model licence still applies |
| Canonical-field decomposition | CoDeF | **MIT** [43] | Yes (code) | **Per-video training** — minutes to hours of GPU per clip |
| Grid/noise-shuffled batching | RAVE | MIT [44] | Yes (code) | GPU; quality varies with motion magnitude |
| Flow-guided diffusion | Rerender-A-Video | **S-Lab License 1.0 — non-commercial** [45] | **No** | — |
| Flow + attention correspondence | FRESCO | **S-Lab License 1.0 — non-commercial** [46] | **No** | — |
| Patch-based keyframe propagation | **Ebsynth** | **public domain code, PatchMatch patented** [47][48] | **See below** | The classic answer, and the trap |
| Video-native diffusion | Bernini-R, Wan 2.2 | Apache-2.0 [20][21] | **Yes** | 8 GPUs for `v2v` (Bernini) or a serious single GPU (Wan 5B) |

**Ebsynth is the most instructive row in this note after MiniMax-H3.** Its README says, verbatim: "The code is released into the public domain. You can do anything you want with it." And then, in the same section: "However, you should be aware that the code implements the PatchMatch algorithm, which is patented by Adobe (U.S. Patent 8,861,869). Other techniques might be patented as well. It is your responsibility to make sure you're not infringing any patent holders' rights by using this code." [47] Google Patents confirms US8861869B2 — *Determining correspondence between image regions* — priority **2010-08-16**, granted 2014-10-14, current assignee **Adobe Inc**, status **Active**, anticipated expiration **2030-08-16** [48].

**A copyright tier of `public-domain` is the most permissive value any licence vocabulary has, and it is the wrong answer for this row.** No copyright-shaped field — not FFmpeg's `gpl/nonfree/version3`, not SPDX — can express "you may copy this freely and may not practise it commercially in the US until 2030". `looks`' record needs a patent field, and Ebsynth is the reason.

**The pattern across the whole table:** the techniques that are permissively licensed (CoDeF, TokenFlow, RAVE, FateZero — all MIT) are *methods over a base model*, so their MIT grant settles nothing about the diffusion weights they drive; and the two techniques purpose-built for exactly this job (Rerender-A-Video, FRESCO — from the same lab) are both non-commercial. **The licence-clean half of the field and the flicker-solving half of the field barely intersect, and where they do (Bernini-R, Wan 2.2), the cost is a GPU cluster.**

---

## 5. The hosted route — and where the seam goes

**Hosted video restyling is real, cheap, and already reachable.** fal.ai serves `decart/lucy-restyle`, a video-to-video model taking `prompt` + `video_url`, output 720p, marked "Commercial use" on the model page [49]. Reported pricing is **$0.01 per second of source video** — about $6 for a ten-minute clip — though the number is from fal's marketing and guide pages rather than the API reference, which quotes no price; treat the figure as **secondary-sourced**. Vendor copy claims it preserves "motion, timing, and narrative structure"; **that temporal claim is unverified here** — no clip was run through it, and given §3 the claim is exactly the one that would need measuring before it is repeated.

**It is not a `looks` backend, and the federation has already decided why.** The standing layering rule is `lacing → nw → falaw.Plan → backends`, and nothing above `falaw.Plan` may know which backend runs. A hosted restyle is a paid vendor call with a cost, a cache key and a terms-of-service position — which is falaw's entire subject matter and none of `looks`'.

**falaw has already filed the exact mechanism, and it is the right home.** falaw#16 [50] specifies a per-`(model, backend)` ledger with `license`, `commercial_use`, `third_party_tenancy`, `provenance_constraint`, `source_url`, `observed_on` — and, load-bearing, **`license_binds_us: yes | no (host holds it) | unknown`**. Its stated rationale is precisely the split this survey kept running into: "the **backend** decides whether an upstream weights licence flows through to us. A model invoked through a hosted API is governed by that host's terms; the same weights self-hosted on our own GPU bind us directly. Same model id, different legal position." That issue also states the rule `looks` shares — **`unknown` is a refusal, not a warning** — and names FLUX.1-dev as its worked example, which this survey independently confirms is the single most common trap in the field [6]. The issue is **OPEN and unbuilt** as of 2026-09-02.

**Two facts bound how soon this matters.** falaw's model registry holds **40 records** across `image`, `image_edit`, `image_to_video`, `text_to_video`, `upscale`, `lipsync`, `music`, `tts`, `avatar`, `llm`, `background_removal`, `training`, `voice_clone`, `audio` — and **no `video_to_video` category at all** (inspected 2026-09-02). So even the hosted route is a future falaw integration, not something `looks` can call today. And nw#29 [51] carries the measured registry lesson from the ComfyUI programme — of ComfyUI's node registry, **85.5% of packs declare no machine-readable licence, the `license` field has 76 distinct raw spellings, and 59% point at a file rather than naming a licence** — with the rule that follows: *any registry field that will later be queried for compliance must be a validated enum, enforced at publish time.* That rule applies to `looks`' tier field on day one, and this survey is a second, independent demonstration of it: `other`, `NOASSERTION`, `null`, README prose and a contradicted `license_name` were the observed values for five of the most-deployed models in the field.

**Where the seam goes, concretely.** `looks` names the effect; `falaw` owns the model, the price and the terms. The mechanism already exists and needs no invention: muvid's `VisualPlan` escape hatch — *a backend that returns a rendered path rather than an ffmpeg filter chain* — is the shape. A future `looks` effect named for a neural restyle should compile to a **request**, handed outward, that a caller routes to falaw. It must not open a socket, and it must not know the model id. That is the ComfyUI ruling applied one layer up, and it costs nothing to honour now.

---

## 6. Recommendation

**Ship no neural backend in v1, and do not declare a neural seam either.**

The house rule is that a declared seam "defaults to the strongest implementation that needs no new dependency, and is declared only when its eventual replacement already exists somewhere you can point at." A neural seam fails the second half of that test, and the failure is not close. The eventual replacement — a local neural restyler that is commercially clean *and* temporally stable *and* runnable on the hardware `looks` targets — **does not exist anywhere I can point at**. The best-licensed candidate on each axis fails the other: BSD-3-Clause `fast_neural_style` measures 1.20×–2.82× at 224×224; Apache-2.0 Bernini-R needs eight GPUs. Declaring the seam anyway would produce exactly the stub the rule exists to prevent, and it would be a stub with an implied promise attached.

**Declare these two things instead. Neither is a stub, because each has a working implementation to point at today.**

**(a) `Effect.temporal` — a declared temporal class on every effect.** The default for every ffmpeg-filter effect is `frame_independent`, which is a *structural* claim: no temporal state, so the effect cannot add temporal energy. Anything that cannot make that claim carries a **measured** amplification ratio instead, with the clip and metric that produced it. The implementation that needs no new dependency already exists — it is the twelve-line numpy metric in `flicker.py`, already used to validate the flagship look and re-run in §3 above to produce seven comparable rows. The eventual replacement is the same metric over more effects, which is why this is an ordinary field and not a seam. Two reasons this earns its place: it is the only field in the whole design that would have caught the `fast_neural_style` route *before* someone shipped it; and it is the one dimension of an effect that `looks` is uniquely positioned to know, because `looks` is the package that knows what an effect *is*.

**(b) A licence record carrying the four fields FFmpeg's vocabulary cannot express.** `looks` is right to steal FFmpeg's `gpl / nonfree / version3` tiers, its caller-declared ceiling and its `die`-not-warn semantics — that is the finding of note 01, and it holds. But that vocabulary was built for one artifact class (C libraries linked into one binary) and it is structurally unable to describe a neural effect. Four additions, each earned by a specific row in this survey:

| Field | Why | The row that forces it |
|---|---|---|
| **`code` and `weights` as separate licences** | They disagree constantly, and the disagreement runs in both directions | `animegan2-pytorch`: MIT code, non-commercial weights [4] |
| **a `non_commercial` tier, distinct from `nonfree`** | FFmpeg's `nonfree` means *unredistributable*. Non-commercial is a different axis: freely redistributable, commercially forbidden. Collapsing them loses the distinction that matters most commercially. Record share-alike separately too | AnimeGANv2 [1]; White-box (CC BY-NC-**SA**) [2] |
| **`patent_until`** | A copyright tier of `public-domain` is the most permissive value in any vocabulary and is still the wrong answer here | Ebsynth: public domain, PatchMatch patent live to 2030-08-16 [47][48] |
| **`binds_us`** | Whether a licence binds *us* or the host is decided by the backend, not the model | falaw#16's `license_binds_us`, already specified [50] |

Two further constraints on the record, both learned the hard way in §2: the tier must be a **validated enum** (nw#29's rule — the observed raw values in this survey included `other`, `NOASSERTION`, `null`, a README sentence, and a `license_name` contradicted by the file next to it [51]); and a conditional grant needs its condition *as data*, not as a boolean, because the four conditional licences here condition on four incompatible things — annual revenue (Stability $1M [12], LTX-2.x $10M [29], MiniMax $20M [30]), monthly visits (CogVideoX-5b, 1M [26]), monthly active users (HunyuanVideo [27]), and **territory** (MiniMax-H3, excluding the EU/UK/Korea/US [30]). `commercial_use: allowed` is false for a US company using MiniMax-H3 and false for a $2M-revenue company using SD 3.5, and only the condition field distinguishes them.

**One thing worth adding to the vocabulary now that is not neural at all.** ffmpeg 8.1's temporal filters split cleanly across the licence line: `deflicker`, `tmix`, `tblend`, `atadenoise`, `nlmeans`, `removegrain` and `minterpolate` are **LGPL-safe**, while `hqdn3d`, `owdenoise` and `vaguedenoiser` are **GPL-gated** [37]. If `looks` ever needs a post-hoc temporal repair at an LGPL ceiling, that substitution is already available and is the same shape as the `eq` → `colorlevels` rule that note 01 identified.

**And one deployed fact worth recording as a decision rather than discovering later.** `pip install burns` redistributes a GPL ffmpeg binary today, verified first-hand on this machine: `burns` 0.0.9 declares `moviepy` as a hard dependency; `moviepy` 2.2.1 declares `imageio_ffmpeg>=0.2.0`; and `imageio_ffmpeg` 0.6.0 ships `ffmpeg-macos-aarch64-v7.1` whose `-version` output reports `--enable-gpl --enable-libx264 --enable-libx265`. Execution is not linking, so the Python code is not infected — but this **is** redistribution, and it is the strongest possible argument for `looks`' zero-hard-dependency rule and its refusal to depend on `imageio-ffmpeg` or `av`.

---

## What could not be verified

Marked explicitly, because an unverified claim asserted as fact would be the worst output here.

- **Lucy Restyle's pricing and its temporal-coherence claim.** The $0.01/source-second figure comes from fal's guide and marketing pages, not the API reference, which quotes no price [49]. The claim that it "preserves motion, timing and narrative structure" is vendor copy; no clip was run through it in this session.
- **The Magenta arbitrary-style-transfer weights licence.** The `magenta` source repository is Apache-2.0 and was **archived 2026-01-06** [36]; TF Hub has been retired (`tfhub.dev` returns 404) and the Kaggle Models API for `google/arbitrary-image-stylization-v1` returns no licence field. The weights licence is **unverified**.
- **VGG-19 weights.** Gatys-style and AdaIN routes depend on VGG-19 features. The *code* licences are MIT [31][35]; the VGG-19 weights' own licence was not chased and is **unverified**. It is the same code/weights split as everywhere else in this note and should not be assumed clean.
- **All-In-One-Deflicker's pretrained checkpoints.** The repository is Apache-2.0 [39] but the README instructs a separate checkpoint download; those weights' licence is **unverified**.
- **The LTX-2.x $10M threshold's scope.** Verified in the `LICENSE-2_x` text dated 2026-08-11 [29]. The older LTXV Open Weights License 0.X (2025-04-15) governing LTX-Video 0.9.6+ contains **no** revenue threshold [28] — so a blog statement that "LTX requires a commercial licence above $10M" is version-dependent and wrong for the older weights.
- **Training-data provenance, for every model in this survey.** The BSD-3-Clause grant on the ONNX `fast_neural_style` weights says nothing about COCO 2014's constituent images [34], and no licence surveyed here addresses training data. This is an open question across the entire field and is out of scope for a per-effect tier.
- **Whether the ONNX models could be re-exported at arbitrary resolution.** `pytorch/examples` is BSD-3-Clause and the architecture is fully convolutional, so it is *likely* — but not tested here, and the shipped ONNX files are fixed-shape.

---

## REFERENCES

All GitHub, Hugging Face and PyPI facts were retrieved on **2026-09-02** via the respective APIs; local software facts were observed on the same date on macOS (Darwin 24.6.0, arm64) with ffmpeg 8.1 (homebrew, `--enable-gpl --enable-version3`), `opencv-contrib-python` 4.13.0.92, `onnxruntime` 1.23.1, `torch` 2.9.0, Python 3.12.12.

1. [TachibanaYoshino/AnimeGANv2 — README §License](https://github.com/TachibanaYoshino/AnimeGANv2#license). No `LICENSE` file; GitHub licence API returns `null`. Last push 2024-08-27.
2. [SystemErrorWang/White-box-Cartoonization — README §License](https://github.com/SystemErrorWang/White-box-Cartoonization#license). CC BY-NC-SA 4.0 by README prose; no `LICENSE` file; GitHub licence API returns `null`. Last push 2026-01-19.
3. [TachibanaYoshino/AnimeGANv3 — README §License](https://github.com/TachibanaYoshino/AnimeGANv3#scroll-license). Identical non-commercial clause; no `LICENSE` file. Last push 2025-08-23.
4. [bryandlee/animegan2-pytorch](https://github.com/bryandlee/animegan2-pytorch). GitHub licence: MIT. README §"Weight Conversion from the Original Repo" documents conversion from ref. [1]'s checkpoints.
5. [black-forest-labs/FLUX.1-schnell — Hugging Face](https://huggingface.co/black-forest-labs/FLUX.1-schnell). `cardData.license: apache-2.0`.
6. [FLUX.1 [dev] Non-Commercial License](https://github.com/black-forest-labs/flux/blob/main/model_licenses/LICENSE-FLUX1-dev). §1.c defines Non-Commercial Purpose as use from which "you do not receive any direct or indirect payment"; §2.d disclaims ownership of Outputs and permits their commercial use.
7. [black-forest-labs/FLUX.1-Kontext-dev — Hugging Face](https://huggingface.co/black-forest-labs/FLUX.1-Kontext-dev). `license_name: flux-1-dev-non-commercial-license`, card last modified 2026-01-01.
8. [black-forest-labs/FLUX.2-dev — Hugging Face](https://huggingface.co/black-forest-labs/FLUX.2-dev). `license_name: flux-non-commercial-license`, card last modified 2026-02-17.
9. [Qwen/Qwen-Image-Edit — Hugging Face](https://huggingface.co/Qwen/Qwen-Image-Edit). `cardData.license: apache-2.0`, card last modified 2025-08-25.
10. [stable-diffusion-v1-5/stable-diffusion-v1-5 — Hugging Face](https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5). `cardData.license: creativeml-openrail-m`. Note: the original `runwayml/stable-diffusion-v1-5` repository now redirects (HTTP 307) — the canonical location moved, which is itself a supply-chain fact worth recording.
11. [stabilityai/stable-diffusion-xl-base-1.0 — Hugging Face](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0). `cardData.license: openrail++`.
12. [stabilityai/sdxl-turbo — LICENSE.md](https://huggingface.co/stabilityai/sdxl-turbo/blob/main/LICENSE.md). File content is the **Stability AI Community License Agreement, "Last Updated: July 5, 2024"**, §3 carrying the $1,000,000 termination clause — while the model card metadata declares `license: other, license_name: sai-nc-community`.
13. [Stability AI — Community License](https://stability.ai/license). Lists SD 3.5, SDXL Turbo, Stable Audio 3.0 and Stable Fast 3D among the covered core models; free commercial use below $1M annual revenue.
14. [ByteDance/SDXL-Lightning — Hugging Face](https://huggingface.co/ByteDance/SDXL-Lightning). `cardData.license: openrail++`.
15. [latent-consistency/lcm-lora-sdxl — Hugging Face](https://huggingface.co/latent-consistency/lcm-lora-sdxl). `cardData.license: openrail++`.
16. [lllyasviel/ControlNet](https://github.com/lllyasviel/ControlNet) (code, Apache-2.0) and [lllyasviel/ControlNet-v1-1 — Hugging Face](https://huggingface.co/lllyasviel/ControlNet-v1-1) (`cardData.license: openrail`). Note `lllyasviel/ControlNet-v1-1-nightly` carries **no** declared licence.
17. [tencent-ailab/IP-Adapter](https://github.com/tencent-ailab/IP-Adapter) (code, Apache-2.0) and [h94/IP-Adapter — Hugging Face](https://huggingface.co/h94/IP-Adapter) (`cardData.license: apache-2.0`).
18. [instantX-research/InstantStyle](https://github.com/instantX-research/InstantStyle). No `LICENSE` file in the repository tree; GitHub licence API returns `null`; README §Disclaimer states only that "the pretrained checkpoints follow the license in IP-Adapter".
19. [google/style-aligned](https://github.com/google/style-aligned). Apache-2.0; repository **archived**.
20. [ByteDance/Bernini-R — Hugging Face](https://huggingface.co/ByteDance/Bernini-R). `cardData.license: apache-2.0`, card last modified 2026-06-02. README §Requirements: CUDA GPU, Hopper (H100/H800/H200) recommended; `t2i`/`i2i` single-GPU, video tasks "on 8 GPUs via `torchrun`". Built on `Wan-AI/Wan2.2-T2V-A14B-Diffusers`.
21. [Wan-AI/Wan2.2-T2V-A14B](https://huggingface.co/Wan-AI/Wan2.2-T2V-A14B) and [Wan-AI/Wan2.2-TI2V-5B](https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B). Both `cardData.license: apache-2.0`, cards last modified 2025-08-07.
22. [Wan-AI/Wan2.2-Animate-14B — Hugging Face](https://huggingface.co/Wan-AI/Wan2.2-Animate-14B). `cardData.license: apache-2.0`, card last modified 2025-11-05.
23. [genmo/mochi-1-preview — Hugging Face](https://huggingface.co/genmo/mochi-1-preview). `cardData.license: apache-2.0`.
24. [ByteDance-Seed/SeedVR2-3B — Hugging Face](https://huggingface.co/ByteDance-Seed/SeedVR2-3B). `cardData.license: apache-2.0`.
25. [zai-org/CogVideoX-2b — Hugging Face](https://huggingface.co/zai-org/CogVideoX-2b). `cardData.license: apache-2.0`.
26. [zai-org/CogVideoX-5b — LICENSE](https://huggingface.co/zai-org/CogVideoX-5b/blob/main/LICENSE). "The CogVideoX License": free academic use; commercial use requires registration and is capped at 1 million visits per month. Note the card's `license_link` still points at the retired `THUDM/CogVideoX-5b` path.
27. [tencent/HunyuanVideo — Hugging Face](https://huggingface.co/tencent/HunyuanVideo). `license_name: tencent-hunyuan-community`.
28. [Lightricks/LTX-Video — LTXV Open Weights License 0.X](https://huggingface.co/Lightricks/LTX-Video/blob/main/LTX-Video-Open-Weights-License-0.X.txt). "License date: April 15, 2025", applicable to LTXV v0.9.6 and later; RAIL-style use-based restrictions in Attachment A; **no revenue threshold** in this document.
29. [Lightricks/LTX-2 — LICENSE-2_x](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x). "LTX-2.x Community License Agreement", "License date: August 11, 2026"; §2.1 defines a Commercial Entity as one with "annual revenues of at least $10,000,000" and requires a separate paid Commercial Use Agreement.
30. [MiniMaxAI/MiniMax-H3 — LICENSE](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE). "MiniMax H3 COMMUNITY LICENSE AGREEMENT", release/licence date 2026-08-02. §I.3 "'Applicable Territory' means worldwide, excluding the Excluded Territories"; §I.5 "'Excluded Territories' means the European Union, the United Kingdom, the Republic of Korea and the United States of America"; §IV.1 requires prior written authorisation above $20M annual revenue; §IV.2 requires prominent "MiniMax H3" attribution. 5,532,597 downloads observed 2026-09-02.
31. [jcjohnson/neural-style](https://github.com/jcjohnson/neural-style). MIT (code).
32. [jcjohnson/fast-neural-style — README §License](https://github.com/jcjohnson/fast-neural-style#license): "Free for personal or research use; for commercial use please contact me." No `LICENSE` file; GitHub licence API returns `null`. 4,360 stars.
33. [pytorch/examples](https://github.com/pytorch/examples). BSD-3-Clause; `fast_neural_style` is the upstream of ref. [34].
34. [onnx/models — validated/vision/style_transfer/fast_neural_style](https://github.com/onnx/models/tree/main/validated/vision/style_transfer/fast_neural_style). Repository Apache-2.0; the model README carries `<!--- SPDX-License-Identifier: BSD-3-Clause -->` and a `## License / BSD-3-Clause` section, and names `pytorch/examples/fast_neural_style` as the origin and COCO 2014 as the training set. Five styles × two opsets. Both `mosaic-8.onnx` and `mosaic-9.onnx` declare `input1: [1, 3, 224, 224]` (fixed), verified with `onnxruntime` 1.23.1.
35. [naoto0804/pytorch-AdaIN](https://github.com/naoto0804/pytorch-AdaIN). MIT (code); repository **archived**.
36. [magenta/magenta](https://github.com/magenta/magenta). Apache-2.0; **archived 2026-01-06**. The arbitrary-style-transfer weights are published at [Kaggle Models: google/arbitrary-image-stylization-v1](https://www.kaggle.com/models/google/arbitrary-image-stylization-v1); `tfhub.dev` now returns 404 and the Kaggle model API exposes no licence field — **weights licence unverified**.
37. FFmpeg `configure` at tag [`n8.1`](https://raw.githubusercontent.com/FFmpeg/FFmpeg/n8.1/configure). `hqdn3d_filter_deps="gpl"` (line 4143), `owdenoise_filter_deps="gpl"` (4180), `vaguedenoiser_filter_deps="gpl"` (4232), `nnedi_filter_deps="gpl"` (4166); `deflicker`, `tmix`, `tblend`, `atadenoise`, `nlmeans`, `removegrain` and `minterpolate` declare no `gpl` dependency. `dnn_processing_filter_select="dnn"` (4123) with `dnn_deps_any="libtensorflow libopenvino libtorch"` (3029) — so ffmpeg's DNN filters are **not** GPL-gated but require a custom build; the homebrew ffmpeg 8.1 on this machine enables none of the three, so `dnn_processing`, `sr` and `derain` are absent from its filter list.
38. [Artiprocher/sd-webui-fastblend](https://github.com/Artiprocher/sd-webui-fastblend). Apache-2.0; last push 2024-08-14. Paper: [FastBlend: a Powerful Model-Free Toolkit Making Video Stylization Easier, arXiv:2311.09265](https://arxiv.org/abs/2311.09265). The `diffsynth/extensions/FastBlend` path no longer exists in current [modelscope/DiffSynth-Studio](https://github.com/modelscope/DiffSynth-Studio) (Apache-2.0, last push 2026-09-01).
39. [ChenyangLEI/All-In-One-Deflicker](https://github.com/ChenyangLEI/All-In-One-Deflicker). Apache-2.0 (code); pretrained checkpoints are a separate download whose licence is unverified. CVPR 2023.
40. [Picsart-AI-Research/Text2Video-Zero — LICENSE](https://github.com/Picsart-AI-Research/Text2Video-Zero/blob/main/LICENSE). CreativeML Open RAIL-M, dated March 28, 2023.
41. [ChenyangQiQi/FateZero](https://github.com/ChenyangQiQi/FateZero). MIT (code).
42. [omerbt/TokenFlow](https://github.com/omerbt/TokenFlow). MIT (code).
43. [robbyant-research/CoDeF — LICENSE](https://github.com/robbyant-research/CoDeF/blob/main/LICENSE). MIT, "Copyright (c) 2023 Ant Group". Formerly `qiuyu96/CoDeF`.
44. [RehgLab/RAVE](https://github.com/RehgLab/RAVE). MIT (code).
45. [williamyang1991/Rerender_A_Video — LICENSE.md](https://github.com/williamyang1991/Rerender_A_Video/blob/main/LICENSE.md). **S-Lab License 1.0**, "Copyright 2023 S-Lab": "Redistribution and use **for non-commercial purpose**… In the event that redistribution and/or use for commercial purpose… is required, please contact the contributor(s)."
46. [williamyang1991/FRESCO — LICENSE.md](https://github.com/williamyang1991/FRESCO/blob/main/LICENSE.md). **S-Lab License 1.0**, "Copyright 2024 S-Lab" — same non-commercial terms as ref. [45].
47. [jamriska/ebsynth — README §License](https://github.com/jamriska/ebsynth#license): "The code is released into the public domain… However, you should be aware that the code implements the PatchMatch algorithm, which is patented by Adobe (U.S. Patent 8,861,869)."
48. [US8861869B2 — Determining correspondence between image regions, Google Patents](https://patents.google.com/patent/US8861869B2/en). Priority 2010-08-16, filed 2013-10-17, granted 2014-10-14, current assignee Adobe Inc, status **Active**, anticipated expiration **2030-08-16**.
49. [fal.ai — decart/lucy-restyle API](https://fal.ai/models/decart/lucy-restyle/api). Video-to-video restyle; inputs `prompt` + `video_url`; output 720p; marked "Commercial use"; max length 10 minutes on the API page. The $0.01/source-second figure is from fal's [long-form user guide](https://fal.ai/learn/devs/lucy-restyle-long-form-user-guide) and not the API reference — **secondary-sourced**.
50. thorwhalen/falaw#16 — *"Licence-and-terms ledger per (model, backend), queried at plan time — `unknown` is a refusal"*. **OPEN** as of 2026-09-02. Specifies `license`, `license_binds_us`, `commercial_use`, `third_party_tenancy`, `provenance_constraint`, `source_url`, `observed_on`; names FLUX.1-dev as the worked example and Replicate's `weights_licenses.md` as the precedent.
51. thorwhalen/nw#29 — *"Decide, before the first third party arrives: does the Transform registry accept third-party registrations?"*. **OPEN** as of 2026-09-02. Carries the measured ComfyUI registry finding (85.5% of node packs declare no machine-readable licence; 76 distinct raw spellings of the `license` field; 59% point at a file rather than naming a licence) and the rule that follows: *any registry field that will later be queried for compliance must be a validated enum, enforced at publish time.*
