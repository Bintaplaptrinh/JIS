"""Source the experimental profile with the user's real zshrc, in an isolated PTY."""
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]


def main():
    helpers=runpy.run_path(str(ROOT/"tests/integration_zsh.py"))
    Terminal,rpc=helpers["Terminal"],helpers["rpc"]
    with tempfile.TemporaryDirectory(prefix="jis-laya-live-") as directory:
        rc="""source /home/tuanphat/.zshrc
source /home/tuanphat/anaconda3/etc/profile.d/conda.sh
conda activate bqp
source %s/shell/jis.experimental.zsh
PROMPT='JIS> '
RPROMPT=''
_jis_inspect() { print -r -- "JIS_BUFFER:$BUFFER"; zle -R; }
zle -N jis-inspect _jis_inspect
bindkey '^T' jis-inspect
""" % ROOT
        (Path(directory)/".zshrc").write_text(rc)
        terminal=Terminal({**os.environ,"ZDOTDIR":directory,"TERM":"xterm-256color","JIS_PYTHON":sys.executable})
        state=ROOT/".runtime/laya-state"
        try:
            terminal.send("git statsu\r")
            terminal.read_until("Do you mean git status")
            terminal.send("yes\r")
            terminal.read_until("filled only")
            assert "JIS_BUFFER:git status" in terminal.inspect()
            terminal.send("\x03"); terminal.read_until("JIS> "); terminal.drain()
            deadline=time.monotonic()+90
            while rpc(state,{"op":"stats"})["model_status"]!="ready":
                if time.monotonic()>deadline:
                    raise RuntimeError("Laya not admitted/loaded: "+str(rpc(state,{"op":"stats"})))
                time.sleep(.1)
            # Same actual terminal, now served by the ready model rather than cold fallback.
            terminal.send("git statsu\r"); terminal.read_until("Do you mean git status")
            terminal.send("yes\r"); terminal.read_until("filled only")
            assert "JIS_BUFFER:git status" in terminal.inspect()
            terminal.send("\x03"); terminal.read_until("JIS> "); terminal.drain()
            terminal.send("ehco JIS_LAYA_FILL_ONLY\r")
            terminal.read_until("Do you mean echo JIS_LAYA_FILL_ONLY")
            terminal.send("yes\r")
            output=terminal.read_until("filled only")+terminal.drain()
            assert "\r\nJIS_LAYA_FILL_ONLY\r\n" not in output
            assert "JIS_BUFFER:echo JIS_LAYA_FILL_ONLY" in terminal.inspect()
            terminal.send("\x03")
            status=rpc(state,{"op":"stats"})
            assert status["ranker"]=="LayaAdaptive" and status["model_calls"]>=1
            result={"real_zshrc":True,"conda":"bqp","experimental_profile":True,"cold_fallback":True,
                    "ready_model_verified":True,"yes_only_fills":True,"stats":status}
            (ROOT/"docs/laya-live-smoke.json").write_text(json.dumps(result,indent=2)+"\n")
            print("PASS: real .zshrc, lazy cold fallback, ready Laya, yes fills without execution",flush=True)
            print(json.dumps(status,indent=2))
        finally:
            terminal.close()


if __name__=="__main__":
    main()
