# Models used in PaperMind

This document records *which* Claude / embedding model the project uses,
*why*, and *how to switch*. Updated when the defaults change.

## Current defaults (Phase 1)

| Slot | Model | Cost per 1M tokens | Notes |
|---|---|---|---|
| **Claude (Q&A)** | `claude-sonnet-4-6` | $3 in / $15 out | Default for `/ask` |
| **Embeddings** | `sentence-transformers/all-MiniLM-L6-v2` | Free (local) | 384-dim, runs on your machine |

## Why `claude-sonnet-4-6` for the MVP

This is a learning project with an interview as the goal — not a
production app. Three reasons Sonnet 4.6 is the right Phase 1 default:

1. **Cheap enough to iterate freely.** $3 in / $15 out vs Opus 4.7's
   $5 / $25. While you're tuning prompts and debugging the RAG
   pipeline, you'll send hundreds of test queries. Sonnet's bill is
   ~3× lower.
2. **RAG quality is close to Opus.** The job of the Q&A endpoint is
   to read retrieved chunks and answer with citations. Sonnet handles
   this very competently — the gap mostly shows on hard open-ended
   reasoning, which isn't what RAG asks of it.
3. **Phase 2 already plans a comparison.** "Side-by-side Claude vs
   GPT-4" is the Phase 2 milestone — that's the natural place to also
   try Opus 4.7, run a measurable retrieval-quality experiment, and
   pick the production model with data instead of vibes.

`claude-haiku-4-5` is even cheaper ($1 / $5), but on grounded Q&A with
citations the quality drop is noticeable — skip it for the main path.

## How to switch

The model is a setting; the code is model-agnostic.

### Permanent switch (recommended for sustained use)

Edit `backend/.env`:

```env
CLAUDE_MODEL=claude-opus-4-7
```

Restart `./scripts/dev.sh`. Verify at <http://localhost:8109/health> —
the response includes `claude_model`.

### Quick comparison run

To compare answers between models without losing your `.env`, override
on the command line:

```bash
CLAUDE_MODEL=claude-opus-4-7 ./scripts/dev.sh
```

In Phase 2, `/ask` will accept a `?model=` query parameter for true
side-by-side comparison — see [ROADMAP.md](../ROADMAP.md) step 2.5.

## Allowed model IDs

Only use the exact IDs from Anthropic's catalog. Aliases (no date
suffix) are recommended — they always point to the latest snapshot:

| Family | Alias to use | Context | Output | Best for |
|---|---|---|---|---|
| Opus 4.7 | `claude-opus-4-7` | 1M | 128K | Hardest reasoning, agentic |
| Sonnet 4.6 | `claude-sonnet-4-6` | 1M | 64K | Balanced — MVP default |
| Haiku 4.5 | `claude-haiku-4-5` | 200K | 64K | Speed-critical / simple tasks |

Guessing a model ID with a date suffix you remember from training
data (`claude-sonnet-4-6-20251114` etc.) **will 404** — use the bare
alias.

## When to revisit the default

Move to `claude-opus-4-7` if any of these become true:

- You're hitting the limits of Sonnet on multi-step reasoning over
  retrieved chunks (e.g. it misses connections that are clearly in
  the citations).
- You're past the Phase 2 comparison and have data showing Opus is
  meaningfully better on your real documents.
- You're presenting the project at the interview and the marginal
  cost stops mattering.

Until then: stay on Sonnet, save the budget for experiments.

## Embeddings

The embedding model swap (`sentence-transformers` → `voyage-3`) is
its own Phase 2 experiment, tracked in
[ROADMAP.md](../ROADMAP.md) step 2.6. Different decision, different
tradeoffs — covered separately when we get there.
