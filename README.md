# JIS

A local, heuristic-powered smart terminal assistant for zsh. JIS catches command
typos and suggests commands from your successful history, directly in your shell.
It runs on the Python standard library with no API keys, network services, or
model downloads.

## Features

- Correct executable names using your PATH, shell builtins, aliases, and functions.
- Catch common subcommand typos for git, npm, docker, conda, kubectl, and pip.
- Show history suggestions as ghost text, ranked by session, working directory,
  previous command, frequency, and recency.
- Browse a table of matching history commands with the arrow keys and fill the
  selected command with Ctrl-Space.
- Share one local daemon across multiple terminals, with bounded queues, caches,
  and a SQLite history of up to 20,000 observations.
- Review a proposed correction before running it. Accepting a correction only
  fills the command line; press Enter again to execute it.

The current release uses heuristic rules throughout the suggestion pipeline.

## Installation

### Requirements

- Linux (the current runtime uses Linux file and Unix socket facilities).
- Python 3.10 or newer, with `venv` and `pip` for the installation below.
- zsh with the `zsh/net/socket` module.
- Git to clone the repository.

### Install from source

Clone the repository and install it in a virtual environment:

```sh
git clone https://github.com/Bintaplaptrinh/JIS.git
cd JIS
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

In an interactive **zsh** session, run these commands from the repository directory:

```zsh
export JIS_PYTHON="$PWD/.venv/bin/python"
source "$PWD/shell/jis.plugin.zsh"
```

Sourcing the plugin starts the shared daemon automatically. Keep the checkout
in place: the shell plugin and launcher run from this directory.
After updating an existing checkout, run `./bin/jis stop` and open a new shell
so the shared daemon picks up the updated suggestion protocol.

### Enable JIS in every terminal

Add the following lines to `~/.zshrc`, replacing the paths with the absolute path
to your checkout. Load JIS after other shell plugins:

```zsh
export JIS_PYTHON="$HOME/path/to/JIS/.venv/bin/python"
source "$HOME/path/to/JIS/shell/jis.plugin.zsh"
```

Open a new terminal to enable it. If `zsh-autosuggestions` is already loaded,
JIS disables its renderer for that shell so it can display its own ghost text.

## Usage

### Correct a typo

Type `gti status` and press Enter. When the correction is clear, JIS asks:

```text
Do you mean git status ? Type yes or no, then Enter.
```

Type `yes` and press Enter to fill `git status` into the command line. Review or
edit it, then press Enter again to run it. Type `no` and press Enter, or press
Ctrl-G, to restore the original input.

### Complete a command from history

Run `echo jis-demo-one` and `echo jis-demo-two`, then type `echo jis-`. JIS
displays matching commands in a table and the selected command as ghost text.
Use the Up and Down arrow keys to select a match. Press Ctrl-Space to fill it,
then Enter to execute it. With no table visible, the arrow keys navigate shell
history as usual. Use `jis-table-off` to hide the table while keeping ghost
text, and `jis-table-on` to show it again in the current shell.
Suggestions come from successful commands observed after JIS was enabled;
your existing `.zsh_history` is not imported.

| Key or command | Action |
| --- | --- |
| Enter | Check for a clear typo before executing |
| `yes` + Enter | Fill the proposed correction for review |
| `no` + Enter / Ctrl-G | Restore the original input |
| Ctrl-Space | Fill a history suggestion |
| Up / Down | Select a suggestion while the table is visible |
| `jis-table-off` / `jis-table-on` | Hide / show the suggestion table in the current shell |
| Ctrl-X, then Enter | Execute the current input while bypassing correction |
| `jis-off` / `jis-on` | Disable / enable JIS in the current shell |
| `jis-refresh` | Reconnect and refresh known aliases and functions |
| `jis-status` | Show daemon status and history counts |

### Command-line interface

From the checkout, use the launcher with the same Python interpreter:

```sh
export JIS_PYTHON="$PWD/.venv/bin/python"
./bin/jis status
./bin/jis correct 'gti status'
./bin/jis suggest 'echo jis-'
./bin/jis stop
./bin/jis start
```

The virtual environment also provides `.venv/bin/jis`. Run `./bin/jis --help`
or `./bin/jis --usage` for detailed commands, shell controls, and configuration.

## Configuration

Set environment variables **before** sourcing the plugin:

| Variable | Default | Purpose |
| --- | --- | --- |
| `JIS_PYTHON` | `python`, falling back to `python3` | Interpreter used by the launcher |
| `JIS_STATE_DIR` | `${XDG_STATE_HOME:-$HOME/.local/state}/jis` | Local socket, history database, lock, and log directory |
| `JIS_SUGGEST_TABLE` | `1` | Set to `0` to start with the suggestion table hidden |

For example, to use a separate history and daemon:

```zsh
export JIS_STATE_DIR="$HOME/.local/state/jis-work"
export JIS_PYTHON="$HOME/path/to/JIS/.venv/bin/python"
source "$HOME/path/to/JIS/shell/jis.plugin.zsh"
```

If Ctrl-Space is intercepted by your terminal or input method, bind another key
after sourcing the plugin:

```zsh
bindkey '^X^A' jis-fill  # Ctrl-X, then Ctrl-A
```

## Privacy and limitations

JIS stores history locally in plaintext. The state directory uses permissions
`0700`; the socket and database use `0600`. Commands with a leading space,
commands matching zsh's `HISTORY_IGNORE`, control characters, and recognized
secret patterns are excluded from learning. Secret detection is heuristic and
cannot identify every sensitive value; prefix private commands with a space.

JIS handles simple commands. It skips pipelines, redirections, substitutions,
and other complex shell syntax. Subcommand coverage is limited, and ambiguous
corrections are left unchanged. It does not inspect command errors or infer
missing arguments. PATH and git-alias caches refresh after 30 seconds.

History suggestions filter known dangerous command patterns. Typo corrections
change the misspelled token and preserve the arguments you entered. Always
review a command before executing it.

## Troubleshooting

- **The daemon does not start:** check `JIS_PYTHON` and inspect `daemon.log` in
  your state directory. Run `./bin/jis start` to see the error.
- **Suggestions stop appearing:** run `./bin/jis start`, then `jis-refresh` in
  the affected shell. Check that JIS is enabled with `jis-on`.
- **A command keeps triggering correction:** use Ctrl-X, then Enter to run the
  original input. Run `jis-refresh` after adding aliases or functions.
- **Disable JIS permanently:** remove its lines from `~/.zshrc` and open a new
  shell. Run `./bin/jis stop` to stop the shared daemon. `jis-off` only affects
  the current shell.

## Bug reports and contributions

Report bugs or propose features through the
[issue tracker](https://github.com/Bintaplaptrinh/JIS/issues). Include your OS,
Python and zsh versions, a minimal reproduction, and relevant log output with
private information removed.

This repository publishes the official heuristic runtime, shell integration,
installation metadata, and this README. Tests, recipes, research documentation,
notebooks, model checkpoints, generated output, and experimental tooling are
kept outside the tracked source through `.gitignore`.

## License

JIS is released under the [MIT License](LICENSE).
