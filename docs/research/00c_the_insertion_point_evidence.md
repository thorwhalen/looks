# Evidence: where a Look actually attaches, read off muvid's bounded-memory invariant

*2026-09-02. Read from source by the orchestrating session: `muvid/footage/assemble.py`'s module docstring, which is the authoritative statement of the invariant. Independent of the research agents; handed to the synthesis because it settles two questions at once.*

## Verdict

`muvid.footage.assemble` renders **one ffmpeg invocation per part**, with a constant number of decoders per invocation, because the previous single-`-filter_complex`-over-all-cuts shape held a decoder context per cut and was OOM-killed at 30 cuts on the 3.7 GB production box (muvid#21/#24). Every part is already scaled and padded onto a fixed canvas through a per-part filter chain.

**So the seam is: `looks` emits a `-vf` chain fragment, and the consumer inserts it into the per-part invocation it is already making.** No new inputs, no new decoders, no change to the invariant. That is the whole integration.

Two consequences, and they are the two hardest open questions in the kickoff:

### 1. The "which source is on screen at time t" problem dissolves

The muvid#63 comment records that the shipped Que Calor stylizer had to carry a per-clip table and resolve it **per frame from the EDL's spans**, because "a stylizer applied to a finished render has no other way to know which source a frame came from" — and offers two ways out: `looks` takes a clip-annotated timeline, or the effect is applied **per cut before assembly**.

Applying per cut is strictly better, and the invariant is why. At part-render time the consumer *already knows* which clip it is holding — that is what a part IS. The per-clip parameter is just a parameter of that part's chain. Nothing needs a timeline, nothing needs spans, and `looks` never comes near an EDL, which is the standing prohibition.

The finished-render path is the one that needed the span table, and it needed it *because* it had thrown that knowledge away. It should be documented as the degraded path, not designed for.

### 2. `Effect.at` is mostly not needed, and that is a feature

If a Look attaches per part, "where does this look apply" is answered by *which part you attached it to*. `at` earns its place only for effects that vary **within** one clip's span — a ramp, a hold-then-release. That is a much smaller and better-defined job than "locate this look on the edit's timeline", and it keeps the type honest about not being an EDL.

## Why this also constrains what `looks` may offer

The invariant is a property of the *caller's* loop, and `looks` can break it from a distance. Two specific hazards, both worth being rules:

- **A convenience `looks.render(clip, look)` is not merely out of scope — it is actively dangerous.** The kickoff says it "*will* get used and *will* rebuild one big `-filter_complex`". The docstring above is the measurement behind that sentence: it is not a stylistic preference, it is a 2.3 GB regression on a 3.7 GB box.
- **A multi-input effect adds a decoder.** muvid's own transition part is a two-input `xfade`, and the docstring is explicit that **TWO is the number that matters** — "a constant number of decoders per invocation keeps it. Reaching for one filtergraph over all parts is exactly how the OOM below comes back." So `looks` may express two-input effects (which is what makes the inherited transitions expressible at all), but an effect whose input count grows with the edit is forbidden by construction, not by taste.

## The mixed-backend case still has to be answered separately

The real Que Calor chain is cv2-flatten → ffmpeg-`lut3d` → ffmpeg-posterise: one Python stage sandwiched between ffmpeg stages, which is not a `-vf` fragment at all. The shipped script solved it by piping raw frames through a Python process per chunk, at ~8 s chunks across a process pool. A `-vf` fragment cannot express that, so the compiled plan must be able to say *"a run of ffmpeg filters, then a frame-callable, then another run of ffmpeg filters"* — and each boundary between runs is a raw-frame pipe, i.e. a real cost the plan should surface. That is the compilation question (research note 05); this note only fixes where the ffmpeg-only case attaches.

## REFERENCES

1. `muvid/footage/assemble.py` module docstring — the invariant, its measurement, and the transition exception. Read 2026-09-02 at `$PP/t/muvid`.
2. [thorwhalen/muvid#63](https://github.com/thorwhalen/muvid/issues/63) and its comment "A measured design constraint from building the first real look" — the per-clip parameter finding and the two ways out.
