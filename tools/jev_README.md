# tools/jev_smoke.py - JEV (TypeSafe System One) line verification

`jev_smoke.py` checks whether a JEV decision line can be added for the bots. Each run tests one line: TypeSafe cloud or local Ollama. It uses only the Python 3.10+ standard library, so there is nothing to install.

| line | base URL (default) | auth | default model |
|---|---|---|---|
| `cloud` | `https://api.typesafe.ai` | `Authorization: Bearer <key>` | `jev-latest` |
| `ollama` | `http://localhost:11434` (Ollama >= 0.35) | placeholder `ollama` | `nimble` (also `tev1`, `tev1:0.8b`) |

Both lines use `POST /v1/systemone`. Preflight calls `GET /v1/models` on cloud, and `GET /api/version` plus `/api/tags` on Ollama.

## What it sends
There are two fixed sets of team-chat cases, chosen with `--set`:
- `--set 1` (default) has 8 cases.
- `--set 2` has 20 cases, covering gates, implementation, acceptance, coordination, owner escalation and no-handoff messages.

Both sets use the same `ROUTE_CRITERIA`, the same `orig`/`B` wordings and the same three questions. Each case is sent as `state={"message": ...}` with the same three questions:
- `route` (choice): `sheep` / `pig` / `dog` / `cat` / `owner` / `none`. The descriptions live in **`ROUTE_CRITERIA`**, one constant near the top of the file.
- `wake` (noul): > 0.5 means wake.
- `urgency` (score): `["低","中","高"]`. The top class is the **argmax of `probabilities`**. `score` is only recorded.

Route wording variants: `orig` = 這則團隊聊天訊息接下來應該交給誰處理？ and `B` = 這則訊息之後，下一個要動手的是誰？. The default `--variant both` runs both, reports both in full, and judges each model on the **better** variant: C2 PASS first, then the higher route+wake correct count, and `orig` on a tie. The output names the variant it used.

Each case runs `--repeats` times (default 3). With both variants and one model that is 8 x 3 x 2 = 48 requests for set 1, or 20 x 3 x 2 = 120 for set 2.

The header prints `set=<n> question_set_sha256=<hex>`, and the report stores it too. It is the sha256 of the canonical JSON (`sort_keys=True, ensure_ascii=False, separators=(",",":")`) of the set's cases (id, state as sent, expected answers) plus each variant's questions (instructions and criteria). The same hash means the same questions.

| set | question_set_sha256 |
|---|---|
| 1 | `659c6638c19424086c41a0b676b3f201e91c062893d49b42e7642fc414cc1b26` |
| 2 | `3e499742a9148e5e8412ee9186b5dc5dd9a3d72970ad8ee42bd4413e6c31ce81` | Every `--model` is judged on its own.

Before anything is sent, the question set is checked: every question must have non-empty `instructions`, and a noul must also have `criteria.true` and `criteria.false`. The cloud API returns 400 otherwise. If the check fails, the run ends with `RESULT: FAIL (config error, nothing sent ...)`.

`--ping` also sends the Ollama-blog billing ticket once per model. It is a connectivity check only and is not scored.

## Criteria (per model)
Thresholds are ratios of the set size. The table shows set 1; set 2 thresholds are in the table below it.
| | rule | verdict |
|---|---|---|
| C1 connect | >= 7/8 of requests return HTTP 200, and every 200 response passes the schema check: all probabilities in [0,1], probabilities sum to 1 +- 0.02 | PASS/FAIL/BLOCKED |
| C2 correct | route >= 7/8 AND wake >= 7/8 AND urgency argmax within 1 level for every case. The modal answer over the repeats is used | PASS/FAIL/BLOCKED |
| C3 stable | top answers identical across all repeats for >= 90% of units. `--stable-unit pair` (default: 24 pairs = 8 cases x 3 questions) or `case`. Both numbers are always reported | PASS/FAIL/BLOCKED |
| C4 latency | p50/p95, with and without the model's first call (model load) | report only |
| C5 cost | input/output token totals (credits are not looked up). Local line: `--mem-note` text | report only |
| C6 security | stdout and the JSON report are scanned for the key string. Any hit is FAIL | PASS/FAIL |

| threshold | set 1 (8 cases) | set 2 (20 cases) |
|---|---|---|
| C1: HTTP 200 share | >= 7/8 of requests | >= 18/20 of requests |
| C2: route and wake | >= 7/8 cases correct (each) | >= 18/20 cases correct (each) |
| C2: urgency | every case within 1 level | every case within 1 level |
| C3 (pair unit) | >= 90% of 24 pairs (22) | >= 54/60 pairs |

