# Evaluation results

Each folder is one scored agent run. Open `report.md` first.

| Folder | Messages | Agent version | Fully correct | Emergency recall | must_not violations | Safety issues |
|---|---|---|---|---|---|---|
| [sample-40](sample-40/report.md) | The 40 labelled sample messages | Final (end of step 4) | 36 / 40 | 100% (5/5) | 0 | 0 |
| [unseen-14](unseen-14/report.md) | 14 new messages written for this test (`data/messages_extra.json`) | Final (end of step 4) | 13 / 14 | 100% (3/3) | 0 | 0 |
| [unseen-14-blind](unseen-14-blind/report.md) | The same 14 messages | **Before** the step-4 fixes: the first time the agent saw them | 13 / 14 | 100% (3/3) | 0 | 0 |

**Blind versus final.** In the blind run, two of the three emergencies were missed by the guard and caught by the AI analysis: Spanish stroke signs, and "ending my life". The guard was widened afterwards, so in the final run all three are caught by the guard. The one failure in both runs is X014, "When is my next appointment?". The agent has no handler for it and safely passes it to the front desk.

Files in each folder:

| File | Contents |
|---|---|
| `report.md` | Human-readable report: headline metrics, missed emergencies, violations, safety invariants, every mismatch, per-action table, cost |
| `results.json` | One result per message in the brief's output format |
| `eval.json` | All metrics and per-message scoring as data |
| `traces.json` | What the agent did for each message: path, AI analysis, facts, every tool call |
| `run_log.json` | Queue tickets, refill requests, reply drafts, flags and appointment changes |
| `summary.json` | Timing, provider, models, token usage |

To re-score any folder:

```bash
.venv\Scripts\python -m edvak_forge.evaluation --run reports/sample-40
```
