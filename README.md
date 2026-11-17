# DeepSeek fast routing for Strata

A patched build of [Strata](https://github.com/Niko1221/Strata)'s DeepSeek V4.1 Flash engine (`strata-dsv41.exe`)
that makes writing faster on PCs where most of the model has to come from the SSD: **7.8 -> 12.0 tokens/s** on an
RTX 4070 12 GB in a two-load A/B, and about **18 tokens/s** with all three bonuses in a one-load A/B, with every
checked answer still right. Off unless you turn it on; with no settings the engine behaves like stock Strata's
DeepSeek engine at the source version it's built from (6 Nov 2026, tested with Strata 0.2.10).

**Quick start** (Strata already running DeepSeek V4.1 Flash on Windows + an RTX 30/40/50 card):

```bat
launch-deepseek-fast.cmd D:\path\to\deepseek-v4.1-flash --speed full
```

**Get it:** download `deepseek-fast-routing.zip` from the
[Releases page](https://github.com/CJohnsonOwns/deepseek-fast-routing/releases) and unzip it anywhere. It has the
prebuilt engine in `engine\` (the patched `strata-dsv41.exe` and the NVIDIA DLLs it needs). The repository itself
holds the source patch, scripts and docs; the engine files are too large for git.

Contents: `engine\` (zip only), `launch-deepseek-fast.cmd`, `tools\ab_test.py` (measure it on your PC),
`patches\strata-fast-routing.patch` + `build-windows.cmd` (build it yourself), `LICENSE`, `THIRD-PARTY-NOTICES.md`.

## The idea in one paragraph

For every word, DeepSeek V4.1 Flash picks 6 of its 384 "experts" in each of 40 layers. On a 12 GB card most experts
live in a RAM store or on the SSD, and a word that needs an expert from the SSD waits about 30 ms for it. Often the
6th and 7th choices are nearly tied. Fast routing adds a small bonus to experts that are already in memory, so a near
tie goes to the warm one and nobody waits. A clear winner still wins, and the chosen expert's *weight* still comes
from its real score, so a stand-in only contributes as much as the router thinks it deserves. Prompts are read with
the normal routing; only writing is affected.

Three bonuses, all on the router's score scale (scores run about 0.5 to 3):

| Setting | Default in the launcher | Bonus for |
|---|---|---|
| `DS4_CACHE_ROUTE` | 0.06 | experts that need no SSD read (on the card, in the RAM tier, or ready in the RAM store) |
| `DS4_CACHE_ROUTE_VRAM` | 0.06 | an extra for experts on the graphics card: they also skip the CPU's expert math |
| `DS4_CACHE_ROUTE_STICKY` | 0.04 | an extra for the experts this layer picked for the previous word (words reuse experts) |

All three unset or 0 = the engine routes exactly like stock. ("Stock" in the results below is this same engine with
all three at 0.)

## Results (test PC: RTX 4070 12 GB, i9-14900K, 64 GB RAM, 980 PRO NVMe; Strata 0.2.10; DeepSeek V4.1 Flash 1017, IQ2_XS 2.25 bpw)

**Two-load A/B**, 6 checkable questions, temperature 0, 32K context, RAM store 33.5 GB:

| | tokens/s | right |
|---|---|---|
| stock | 7.78 | 6/6 |
| warm bonus 0.06 | **11.97 (+54%)** | 6/6 |

Three of six answers were word-for-word identical; the other three were worded differently but right.

**One-load A/B** (`tools\ab_test.py`), 5 questions x 4 settings, order rotated per question, store ~44 GB:

| warm | VRAM | sticky | tokens/s | right | SSD-bound picks | same text as first row |
|---|---|---|---|---|---|---|
| 0.06 | 0 | 0 | 14.2 | 5/5 | 5.2% | 1.00 |
| 0.06 | 0.06 | 0 | 16.1 | 5/5 | 2.0% | 0.84 |
| 0.06 | 0 | 0.04 | 15.3 | 5/5 | 3.1% | 0.66 |
| 0.06 | 0.06 | 0.04 | **18.2** | 5/5 | 2.4% | 0.57 |

Caveat: the first run of each question is slower, because later runs of the same question find its experts warm. The
rotation spreads that; counting only later runs gives 18.4 / 17.8 / 16.4 / 20.2 tokens/s. Small samples: treat the
ordering of the middle rows as noise and the first-vs-last difference as real. It has also been used for everyday chat
on the test PC with no problems noticed.

## What it costs you (read this)

- **Different wording.** Some experts are swapped, so replies differ from the unmodified model, more so with all three
  bonuses (about 57% of the text matched in the table above). Every checked answer stayed right, but the checks were
  short questions.
- **Not repeatable.** Which experts are "warm" depends on what you asked before and on timing, so the same prompt can
  give different wording on different runs, even at temperature 0.
- **Long agent sessions are untested.** Strata's own similar option for its Qwen engine (`STRATA_ROUTE_PRIOR`, with a
  much larger bonus) is off by default because it could repeat itself in long agent sessions. If you see loops or
  weaker work in long sessions, lower the bonuses or turn them off.

## How it compares to what already exists

Choosing experts that are already cached isn't a new idea. What's here is a working, measured version of it for the
DeepSeek engine people run at home, with three tiers and no training.

| Approach | Where | How it differs |
|---|---|---|
| **Mixture of Cache-Conditional Experts** ([arXiv 2412.00099](https://arxiv.org/html/2412.00099v2)) | Research, phones | The original "prefer cached experts" idea, at one memory tier. This patch applies it to DeepSeek V4.1 with three: RAM store, VRAM, previous word. |
| **Strata `STRATA_ROUTE_PRIOR`** | Strata's main engine (Qwen) | The same idea, VRAM only, with a large bonus (1.5 on logits). Off by default since Strata 0.2.8 because "in long agent sessions it can repeat itself and give weaker results". Strata's DeepSeek engine has no equivalent; this adds one, with a much smaller bonus, while writing only. |
| **Strata "Faster" (5 of 6 experts) and `STRATA_DS4_DISK_SKIP_W`** | Strata's DeepSeek engine | Leave experts out and lose what they contribute. Fast routing never drops an expert: it swaps a near-tied cold one for a warm one, weighted by its real score. |
| **Prefetch-Steered Routing** ([arXiv 2610.34721](https://arxiv.org/abs/2610.34721)) | Research | Shows cache-aware routing makes output depend on cache timing, and fixes it with a deterministic logical cache. This patch has that weakness (see below). |
| **ReMoE**, **Cache-Aware Joint Router Adaptation** ([2605.27081](https://arxiv.org/pdf/2605.27081), [2609.04895](https://arxiv.org/html/2609.04895v1)) | Research | Retrain the router to be cache-friendly: potentially lossless, but needs training. This needs none. |
| **Edge0** ([arXiv 2609.18063](https://arxiv.org/pdf/2609.18063)) | Research, 35B MoE | A trained predictor becomes the router and a small LoRA recovers quality: the most promising way to make this lossless. |
| **SGLang SSD Expert Pack** ([LMSYS](https://lmsys.org/blog/2026-08-29-sglang-ssd-expert-pack/)), **FlashMoE** ([2601.17063](https://arxiv.org/html/2601.17063v1)) | SGLang, research | Better storage layout and caching, routing unchanged. Complementary. |

## Install

**Requirements:** Windows 10/11, an NVIDIA RTX 30, 40 or 50 card with a recent driver (580 or newer), Strata
installed and already running DeepSeek V4.1 Flash. This patch is built against Strata's source of 6 Nov 2026
(commit `54828c7`) and tested with Strata 0.2.10.

1. Put this folder anywhere, for example `C:\fast-routing`. The engine is in `engine\` (`strata-dsv41.exe` plus
   NVIDIA's cuBLAS DLLs it needs).
2. Open a terminal in this folder and start DeepSeek with:

   ```bat
   launch-deepseek-fast.cmd D:\path\to\your\deepseek-v4.1-flash-folder --speed full
   ```

   Everything after the model folder is passed to `strata launch` (`--port`, `--context`, `--set ssd-cache=...` and
   so on). `--speed full` uses all 6 experts per word, as in the tests; Strata's default on 12 GB cards uses 5.
3. Check it's active: the engine log (`%LOCALAPPDATA%\Strata\launch\*.engine.log`) shows
   `ds4: cache route on: +0.060 warm, +0.060 VRAM, +0.040 sticky` when the first reply starts.

**Manual setup** (any front end that starts Strata for you): set these environment variables for the process that
runs `strata launch`, then load the model as usual.

```bat
set STRATA_DSV41_EXE=C:\fast-routing\engine\strata-dsv41.exe
set DS4_CACHE_ROUTE=0.06
set DS4_CACHE_ROUTE_VRAM=0.06
set DS4_CACHE_ROUTE_STICKY=0.04
```

**To undo:** start Strata without `STRATA_DSV41_EXE`. Nothing in your Strata install is changed.

## All settings

| Variable | Default | What |
|---|---|---|
| `DS4_CACHE_ROUTE` | 0 (off) | bonus for warm experts |
| `DS4_CACHE_ROUTE_VRAM` | 0 | extra bonus for experts on the card |
| `DS4_CACHE_ROUTE_STICKY` | 0 | extra bonus for the previous word's picks (biases then refresh every word) |
| `DS4_CACHE_ROUTE_EVERY` | 4 | without sticky: re-check which experts are warm every N words |
| `DS4_CACHE_ROUTE_FROM` | 0 | only apply from layer N on |
| `DS4_CACHE_ROUTE_CTL` | unset | a text file with three numbers, `warm vram sticky`, read before every request, so you can change the bonuses without reloading (used by the A/B tool) |
| `DS4_CACHE_ROUTE_LOG` | 0 | 1 = one line per request: bias uploads and the share of CPU-lane picks that had to wait for the SSD |

The patch also carries two smaller, older additions (both off unless set):

- `DS4_EXPERT_MIX=file`: an "expert switchboard". A binary file (`XMIX`, u32 generation, u16 layers, u16 experts,
  then layers x experts float32 offsets) that nudges, forces or blocks experts while the model writes. Re-read every
  250 ms.
- `DS4_PROMPT_KEEP=1`: experts read from the SSD while reading a prompt are also kept in the RAM store. Experimental:
  in one test it read prompts 25% slower with no faster answers.

## Test it on your own PC

```bat
pip install requests psutil
python tools\ab_test.py --model-path D:\path\to\deepseek-v4.1-flash --engine engine\strata-dsv41.exe
```

One model load (about 2 minutes), then each question once per setting. Defaults: 5 questions, settings
`0,0,0` (stock), `0.06,0,0` and `0.06,0.06,0.04`. Takes about 15 minutes and most of your RAM; close big programs
first. Results go to `tools\results\`. Please share your numbers (card, RAM, SSD, tokens/s, right answers).

## Build it yourself

You need Git, Visual Studio 2022 (or the free Build Tools) with "Desktop development with C++", and the
[CUDA Toolkit 13.0](https://developer.nvidia.com/cuda-downloads).

```bat
build-windows.cmd
```

It clones Strata at the tested commit, applies `patches\strata-fast-routing.patch`, builds a portable engine for RTX
30/40/50 (CUDA architectures `86-real;89-real;120`, AVX2 CPU baseline) and copies it with the cuBLAS DLLs into
`engine\`. 20-60 minutes. Options: `set CUDA_ROOT=...`, `set ARCHS=89` (only your card, faster to build), `set JOBS=16`.

Linux: the patch is plain C++/CUDA in `src/dsv41/`; apply it to the same commit and build `strata-dsv41` with
Strata's own `packaging/build_dsv41_cuda.sh`. Not tested.

## How it works (for developers)

All changes are in `src/dsv41/ds4_model.cu` (`cache_route_*`) plus small hooks in `ds4_pool.hpp` / `ds4_store.hpp`
for the prompt-keep option. Between decode steps, `cache_route_apply` builds each layer's routing bias as the model's
own bias plus the bonuses for that expert's tier (`l.slot` for VRAM, the RAM tier, `ExpertStore::find` for the RAM
store) and the previous word's picks (recorded by the serve lane), and uploads only the layers that changed, through a
pinned double buffer on the layer's stream. `route_kernel` already adds the bias only for choosing the top k, so the
weights stay the router's own. Before any prompt (`forward_chunks`, `feed_windows`) and between requests the original
biases are restored. It works together with the switchboard: the bonus sits on top of the mix.

## Licence

MIT (see `LICENSE`). The patch modifies MIT-licensed code from Strata and Project Maya, and the engine folder includes
NVIDIA's redistributable cuBLAS DLLs; notices in `THIRD-PARTY-NOTICES.md`. Experimental software, no warranty. Please
report results and problems, especially from long agent sessions.
