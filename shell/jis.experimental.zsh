# Laya profile: source from conda activate bqp. Model loads lazily in a process.
[[ -o interactive ]] || return 0
if [[ -n ${_JIS_LOADED:-} ]]; then
  print -u2 -- 'JIS: open a fresh shell before selecting the experimental profile.'
  return 1
fi
typeset -g _JIS_EXPERIMENT_ROOT=${${(%):-%N}:A:h:h}
export JIS_STATE_DIR="$_JIS_EXPERIMENT_ROOT/.runtime/laya-state"
export JIS_PYTHON=${JIS_PYTHON:-${commands[python]:-${commands[python3]}}}
"$_JIS_EXPERIMENT_ROOT/bin/jis" start \
  --laya-checkpoint "${JIS_LAYA_CHECKPOINT:-$_JIS_EXPERIMENT_ROOT/models/laya-base}" \
  --laya-device "${JIS_LAYA_DEVICE:-auto}" \
  --laya-threads "${JIS_LAYA_THREADS:-2}" \
  --laya-mode "${JIS_LAYA_MODE:-assist}" \
  --laya-idle "${JIS_LAYA_IDLE:-120}" >/dev/null || return 1
source "$_JIS_EXPERIMENT_ROOT/shell/jis.plugin.zsh"
