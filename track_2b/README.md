# KMU-Compliance-Check · Track 2B

A compliance pre-check for small Swiss online shops (SMEs, in German «KMU»), built with
**Apertus 1.5**. It loads up to 10 public pages of a shop, checks 18 points of Swiss law
(UWG, PBV, DSG, OR, MSchG) and returns a score with a traffic light. Every finding names the
legal basis, quotes the shop's page as evidence (verified in code) and suggests a fix. On request,
Apertus drafts the missing text, e.g. the paragraph on data transfers abroad.

> Pre-check, not legal advice. Every report says so.

**Demo video (2 min):** https://www.youtube.com/watch?v=TMmmkfqVIfs

## Run it

```bash
export LLM_NAME=swiss-ai/apertus-v1.5-8b LLM_BASE_URL=<endpoint> LLM_API_KEY=<key>
make run                                # builds the Docker image, web UI on http://localhost:7860
make demo SHOP=testshop:velowerk        # same image, one check, report in the terminal
```

- Instead of `export`, the three values can go into `.env` (template: [`.env.example`](.env.example)).
- No GPU needed: the model runs at the endpoint. The image contains the statutes and builds offline.
- Try `testshop:bergwiese` (many defects), `testshop:velowerk` (model shop) or any public shop URL.

## How it works

```
shop URL ─▶ seiten_laden ─▶ seiten_zuordnen ─▶ pruefen × 18 (parallel, Apertus) ─▶ score_berechnen ─▶ bericht
             ≤ 10 pages       page types          + exact statute text from fedlex     in code, no LLM      quotes, laws, fixes
                                                  + rules in code that verify
```

Four ideas carry the design:

1. **Apertus judges, code verifies.** Only `pruefen` calls the model. Code checks every quote
   against the page, decides whether a checkpoint applies at all, and computes the score.
2. **Evidence, not claims.** A finding without a verifiable quote is not reported as a violation.
3. **Honest when unsure.** Pages the tool cannot see (checkout, JavaScript-only pages) give «unclear», never «missing».
4. **Sovereign.** One OpenAI-compatible endpoint is the only runtime dependency besides the shop itself.

The illustrated explainer [`docs/bauplan.html`](docs/bauplan.html) (German, written like a Swiss
statute) goes through every step with diagrams.

## Reading the code

In the order the data flows. Every file starts with «Schritt N» and names its article in the explainer.

| Step | File | What it does |
|---|---|---|
| 1 | `src/download_data.py` | load the statutes from fedlex (already in `data/laws/`) |
| 2 | `src/ingest.py` | split the statutes into citable passages (run at `docker build`) |
| 3 | `src/retrieval.py` | optional free search over the statutes (experiment, not in the image) |
| 4 | `src/crawler.py` | load a shop's pages, clean them, assign page types |
| 5 | `src/pipeline.py` | the check as a LangGraph graph, including the rules that verify the model |
| 5 | `src/prompts.py` | the prompt of one check; long pages are reduced to the relevant sections |
| 6 | `src/scoring.py` | score and traffic light, without a model |
| 7 | `src/report.py` | the report in Markdown |
| 8 | `src/evaluate.py` · `evaluate_audit.py` · `evaluate_crawler.py` | measurements: test shops, real-shop audit, page discovery |
| 9 | `src/app.py` · `src/ui_parts.py` | the web UI (Gradio) and its look |

Helpers: `config.py` (paths), `catalog.py` (checklist), `laws.py` (statute lookup), `evidence.py`
(quote verification), `llm.py` (access to Apertus), `drafts.py` (text drafts), `protocol.py` (audit trail).

Conventions:

- **Business rules are data**, not code: checkpoints, legal references, weights, page types,
  trigger patterns and keywords for long pages are in [`data/checks.json`](data/checks.json).
- Graph nodes have German names like in the explainer (`seiten_laden`, `pruefen`); helpers are
  English. Comments are German and explain *why*.
- `make test` runs 43 unit tests for everything that works without a model.

## Commands

