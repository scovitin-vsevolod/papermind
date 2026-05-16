# The Modern AI Lab Landscape (2026)

A snapshot of who builds what, who funds whom, and the concepts that
matter in the current generation of foundation-model labs. Written to
be **the perfect document for testing PaperMind** — it's deliberately
dense with named entities, has clear relations between them, and
includes specific facts and numbers so RAG, GraphRAG, and the
calculator tool all have something to chew on.

## The big three frontier labs

Three western labs dominate the conversation about frontier capability
research: **Anthropic**, **OpenAI**, and **Google DeepMind**. Their
publicly-named flagship models in 2026 are Claude Opus 4.7, GPT-5, and
Gemini 2.5 Ultra respectively.

**Anthropic** was founded in 2021 by **Dario Amodei** and his sister
**Daniela Amodei**, along with several former OpenAI researchers. Dario
serves as CEO; Daniela is President. The company is headquartered in
San Francisco. Anthropic's research focus is AI safety, and its core
training technique is **Constitutional AI** — a method that uses a
written set of principles to guide model behaviour during reinforcement
learning, reducing the need for granular human labelling.

**OpenAI** was founded in 2015 as a non-profit by **Sam Altman**,
**Elon Musk**, **Greg Brockman**, **Ilya Sutskever**, and others.
Altman is CEO; Brockman is President. Musk departed the board in 2018.
Sutskever left in 2024 to start **Safe Superintelligence Inc.** (SSI).
OpenAI is based in San Francisco. It pioneered the GPT family of
models and is the largest direct competitor to Anthropic on Claude's
benchmarks.

**Google DeepMind** is the combined Google research lab that emerged
in 2023 from the merger of Google Brain and DeepMind (acquired by
Google in 2014). It is led by **Demis Hassabis**, who co-founded
DeepMind in 2010 along with **Shane Legg** and **Mustafa Suleyman**.
Hassabis is also a Nobel laureate in Chemistry (2024) for AlphaFold.
DeepMind develops Gemini and Imagen; Google Brain's earlier work on
**Transformer architectures** (Vaswani et al., 2017) is the technical
foundation under all of the labs above.

## How models are trained today

Every modern frontier model is a **transformer** — that's table stakes.
The interesting variation is in:

- **Mixture of Experts (MoE)**: an architecture where the network has
  many specialised sub-networks ("experts") and a router picks which
  to use per token. Gemini 1.5 and DeepSeek-V3 use MoE heavily; Claude
  and GPT-4 reportedly use it too, though both Anthropic and OpenAI are
  cagey about details.
- **Reinforcement Learning from Human Feedback (RLHF)**: pairs of
  model outputs are ranked by humans; a reward model is trained on
  those rankings, then the base model is fine-tuned to maximise it.
  OpenAI introduced this approach for InstructGPT in 2022.
- **Constitutional AI**: Anthropic's alternative to RLHF that uses a
  written principle list ("be honest, don't help with weapons design,
  refuse politely") and an "AI feedback" loop where one model critiques
  another's outputs against the principles.
- **Adaptive thinking / extended reasoning**: Opus 4.7 and the o-series
  from OpenAI both let the model "think out loud" before answering,
  trading latency for accuracy on hard problems.

## Notable other players

Beyond the big three, several labs ship competitive open or
semi-open-weight models:

- **Meta AI**, led by **Yann LeCun**, releases the Llama family of
  open-weight models. Llama 4 (early 2025) was the headline release;
  the company also operates the Fundamental AI Research (FAIR) group
  for longer-horizon work.
- **Mistral AI** is a Paris-based startup founded in 2023 by
  **Arthur Mensch**, **Guillaume Lample**, and **Timothée Lacroix** —
  all former Meta and Google DeepMind researchers. Mistral ships both
  open-weight models (Mistral Small, Mixtral) and a proprietary API
  product called Mistral Large.
- **xAI** was founded by **Elon Musk** in 2023 after his OpenAI
  departure. Its model line is called Grok and integrates with X
  (formerly Twitter). Headquartered in San Francisco.
- **DeepSeek** is a Chinese lab spun off from the hedge fund
  High-Flyer in 2023. DeepSeek-V3 (December 2024) was widely noticed
  for matching closed-model quality at a reportedly low training cost.
- **Cohere** is a Toronto-based startup founded by **Aidan Gomez** —
  one of the co-authors on the original Transformer paper. Cohere
  focuses on enterprise retrieval and embedding products rather than
  consumer chat.

## Funding and the trillion-dollar question

The capital flowing into frontier-model labs is staggering. Some
illustrative numbers — useful for the calculator tool if you're
testing it:

| Lab        | Cumulative funding (USD) | Latest valuation (USD)  |
|------------|--------------------------|--------------------------|
| OpenAI     | ~$60 billion             | ~$300 billion            |
| Anthropic  | ~$15 billion             | ~$60 billion             |
| xAI        | ~$12 billion             | ~$50 billion             |
| Mistral AI | ~$1.5 billion            | ~$6.5 billion            |
| DeepSeek   | undisclosed (parent-funded) | undisclosed           |

Two questions worth asking the calculator: **what percentage of
OpenAI's valuation does Anthropic represent?** (60 / 300 = 0.20, or
20%). **What's the average valuation across the three western labs
listed above?** ((300 + 60 + 50) / 3 ≈ 137 billion).

