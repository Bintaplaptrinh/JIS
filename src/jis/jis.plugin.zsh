# JIS v1: native socket transport, no Python subprocess per key/command.
[[ -o interactive ]] || return 0
[[ -n ${_JIS_LOADED:-} ]] && return 0
typeset -g JIS_PYTHON=${JIS_PYTHON:-${commands[python]:-${commands[python3]}}}
typeset -g JIS_STATE_DIR=${JIS_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/jis}
typeset -g JIS_SESSION="${$}-${EPOCHSECONDS:-0}-${RANDOM}-${RANDOM}"
export JIS_PYTHON JIS_STATE_DIR JIS_SESSION
zmodload zsh/net/socket || return 1
zmodload zsh/datetime
autoload -Uz add-zsh-hook add-zle-hook-widget

# Python launches once at source time; a file lock prevents duplicate daemons.
"$JIS_PYTHON" -m jis start >/dev/null || return 1
typeset -g _JIS_LOADED=1 _JIS_FD='' _JIS_PREVIOUS='' _JIS_RUNNING=''
typeset -g _JIS_RUNNING_CWD='' _JIS_SUGGESTION='' _JIS_KIND='' _JIS_CONFIRM=''
typeset -g _JIS_SENT_BUFFER='' _JIS_SENT_CWD='' _JIS_SENT_PREVIOUS='' _JIS_SENT_PATH=''
typeset -g _JIS_LAST_BUFFER='' _JIS_LAST_CWD='' _JIS_LAST_PATH=''
typeset -ga _JIS_CANDIDATES=()
typeset -gi _JIS_ID=0 _JIS_BUSY=0 _JIS_ENABLED=1 _JIS_SELECTED=1 _JIS_MENU_VISIBLE=0
typeset -gi _JIS_TABLE_ENABLED=1
[[ ${JIS_SUGGEST_TABLE:-1} == 0 ]] && _JIS_TABLE_ENABLED=0