| Command | What it does |
|---|---|
| `make run` / `make demo` | Docker: web UI / one headless check (for the jury) |
| `make setup` | local virtual environment with all runtime packages |
| `make index` | split the statutes into passages (needed once for local runs) |
| `make app` | web UI locally, without Docker |
| `make check SHOP=…` | check one shop, report in `output/` |
| `make eval` | check all test shops and compare with the answer keys |
| `make test` | unit tests, no model or key needed |
| `make setup-search` · `make search` · `make report` | optional: retrieval experiment, report PDF |

## Apertus fully offline

On a Mac with Apple Silicon, Apertus 1.5 8B runs as a 4-bit MLX model with an OpenAI-compatible
API. The project only needs the three variables pointed at it:

```bash
python3 -m venv apertus-lokal/.venv && apertus-lokal/.venv/bin/pip install mlx-lm
apertus-lokal/.venv/bin/hf download m1rkocasu/Apertus-v1.5-8B-text-MLX-4bit-DWQ --local-dir apertus-lokal/model
apertus-lokal/.venv/bin/mlx_lm.server --model apertus-lokal/model --port 8080 \
    --chat-template-args '{"enable_thinking": false}'
export LLM_NAME=apertus-lokal/model LLM_BASE_URL=http://127.0.0.1:8080/v1 LLM_API_KEY=local
make check SHOP=testshop:bergwiese      # from Docker use host.docker.internal instead of 127.0.0.1
```

The 4-bit model works but is less accurate (see the evaluation). On a GPU server, vLLM serves the
full open weights the same way.

## How the Track 2B requirements are met

| Requirement | Where |
|---|---|
| Built with Apertus; role of other models described | Apertus 1.5 8B makes every judgement. gpt-oss-120b was used only during development before the Apertus key arrived; multilingual-e5-small only in the optional retrieval experiment. [Report §3](technical_report.md#3-use-of-apertus) |
| Template structure, `track_2b/` unchanged | `README.md`, `technical_report.md`, `Makefile`, `src/`, `data/`, `docs/` |
| Runs in Docker with `make run`, end-to-end | [`Dockerfile`](Dockerfile), [`Makefile`](Makefile); uses `LLM_NAME`, `LLM_BASE_URL`, `LLM_API_KEY` |
| Target architecture (on-premise, air-gapped, Swiss cloud) | all three; [report §2](technical_report.md#2-architecture). Statutes are in the image; the only runtime dependency is the Apertus endpoint |
| `data/` under 100 MB | about 9 MB (statutes 8.4 MB, test shops, checklist) |
| Technical report, PDF, max. 6 pages | [`technical_report.md`](technical_report.md), [`AlexSuter_Report.pdf`](AlexSuter_Report.pdf) |
| Demo video, max. 2 min | [https://www.youtube.com/watch?v=TMmmkfqVIfs](https://www.youtube.com/watch?v=TMmmkfqVIfs) (1:57) |
| Dataset (optional) | not submitted separately; the 8 test shops with answer keys are in [`data/testshops/`](data/testshops/) |

| Judging criterion | Where to look |
|---|---|
| Purposeful use of AI | the model judges, code verifies; rules measured with an ablation ([evaluation](docs/evaluation.md)) |
| Technical rigour | test shops with answer keys, a live-site audit of 378 verdicts, a blind hold-out, 43 unit tests |
| Value, cost & scalability | a real shop costs about USD 0.01; 18 parallel calls; text drafts for every defect |
| Sovereign deployability | Swiss open model, statutes in the image, offline run demonstrated on a laptop |
| Implementation feasibility | `make run`; limits stated honestly in [report §6](technical_report.md#6-limitations) |

## Data and privacy

- The statutes (fedlex, public domain) and the fictional test shops are in the repository.
- Reports on real shops and the audit keys quote third-party websites. They stay local in
  `output/` (git-ignored). The only real shop named in the documents is the author's own, nuvate.ch.
- API keys live only in `.env` (git-ignored, never in the image).

## License

Code: Apache-2.0. Documentation and checklist: CC-BY-4.0. Test shops: CDLA-Permissive-2.0.
Statutes: official enactments, free to use (Art. 5 URG).