Set 2 adds a report-only section, **`WAKE-ACCEPTANCE (report only)`**, which does not affect any verdict. For cases 3, 4 and 5 (acceptance-bound messages: gate PR ready, implementation PR waiting, branch updated) it lists, per variant, the majority wake answer, the yes votes and the mean noul.

**A model can be added when C1, C2, C3 and C6 are all PASS.**

BLOCKED covers these cases:
- the endpoint is unreachable
- HTTP 401, 402 or 403 (with no key the cloud returns 403 "Must supply an API key!")
- the key is missing
- the model is not pulled
- `/v1/systemone` returns 404, or Ollama is older than 0.35
- HTTP 429 or 529 again after one retry
- a key would be sent over plain http to a non-loopback host

Just before the RESULT line, the script prints one line per model:
```
MODEL VERDICT <model>: PASS|FAIL|BLOCKED (variant=<orig|B>; failed=<C1,C2,..|none>)
```
The last line of output is one of:
- `RESULT: PASS (models passing: <list>)` (exit 0) if **any** model passes, even when other models fail or are blocked.
- `RESULT: FAIL (...)` (exit 1) if no model passes and at least one fails.
- `RESULT: BLOCKED (...)` (exit 2) if every model is blocked. A JSON report goes to `--out` (default `jev_report.json`). Console output is ASCII only, and the key is never printed or written.

## Windows / PowerShell
```powershell
cd C:\path\to\hello
py -3 .\tools\jev_smoke.py --self-test            # fake server on 127.0.0.1; must end with RESULT: PASS (self-test: ...)
```

### Line B - local Ollama
```powershell
ollama --version                  # need 0.35+
ollama pull tev1:0.8b
ollama pull tev1
ollama pull nimble
py -3 .\tools\jev_smoke.py --line ollama --model "tev1:0.8b" --model tev1 --model nimble `
    --mem-note "ollama ps: <paste size>" --out .\jev_report_ollama.json
$LASTEXITCODE                     # 0 = at least one model PASS / 1 FAIL / 2 BLOCKED
```
Timeouts: the default is 120 s per request (`--timeout`). The first call to each model includes the model load time, so C4 reports latency both with and without it. If Ollama runs on another host, use `--base-url http://<host>:11434`. A missing model is reported as BLOCKED with the hint `ollama pull <model>`.

### Line A - TypeSafe cloud (credit-only key)
The key file is **one line** (`apikey_...`, 108 chars). The script reads the first non-empty line and strips it. UTF-8, UTF-8 with BOM, and UTF-16 with BOM (Notepad "Unicode") all work. If the format looks different, the script prints a warning (never the key) and continues.
```powershell
py -3 .\tools\jev_smoke.py --line cloud --key-file C:\secrets\typesafe_key.txt --out .\jev_report_cloud.json
$LASTEXITCODE
```
You can set `$env:TYPESAFE_API_KEY` instead of `--key-file`. Keep the key out of command lines and history. The ollama line never sends `TYPESAFE_API_KEY`.

### Useful flags
- `--set 1|2` (default 1). For example, add `--set 2` to either line's command to run the 20-case set.
- `--variant orig|B|both`, `--repeats N`, `--stable-unit pair|case`
- `--case <id>` (repeatable; the ids belong to the chosen `--set` and are listed in the report's `case_ids`)
- `--ping`
- `--skip-preflight`
- `--dry-run` prints the payload and sends nothing (exits BLOCKED by design)

## Notes
- Cloud facts and their sources:
  - typesafe-sdk 0.7.2 (`constants.py`): `DEFAULT_BASE_URL="https://api.typesafe.ai"`, `DEFAULT_MODEL="jev-latest"`
  - typesafe-sdk 0.7.2 (`_core/transport.py`): `Authorization: Bearer <key>`
  - `https://api.typesafe.ai/openapi.json`: `HTTPBearer`
  - `https://docs.typesafe.ai/api.md`
- The status code for an exhausted credit balance is not documented. The script maps 401, 402 and 403 to BLOCKED. Any other non-2xx is a FAIL, and the masked body is shown.
- TypeSafe docs say accuracy is best in English and that CJK is "handled but not equally well". A C2 FAIL can be a model-quality result even when C1 shows the line works.
