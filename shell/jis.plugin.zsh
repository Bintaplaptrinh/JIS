# Compatibility entry point for existing source-checkout installations.
[[ -o interactive ]] || return 0
[[ -n ${_JIS_LOADED:-} ]] && return 0
export PYTHONPATH="${${(%):-%N}:A:h:h}/src${PYTHONPATH:+:$PYTHONPATH}"
source "${${(%):-%N}:A:h:h}/src/jis/jis.plugin.zsh"
