# JIS v0.1 architecture

```text
zsh / ZLE (one session ID per shell)
    native Unix socket: async suggest, bounded sync correction at Enter
        one daemon per Unix user, flock startup lock
            validated Context
                TypoProvider + HistoryProvider
                deterministic Policy filter
                HeuristicRanker + optional Laya process
                ambiguity threshold -> Decision or abstain
            HistoryStore (SQLite WAL, bounded rows)
    Decision -> ghost text / yes-no confirmation -> BUFFER only
```

## Component boundaries

`types.py` contains portable input/output DTOs and Provider/Ranker protocols.
`providers.py` generates spelling corrections and retrieves successful prefix
history. `policy.py` constrains learning and suggestions. `rankers.py` scores
surviving candidates. `engine.py` composes these stages and handles abstention.
`store.py` owns indexed persistence. `daemon.py` owns scheduling and lifetime;
`protocol.py` defines transport; `shell/` owns the editable-buffer UX.

Core has no shell execution API. The optional git-alias probe is a bounded,
read-only `git config --get-regexp` subprocess, not an execution of user input.
Ranker scores are utilities, not calibrated probabilities.

## Context and resource limits

- One daemon, one fast engine worker and one optional model process; asyncio
  handles up to 128 connections. Control operations bypass model work.
  Only one model inference can be in flight; busy/deadline (75ms) requests
  use heuristic results. Native inference has a 3s watchdog; process termination releases runtime memory.
- Each shell sends session ID, execution CWD, current CWD, previous successful
  command, PATH and known aliases/functions/builtins. Requests use snapshots;
  stale suggestions cannot replace a newer buffer.
- Shell allows one suggestion request in flight and coalesces edits. There is
  no process per keystroke, per executed command, or per terminal held alive.
- History: 20,000 observations maximum; retrieval samples at most 384 rows from
  session, CWD, previous-command and global prefix indexes. Frequent older rows
  outside this sample do not contribute to the score.
- Candidates: at most 8 typo results; history candidates are bounded by sample.
- Frame: 32 KiB; buffer: 4 KiB; queue: 128 engine requests; shell-name list: 4096.
  Zsh limits its normal command registry to 4096 characters and excludes
  internal completion functions; an exact typed alias/function is added during
  correction checking. This supports large completion frameworks without
  exceeding the transport frame. Oversized JSON candidate evidence is omitted.
- PATH cache: 16 directory sets, 30s TTL, at most 20,000 scanned entries per set.
  Git-alias cache: 32 contexts, 30s TTL, 60ms timeout, 32KiB output limit.
  The helper executable is resolved from daemon startup PATH, never request PATH.
- Idle connection timeout: 30 minutes; shell reconnects after an EOF.
- Enter correction timeout: 120ms after connection; cold connection greeting
  timeout: 150ms. Daemon failure/timeouts let the original zsh widget proceed.
  Request reads have a 30ms bound; command-record acknowledgements at most 120ms.
- SQLite WAL prevents a reader from blocking writers; operations serialize
  through one worker. Indexed history pruning bounds rows. File size tracks the
  longest retained commands, not a fixed few-megabyte budget.

Session weight is deliberately stronger than frequency for concurrent work;
same-directory matching outranks history from another directory. This is task
context from observed shell behavior, not inferred intent from arbitrary prose.

## Transport v1 (migration boundary)

Canonical API is UTF-8 JSON Lines over a private Unix socket. Example:

```json
{"id":"17","op":"correct","session":"terminal-a","cwd":"/work/project","previous":"git diff","buffer":"gti status","path":"/usr/bin:/bin","known":["cd","my_function"]}
```

Operations: `hello`, `ping`, `stats`, `suggest`, `correct`, `record`, `stop`.
`record` uses `buffer` as the executed command plus `status` (0..255).
`hello` registers valid shell commands for the connection. `known` may be sent
with another request to refresh these names. Responses echo `id`.

```json
{"id":"17","kind":"correction","command":"git status","score":0.7833,"reason":"typo","candidates":[]}
```

The fork-free zsh adapter uses the same DTOs as nine tab-separated fields in
this order: `id,op,session,cwd,previous,buffer,status,path,known`.
Every field starts with `=` (empty is `=`), followed by percent-escaped text.
Escape `%` -> `%25`, TAB -> `%09`, LF -> `%0A`, CR -> `%0D` in that order.
`known` is newline-separated names before escaping. Response fields are
`id,kind,command,reason`, encoded the same way. There is no eval/source of replies.

Replace the daemon with Rust/Go while retaining this contract and the zsh
adapter. Port providers, policies and rankers independently, or host a Python
model behind a separate optional process. Keep test fixtures and behavior.

## Adaptive Laya runtime

`resources.py` is a standard-library Linux probe plus pure ResourcePolicy.
`model_runtime.py` owns admission/hysteresis, bounded exact-context cache,
process lifetime and private JSON Lines IPC. `laya_worker.py` alone imports
ML libraries and an offline, SHA256-checked local Laya Agent. The daemon
retains Engine/SQLite and serves shell/control traffic independently.

Lifecycle: unloaded -> stable resource admission after correction demand ->
loading/warmup -> ready -> evicting -> cooldown -> unloaded. Idle, RAM/VRAM/PSI
pressure and sustained CPU/GPU load evict the process. A request cannot force
loading without admission. No prediction queue is built while busy. A late
result may serve only the exact bound context from a 32-entry, 30s cache.
JIS does not deliberately log prediction state. Private model diagnostics
may come from the SDK; the prediction cache has no disk persistence.

Fast UI deadline is 75ms, hard inference watchdog 3s, loading watchdog 90s.
Termination has a 300ms grace period then kill/reap. Linux parent-death signal
prevents model orphans. Eager backend, CUDA autocast fp16 by default,
no torch.compile, TileLang, pickle,
remote code or auto-downloads. Both named checkpoints are supported; defaults
use base, device auto, two CPU math threads and 120s idle release. Admission
thresholds and UX setup are in README; policy can be replaced independently.

All model replies require valid choice IDs, finite probability distributions,
max-probability answer_confidence, no truncation/collapsed options and strong
confidence/margin. Strong heuristic corrections retain priority. A model
can only break weak spelling ties among filtered candidates; no execution.
Shadow mode uses the same inference/lifecycle without changing the decision.

See [measured results](laya-results.md), [lifecycle observation](laya-lifecycle.json),
[security review](security-review.md). Historical Reflex measurements remain
for comparison but its adapter, checkpoint and scripts have been removed.

Primary sources inspected 2026-10-11:
- https://huggingface.co/convaiinnovations/laya
- https://huggingface.co/convaiinnovations/laya-typed-decisions
- https://github.com/NandhaKishorM/laya

Reference zsh projects informed the original requirements; no implementation
from those terminal projects was copied.
