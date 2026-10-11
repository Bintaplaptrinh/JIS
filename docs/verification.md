# Verification — 2026-10-10

Interpreter: `/home/tuanphat/anaconda3/envs/bqp/bin/python`, Python 3.12.14,
activated with `conda activate bqp`. zsh 5.9 on the user's Linux machine.

- 18 core/protocol tests passed (`python -m unittest discover -s tests -v`).
- 12 integration tests passed (`python tests/integration_zsh.py`). These run
  real zsh/ZLE in pseudo-terminals against a daemon with an isolated temporary
  state directory. Coverage includes yes/no/cancel, fill-only behavior,
  bypass, private history rules, per-terminal context, malformed clients,
  32 connections sharing a PID/worker, existing autosuggestions, and a registry
  containing 2,000 completion functions plus a valid internal user function.
- `zsh -n shell/jis.plugin.zsh` passed.
- Python compilation passed.
- Separate verification sourced the machine's real `/home/tuanphat/.zshrc`,
  activated `bqp` and loaded JIS, with isolated test history. `gti status` showed
  `Do you mean git status`; `yes` filled `BUFFER=git status` without running it;
  Ctrl-Space filled a previously successful `echo` command. All three passed.
- Daemon benchmark: [benchmark.json](benchmark.json). Uses 6,000 synthetic
  observations, persistent socket connections and 16 concurrent querying
  clients. RSS excludes shell/terminal memory; CPU measurements use Linux
  process counters and are rounded to the kernel clock tick.

No model weights were downloaded. The default ranker and Reflex abstention
fallback were tested; actual Reflex-S1 inference was not tested. No changes
were made to the user's `.zshrc`. The default local JIS daemon remains running
for interactive use.
