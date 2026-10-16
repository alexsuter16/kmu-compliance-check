# KMU-Compliance-Check

A sovereign compliance pre-check for Swiss online shops. It reads a shop's public pages, checks
**18 legal points under Swiss law** (legal notice, order process, prices, data protection,
advertising claims, terms) and returns a **score from 0 to 100 with a traffic light**. Every
finding comes with the legal basis, a quote from the shop that code has verified, and a concrete
fix. **Apertus 1.5** makes every judgement; it runs wherever Apertus runs – on-premise,
air-gapped or in a Swiss cloud.

Hack Apertus 2026 · Track 2B (own project) · Alex Suter (solo).

> Pre-check, not legal advice.

**Demo video (2 min):** https://www.youtube.com/watch?v=TMmmkfqVIfs

## Run it

The project lives in [`track_2b/`](track_2b/) as the template requires.

```bash
cd track_2b
export LLM_NAME=swiss-ai/apertus-v1.5-8b LLM_BASE_URL=<endpoint> LLM_API_KEY=<key>
make run                                # Docker: web UI on http://localhost:7860
make demo SHOP=testshop:velowerk        # Docker: one check, report in the terminal
```

`make run` also works from this folder; it forwards to `track_2b/`.

## Results in one table

| Measured on | Result |
|---|---|
| 8 fictional test shops, 37 planted defects | 86 % of defects found, 89 % precision, prompt-injection test passed |
| 21 real Swiss shops, every verdict audited on the live site | agreement 63 % → 72 % after the audit fixes, false alarms 48 → 25 |
| 10 new real shops, audited blind (hold-out) | 63 % agreement, 55 % of clear defects found, 63 % of reported defects real |
| Cost | about USD 0.01 per real shop at list price |

Details: [evaluation](track_2b/docs/evaluation.md) · [technical report](track_2b/technical_report.md)
([PDF](track_2b/AlexSuter_Report.pdf)).

## Where to find what

| Path | What it is |
|---|---|
| [`track_2b/README.md`](track_2b/README.md) | Project README: how it works, code map, commands, how each hackathon requirement is met |
| [`track_2b/technical_report.md`](track_2b/technical_report.md) | Architecture, use of Apertus, evaluation, limitations |
| [`track_2b/docs/bauplan.html`](track_2b/docs/bauplan.html) | Illustrated explainer written like a Swiss statute (German) |
| [`track_2b/docs/evaluation.md`](track_2b/docs/evaluation.md) | All measurement results |
| `track_2b/src/` · `data/` · `tests/` | Code, checklist, statutes, test shops, unit tests |

## License

Code: Apache-2.0 ([LICENSE](LICENSE)). Documentation and checklist: CC-BY-4.0. Test shops:
CDLA-Permissive-2.0. Statutes: official enactments, free to use (Art. 5 URG).