_jis_encode() {
  REPLY="=$1"
  REPLY=${REPLY//\%/\%25}
  REPLY=${REPLY//$'\t'/\%09}
  REPLY=${REPLY//$'\n'/\%0A}
  REPLY=${REPLY//$'\r'/\%0D}
}

_jis_decode() {
  REPLY=${1#=}
  REPLY=${REPLY//\%09/$'\t'}
  REPLY=${REPLY//\%0A/$'\n'}
  REPLY=${REPLY//\%0D/$'\r'}
  REPLY=${REPLY//\%25/\%}
}

_jis_disconnect() {
  if [[ -n $_JIS_FD ]]; then
    zle -F $_JIS_FD 2>/dev/null
    exec {_JIS_FD}>&-
  fi
  _JIS_FD='' _JIS_BUSY=0
}

_jis_send() {
  local op=$1 buffer=$2 code=${3:-0} names=${4:-} field REPLY frame=''
  local LC_ALL=C
  # Enforce byte limits before writing to a blocking socket, including paste.
  (( ${#buffer} <= 4096 && ${#PWD} <= 4096 && ${#PATH} <= 8192 && ${#_JIS_PREVIOUS} <= 4096 )) || return 1
  (( ++_JIS_ID ))
  for field in "$_JIS_ID" "$op" "$JIS_SESSION" "$PWD" "$_JIS_PREVIOUS" "$buffer" "$code" "$PATH" "$names"; do
    _jis_encode "$field"
    [[ -z $frame ]] || frame+=$'\t'
    frame+=$REPLY
  done
  (( ${#frame} < 32768 )) || return 1
  print -r -u $_JIS_FD -- "$frame" 2>/dev/null || { _jis_disconnect; return 1; }
}

_jis_known_names() {
  # Completion frameworks register thousands of internal _functions. Keep a
  # bounded registry; the exact typed function/alias is added at Enter below.
  local -a names
  local name
  names=( ${(k)builtins} ${(k)aliases} ${${(k)functions}:#_*} )
  REPLY=''
  for name in "${names[@]}"; do
    (( ${#REPLY} + ${#name} < 4096 )) || break
    REPLY+="$name"$'\n'
  done
}

_jis_connect() {
  [[ -n $_JIS_FD ]] && return 0
  local REPLY names
  zsocket "$JIS_STATE_DIR/jis.sock" 2>/dev/null || return 1
  _JIS_FD=$REPLY
  # Aliases and functions are valid commands, even if absent from PATH.
  _jis_known_names
  names=$REPLY
  _jis_send hello '' 0 "$names" || { _jis_disconnect; return 1; }
  local line
  read -r -t 0.15 -u $_JIS_FD line || { _jis_disconnect; return 1; }
  _jis_parse "$line" && [[ $_JIS_RESPONSE_KIND == ok ]] || { _jis_disconnect; return 1; }
}

_jis_parse() {
  local line=$1 REPLY
  local -a fields
  fields=( "${(@ps:\t:)line}" )
  (( ${#fields} == 4 || ${#fields} == 5 )) || return 1
  local field
  for field in "${fields[@]}"; do
    [[ $field == '='* ]] || return 1
  done
  _jis_decode "$fields[1]"
  [[ $REPLY == <-> ]] || return 1
  _JIS_RESPONSE_ID=$REPLY
  _jis_decode "$fields[2]"; _JIS_RESPONSE_KIND=$REPLY
  case $_JIS_RESPONSE_KIND in
    ok|ignored|none|completion|correction) ;;
    *) return 1 ;;
  esac
  _jis_decode "$fields[3]"; _JIS_RESPONSE_COMMAND=$REPLY
  [[ $_JIS_RESPONSE_COMMAND != *[[:cntrl:]]* ]] || return 1
  _JIS_RESPONSE_CANDIDATES=()
  if (( ${#fields} == 5 )); then
    _jis_decode "$fields[5]"
    _JIS_RESPONSE_CANDIDATES=( "${(@f)REPLY}" )
    local candidate
    for candidate in "${_JIS_RESPONSE_CANDIDATES[@]}"; do
      [[ $candidate != *[[:cntrl:]]* ]] || return 1
    done
  fi
}

_jis_clear() {
  _JIS_SUGGESTION='' _JIS_KIND=''
  _JIS_CANDIDATES=() _JIS_SELECTED=1
  if (( _JIS_MENU_VISIBLE )); then
    zle -M '' 2>/dev/null
    _JIS_MENU_VISIBLE=0
  fi
  POSTDISPLAY=''
  if [[ -n ${_JIS_HIGHLIGHT:-} ]]; then
    region_highlight=("${(@)region_highlight:#$_JIS_HIGHLIGHT}")
    _JIS_HIGHLIGHT=''
  fi
}

_jis_show_table() {
  (( _JIS_TABLE_ENABLED && ${#_JIS_CANDIDATES} )) || return 0
  local message='JIS suggestions (↑/↓ select, Ctrl-Space fill)' item display
  local -i i=0 width=$(( COLUMNS > 8 ? COLUMNS - 4 : 4 ))
  for item in "${_JIS_CANDIDATES[@]}"; do
    (( ++i ))
    display=${item[1,$width]}
    display=${display//\%/%%}
    if (( i == _JIS_SELECTED )); then
      message+=$'\n'"> $display"
    else
      message+=$'\n'"  $display"
    fi
  done
  zle -M "$message"
  _JIS_MENU_VISIBLE=1
}

_jis_move_selection() {
  if (( _JIS_TABLE_ENABLED && ${#_JIS_CANDIDATES} )) && [[ $BUFFER == $_JIS_SENT_BUFFER && $PWD == $_JIS_SENT_CWD && $PATH == $_JIS_SENT_PATH && $_JIS_PREVIOUS == $_JIS_SENT_PREVIOUS ]]; then
    (( _JIS_SELECTED = (_JIS_SELECTED - 1 + $1 + ${#_JIS_CANDIDATES}) % ${#_JIS_CANDIDATES} + 1 ))
    _JIS_SUGGESTION=$_JIS_CANDIDATES[$_JIS_SELECTED]
    POSTDISPLAY=${_JIS_SUGGESTION[${#BUFFER}+1,-1]}
    region_highlight=("${(@)region_highlight:#$_JIS_HIGHLIGHT}")
    _JIS_HIGHLIGHT="${#BUFFER} $(( ${#BUFFER} + ${#POSTDISPLAY} )) fg=8"
    region_highlight+=("$_JIS_HIGHLIGHT")
    _jis_show_table
  else
    if (( $1 < 0 )); then zle up-line-or-history; else zle down-line-or-history; fi
  fi
}
_jis_up() { _jis_move_selection -1; }
_jis_down() { _jis_move_selection 1; }

_jis_receive() {
  local line
  if [[ -n $2 ]]; then
    _jis_disconnect
    _jis_clear
    return
  fi
  read -r -t 0.03 -u $_JIS_FD line || { _jis_disconnect; _jis_clear; return; }
  _jis_parse "$line" || { _jis_disconnect; _jis_clear; return; }
  [[ $_JIS_RESPONSE_ID == $_JIS_ID ]] || return
  _JIS_BUSY=0
  if [[ $BUFFER == $_JIS_SENT_BUFFER && $PWD == $_JIS_SENT_CWD && $PATH == $_JIS_SENT_PATH && $_JIS_PREVIOUS == $_JIS_SENT_PREVIOUS ]]; then
    _JIS_SUGGESTION=$_JIS_RESPONSE_COMMAND _JIS_KIND=$_JIS_RESPONSE_KIND
    if [[ $_JIS_KIND == completion && $_JIS_SUGGESTION == "$BUFFER"* && -n $BUFFER ]]; then
      local candidate
      _JIS_CANDIDATES=()
      for candidate in "${_JIS_RESPONSE_CANDIDATES[@]}"; do
        [[ $candidate == "$BUFFER"* && $candidate != "$BUFFER" ]] && _JIS_CANDIDATES+=("$candidate")
      done
      (( ${#_JIS_CANDIDATES} )) || _JIS_CANDIDATES=("$_JIS_SUGGESTION")
      _JIS_SELECTED=1
      _JIS_SUGGESTION=$_JIS_CANDIDATES[1]
      POSTDISPLAY=${_JIS_SUGGESTION[${#BUFFER}+1,-1]}
      _JIS_HIGHLIGHT="${#BUFFER} $(( ${#BUFFER} + ${#POSTDISPLAY} )) fg=8"
      region_highlight+=("$_JIS_HIGHLIGHT")
      _jis_show_table
    else
      POSTDISPLAY=''
    fi
  else
    _JIS_LAST_BUFFER=''  # coalesce edits while one request was in flight
    _jis_redraw
  fi
  zle -R
}

_jis_redraw() {
  (( _JIS_ENABLED )) || return 0
  [[ -z $_JIS_CONFIRM ]] || return 0
  if [[ $BUFFER == $_JIS_LAST_BUFFER && $PWD == $_JIS_LAST_CWD && $PATH == $_JIS_LAST_PATH ]]; then
    return 0
  fi
  _jis_clear
  (( _JIS_BUSY )) && return 0
  # Don't send blank, multiline, very long or space-prefixed/private commands.
  [[ -n $BUFFER && $BUFFER != [[:space:]]* && $BUFFER != *$'\n'* && ${#BUFFER} -le 4096 ]] || return 0
  [[ -z ${HISTORY_IGNORE:-} || $BUFFER != ${~HISTORY_IGNORE} ]] || return 0
  _jis_connect || return 0
  _JIS_SENT_BUFFER=$BUFFER _JIS_SENT_CWD=$PWD _JIS_SENT_PREVIOUS=$_JIS_PREVIOUS _JIS_SENT_PATH=$PATH
  _JIS_LAST_BUFFER=$BUFFER _JIS_LAST_CWD=$PWD _JIS_LAST_PATH=$PATH
  _jis_send suggest "$BUFFER" || return 0
  _JIS_BUSY=1
  zle -F -w $_JIS_FD jis-socket-response
}

_jis_correct_now() {
  [[ -z ${HISTORY_IGNORE:-} || $BUFFER != ${~HISTORY_IGNORE} ]] || return 1
  _jis_connect || return 1
  zle -F $_JIS_FD 2>/dev/null
  local REPLY names head
  local fallback=''
  if [[ $_JIS_KIND == correction && $BUFFER == $_JIS_SENT_BUFFER && $PWD == $_JIS_SENT_CWD && $PATH == $_JIS_SENT_PATH ]]; then
    fallback=$_JIS_SUGGESTION
  fi
  local -a tokens
  _jis_known_names
  names=$REPLY
  tokens=( ${(z)BUFFER} )
  head=${(Q)tokens[1]}
  if [[ -n $head ]] && (( $+functions[$head] || $+aliases[$head] )); then
    names+="$head"$'\n'
  fi
  _jis_send correct "$BUFFER" 0 "$names" || return 1
  local target=$_JIS_ID line
  local -F deadline=$(( EPOCHREALTIME + 0.12 )) remaining
  while (( EPOCHREALTIME < deadline )); do
    remaining=$(( deadline - EPOCHREALTIME ))
    read -r -t $remaining -u $_JIS_FD line || break
    _jis_parse "$line" || continue
    if [[ $_JIS_RESPONSE_ID != $target ]]; then
      if [[ $_JIS_RESPONSE_KIND == correction && $BUFFER == $_JIS_SENT_BUFFER && $PWD == $_JIS_SENT_CWD && $PATH == $_JIS_SENT_PATH ]]; then
        fallback=$_JIS_RESPONSE_COMMAND
      fi
      continue
    fi
    _JIS_BUSY=0
    if [[ $_JIS_RESPONSE_KIND == correction && -n $_JIS_RESPONSE_COMMAND ]]; then
      _JIS_SUGGESTION=$_JIS_RESPONSE_COMMAND _JIS_KIND=correction
      return 0
    fi
    return 1
  done
  # On timeout, close so an old response cannot attach to a future input.
  _jis_disconnect
  if [[ -n $fallback ]]; then
    _JIS_SUGGESTION=$fallback _JIS_KIND=correction
    return 0
  fi
  return 1
}

_jis_accept_line() {
  if [[ -n $_JIS_CONFIRM ]]; then
    case ${(L)BUFFER} in
      yes|y)
        BUFFER=$_JIS_CONFIRM
        CURSOR=${#BUFFER}
        _JIS_CONFIRM=''
        _jis_clear
        _JIS_LAST_BUFFER=$BUFFER _JIS_LAST_CWD=$PWD _JIS_LAST_PATH=$PATH
        zle -M 'JIS: filled only. Edit the command, then press Enter to execute.'
        ;;
      no|n)
        BUFFER=$_JIS_ORIGINAL CURSOR=${#_JIS_ORIGINAL}
        _JIS_CONFIRM=''
        _jis_clear
        zle -M 'JIS: original command restored. Ctrl-X Enter bypasses correction.'
        ;;
      *) zle -M "Do you mean $_JIS_CONFIRM ? Type yes or no, then Enter." ;;
    esac
    return 0
  fi
  if (( _JIS_ENABLED )) && [[ -n $BUFFER && $BUFFER != [[:space:]]* ]] && _jis_correct_now; then
    _JIS_ORIGINAL=$BUFFER _JIS_CONFIRM=$_JIS_SUGGESTION
    BUFFER='' CURSOR=0
    _jis_clear
    zle -M "Do you mean $_JIS_CONFIRM ? Type yes or no, then Enter."
    return 0
  fi
  _jis_clear
  zle jis-original-accept-line
}

_jis_fill() {
  [[ -z $_JIS_CONFIRM ]] || return 0
  if [[ $_JIS_KIND == completion && $_JIS_SUGGESTION == "$BUFFER"* && $BUFFER == $_JIS_SENT_BUFFER && $PWD == $_JIS_SENT_CWD && $PATH == $_JIS_SENT_PATH && $_JIS_PREVIOUS == $_JIS_SENT_PREVIOUS ]]; then
    BUFFER=$_JIS_SUGGESTION CURSOR=${#_JIS_SUGGESTION}
    _jis_clear
  fi
}

_jis_bypass() {
  [[ -z $_JIS_CONFIRM ]] || { BUFFER=$_JIS_ORIGINAL; _JIS_CONFIRM=''; }
  _jis_clear
  zle jis-original-accept-line
}

_jis_cancel() {
  if [[ -n $_JIS_CONFIRM ]]; then
    BUFFER=$_JIS_ORIGINAL CURSOR=${#_JIS_ORIGINAL}
    _JIS_CONFIRM=''
  fi
  _jis_clear
  zle -M 'JIS: suggestion dismissed.'
}

_jis_line_finish() {
  _jis_clear
  [[ -z $_JIS_CONFIRM ]] || _JIS_CONFIRM=''
  [[ -z $_JIS_FD ]] || zle -F $_JIS_FD 2>/dev/null
  _JIS_LAST_BUFFER='' _JIS_BUSY=0
}

_jis_preexec() {
  _JIS_RUNNING=$1 _JIS_RUNNING_CWD=$PWD
  if [[ $1 == [[:space:]]* || ( -n ${HISTORY_IGNORE:-} && $1 == ${~HISTORY_IGNORE} ) ]]; then
    _JIS_RUNNING='' _JIS_PREVIOUS=''
  fi
}

_jis_precmd() {
  local code=$? line saved_cwd=$PWD
  if [[ -n $_JIS_RUNNING ]] && _jis_connect; then
    # A cd changes PWD before precmd. Record the directory of execution.
    local PWD=$_JIS_RUNNING_CWD
    _jis_send record "$_JIS_RUNNING" "$code" || { _JIS_RUNNING='' _JIS_PREVIOUS=''; return 0; }
    # Ack may follow a previous async response. Read only a small bounded batch.
    local target=$_JIS_ID i
    for i in {1..4}; do
      read -r -t 0.03 -u $_JIS_FD line || break
      _jis_parse "$line" && [[ $_JIS_RESPONSE_ID == $target ]] && break
    done
    if (( code == 0 )) && [[ $_JIS_RESPONSE_ID == $target && $_JIS_RESPONSE_KIND == ok ]]; then
      _JIS_PREVIOUS=$_JIS_RUNNING
    else
      _JIS_PREVIOUS=''
    fi
  fi
  _JIS_RUNNING='' _JIS_LAST_BUFFER='' _JIS_BUSY=0
}

jis-on() { _JIS_ENABLED=1; }
jis-off() { _JIS_ENABLED=0; _jis_disconnect; }
jis-table-on() { _JIS_TABLE_ENABLED=1; _JIS_LAST_BUFFER=''; }
jis-table-off() { _JIS_TABLE_ENABLED=0; _JIS_LAST_BUFFER=''; }
jis-status() { "$JIS_PYTHON" -m jis status; }
jis-refresh() { _jis_disconnect; _jis_connect; _JIS_LAST_BUFFER=''; }

# Disable the existing autosuggestion renderer for this shell only. JIS owns
# POSTDISPLAY; reloading .zshrc or opening another shell restores that plugin.
(( $+functions[_zsh_autosuggest_disable] )) && _zsh_autosuggest_disable
if (( $+functions[_zsh_autosuggest_start] )); then
  typeset -g ZSH_AUTOSUGGEST_MANUAL_REBIND=1
  add-zsh-hook -d precmd _zsh_autosuggest_start
fi

zle -A accept-line jis-original-accept-line
zle -N accept-line _jis_accept_line
zle -N jis-fill _jis_fill
zle -N jis-up _jis_up
zle -N jis-down _jis_down
zle -N jis-bypass _jis_bypass
zle -N jis-cancel _jis_cancel
zle -N jis-socket-response _jis_receive
bindkey '^X^J' jis-bypass
bindkey '^X^M' jis-bypass
bindkey '^G' jis-cancel
bindkey '^ ' jis-fill
bindkey '^[[A' jis-up
bindkey '^[[B' jis-down
bindkey '^[OA' jis-up
bindkey '^[OB' jis-down
add-zle-hook-widget line-pre-redraw _jis_redraw
add-zle-hook-widget line-finish _jis_line_finish
add-zsh-hook preexec _jis_preexec
add-zsh-hook precmd _jis_precmd
add-zsh-hook zshexit _jis_disconnect
