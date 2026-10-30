---
type: driver
title: reporter (campaign reports)
description: 'core/report.py starts the reporting agent (sibling checkout mu2ebo-reporter, $AUTORESEARCH_REPORTER) at every closed_loop exit and on the MCP start_report tool; a detached job writing a number-checked Markdown report under <prefix>/reports/'
status: active
timestamp: '2026-10-15'
---

# reporter (campaign reports)

## Summary
Every campaign ends with a report. When `graph.closed_loop` leaves its loop, whether done, aborted, or because the
pool raised, it calls `final_report`. That starts the reporting agent, the Genesis phase 1 item of docdb-58092, as
a detached job (`core/report.py`). The agent reads the campaign through this repo's two MCP servers and the Mu2e
`kb` server, has an LLM write a Markdown report, and checks every number in it against the tool outputs. A driving
agent on the [service](service.md) MCP server can also ask for interim reports with `start_report` whenever it
judges there is something to tell. The exit report needs no request.

## Facts
- **Where.** The agent is [RobMina/mu2ebo-reporter](https://github.com/RobMina/mu2ebo-reporter), cloned beside this
  repo like the kits; `activate.sh` exports `AUTORESEARCH_REPORTER=../mu2ebo-reporter` when the directory exists.
  It runs on `$AUTORESEARCH_PYTHON` (ana 2.8.0 has `mcp` 2.0, `openai`, `anyio`).
- **A job per report.** Each report gets `<GRAPH_DATA>/<prefix>/reports/<stamp>-<trigger>-<hex>/` with `job.json`,
  `lock`, `log`, `out/` (`report.md`, `facts.json`, `check.json`, `trace.jsonl`, `run.json`) and `rc`, which is
  written last. The pattern is that of `service/jobs.py`: the job holds `lock` while it lives, so it survives the
  loop's exit, and a killed one reads as `lost`. `rc` 0 means every number was checked; 1 means the report was
  written but a number is not in the tool outputs (`checked: false`); anything else means no report.
- **Triggers.** `exit` comes from closed_loop, with the note `closed_loop exit code <rc>`. `milestone` comes from
  `start_report(name_prefix, note)`, one at a time per campaign. The agent's prompt marks a milestone report as
  interim. `campaign_status(prefix)["reports"]` lists both kinds; `report(prefix, report_id)` returns the text.
- **Never blocks a campaign.** A missing checkout is a warning at launch (`[closed_loop] WARNING: no final report
  at loop exit`, also printed by `--check-only` and so by the MCP dry run); the campaign runs without the report.
  A report that cannot start at exit is a logged warning, and the campaign's exit code stands. `--no-report`
  silences both. `campaign.json` records `"report": true|false`.
- **Model.** The default is `gpt-oss:120b` on `vllm.fnal.gov`, the aitools harness default; the `openai` client is
  what the retired `autoresearch_loop.py` used (f6f281f, against litellm.fnal.gov). `MU2EBO_REPORT_ENDPOINT`,
  `MU2EBO_REPORT_MODEL` and `MU2EBO_REPORT_API_KEY_CMD` choose others (litellm, ALCF Sophia/Metis, AmSC). The `kb`
  context needs `MIKEY_TOKEN`; without it a report has no DocDB section.
- **Read-only.** The agent's model sees only `list_studies`, `show_study`, `campaign_status`, `leaderboard`,
  `list_problems`, `stats`, `predict`, `kb_search` and `kb_get`. A report launches nothing and costs no grid time.
- **Tests** use `tests/fixtures/fake_reporter` (no model), which `tests/__init__.py` and `engine_env` export, so an
  operator's real checkout is never started on a test campaign (`tests/test_report.py`).
- **Another operator's board needs a snapshot** for a by-hand report (`mu2ebo-reporter/scripts/snapshot-campaign.sh`):
  `core/locks.py` opens lock files `O_CREAT|O_RDWR`, so reading without write access to the owner's `locks/` fails.
  This does not affect the loop-exit report, which runs as the campaign's owner.
- **First runs (2026-10-15, bpzq01).** Every table matched the tools: 0 unsupported numbers out of 114 on ALCF
  Sophia `openai/gpt-oss-120b` and out of 122 on vllm.fnal.gov `gpt-oss:120b`. Each report took one LLM turn of
  about 29k prompt tokens. Both models still carried a DocDB conclusion over to the campaign without a number, so
  read the claims.

## Open
- A claims reviewer beside the number check; slides; a lock-free read path for other operators' boards.