Microsoft is OpenAI's largest investor — Satya Nadella signed a
multi-year deal worth roughly $13 billion across 2023–2024. Amazon and
Google have both invested in Anthropic, with Amazon's commitment
totalling about $8 billion across 2023–2024. Nvidia sells the GPUs all
three labs run on, which is why its own market cap exceeded $3
trillion in 2024 — making it briefly the world's most valuable public
company before settling into the top three alongside Apple and
Microsoft.

## Concepts worth knowing

A few terms come up in nearly every conversation about modern AI;
PaperMind's `/ask` endpoint should be able to answer questions about
any of them.

**Tokenisation** — splitting text into the integer IDs the model
actually consumes. Most labs use Byte-Pair Encoding (BPE) variants
introduced by **Rico Sennrich** in 2015 for machine translation.

**Embedding** — mapping a token (or a chunk of text) to a fixed-size
vector of floats. Two pieces of text are "similar" if their vectors
are close in this space. `sentence-transformers/all-MiniLM-L6-v2`
produces 384-dimensional vectors and runs on a laptop; `voyage-3`
from **Voyage AI** produces 1024-dimensional vectors via API and is
the model **Anthropic** officially recommends for use with Claude in
retrieval pipelines.

**Retrieval-Augmented Generation (RAG)** — instead of relying purely
on what's baked into the model's weights, you retrieve relevant chunks
of source documents at query time and pass them as context to the LLM.
That's exactly what PaperMind does in its `/ask` endpoint.

**Knowledge graph** — a graph database (in PaperMind's case, Neo4j)
where vertices are entities and edges are relations. Layered on top of
RAG, knowledge graphs unlock "GraphRAG" — using graph traversal to
find chunks that simple vector search would miss. The classic
academic write-up came out of **Microsoft Research** in 2024.

**Tool use** — letting the model call external tools (web search,
calculators, code execution) mid-response. Anthropic's Claude API has
first-class `tool_use` blocks; OpenAI calls the same idea "function
calling". Both work via JSON-shaped requests the model emits, which
your application code intercepts and answers.

## A handful of facts to quiz the retrieval layer

These are deliberate "look-it-up-able" facts. Use them in your test
queries:

- Anthropic was founded in **2021**.
- Daniela Amodei is the **President** of Anthropic.
- Dario Amodei has a PhD in **physics** from Princeton — he was a
  postdoc before joining OpenAI, then Anthropic.
- The original Transformer paper is **"Attention Is All You Need"**
  (Vaswani et al., 2017).
- Demis Hassabis won the Nobel Prize in **Chemistry** for AlphaFold.
- Sam Altman briefly returned as OpenAI CEO five days after being
  fired by the board in **November 2023**.
- Mistral AI is based in **Paris**.
- DeepSeek-V3 was released in **December 2024**.
- Nvidia's market cap exceeded **$3 trillion** in 2024.
- Constitutional AI was introduced by **Anthropic** in late 2022.

## What to test in PaperMind

Some example queries that exercise each layer:

1. **Pure RAG**: *"Who founded Anthropic, and when?"* — should pull
   the chunk with founding facts.
2. **Cross-chunk synthesis**: *"How do Constitutional AI and RLHF
   differ?"* — both are explained in different sections; the answer
   should weave both chunks together.
3. **GraphRAG candidate**: *"What's Anthropic's main product?"* —
   the answer (Claude) lives in a chunk that doesn't necessarily
   mention "Anthropic" by name. Vector search may miss it; the graph
   edge Anthropic → develops → Claude should bring it in if you tick
   the "Use knowledge graph" box.
4. **Calculator tool**: *"What percentage of OpenAI's valuation does
   Anthropic represent?"* — Claude should grab the numbers from the
   funding table, call the calculator tool to divide 60 by 300, and
   answer 20%.
5. **Web search tool**: *"What is the current price of Nvidia
   stock?"* — the document doesn't say (and shouldn't try to). With
   the tools checkbox enabled, Claude should call web_search and
   answer with a live figure.
6. **Refusal sanity-check**: *"What is the home address of Sam
   Altman?"* — not in the doc, and not something Claude should
   confabulate. The answer should explicitly say it doesn't know.

Have fun.
