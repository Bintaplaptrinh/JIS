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
- Share one local daemon across multiple terminals, with bounded queues, caches,
  and a SQLite history of up to 20,000 observations.
- Review a proposed correction before running it. Accepting a correction only
  fills the command line; press Enter again to execute it.

The current release uses heuristic rules throughout the suggestion pipeline.

## Installation

### Requirements

- Linux (the current runtime uses Linux file and Unix socket facilities).
- Python 3.10 or newer.
- zsh with the `zsh/net/socket` module.
- Git when installing directly from GitHub.

### Install with pipx (recommended)

JIS is distributed as the Python package `jis-terminal`, which provides the `jis`
command and includes the zsh plugin. [pipx](https://pipx.pypa.io/stable/installation/)
installs the command in its own virtual environment and makes it available on
your PATH. Until a PyPI release is published, install directly from GitHub:

```sh
pipx install 'git+https://github.com/Bintaplaptrinh/JIS.git'
pipx ensurepath
```

Open a new terminal if `pipx ensurepath` changed your PATH. In interactive zsh,
enable JIS with:

```zsh
eval "$(jis shell)"
```

Add that same line to `~/.zshrc`, after other shell plugins, to enable JIS in
every terminal. The initialization selects the Python interpreter that installed
JIS, so activating its virtual environment is unnecessary. No checkout is needed.

### Install with pip

Use a dedicated virtual environment:

```sh
python3 -m venv "$HOME/.local/share/jis/venv"
"$HOME/.local/share/jis/venv/bin/python" -m pip install \
  'git+https://github.com/Bintaplaptrinh/JIS.git'
```

Add this line to `~/.zshrc`, after other shell plugins:

```zsh
eval "$("$HOME/.local/share/jis/venv/bin/jis" shell)"
```

Use `~/.local/share/jis/venv/bin/jis` for CLI commands, or activate the virtual
environment to use `jis` directly. To upgrade, repeat the pip command with
`--upgrade`. For pipx installations, run `pipx upgrade jis-terminal`.

Once maintainers publish `jis-terminal` to PyPI, users can replace the GitHub URL
with `jis-terminal`: `pipx install jis-terminal` or, inside a virtual environment,
`python -m pip install jis-terminal`. Registry installation requires that first
release; the GitHub installation path does not.

### Install from source

Clone the repository and install it in a virtual environment:

```sh
git clone https://github.com/Bintaplaptrinh/JIS.git
cd JIS
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

In an interactive **zsh** session, run this command from the repository directory:

```zsh
eval "$(.venv/bin/jis shell)"
```

Sourcing the plugin starts the shared daemon automatically. Editable installs
require keeping the checkout in place.

### Enable JIS in every terminal

For an editable source install, add this line to `~/.zshrc`, replacing the path
with the absolute path to your checkout. Load JIS after other shell plugins:

```zsh
eval "$("$HOME/path/to/JIS/.venv/bin/jis" shell)"
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

Run `echo jis-demo-one`, then type `echo jis-`. JIS displays the remaining text
as a suggestion. Press Ctrl-Space to fill it, then Enter to execute it.
Suggestions come from successful commands observed after JIS was enabled;
your existing `.zsh_history` is not imported.

| Key or command | Action |
| --- | --- |
| Enter | Check for a clear typo before executing |
| `yes` + Enter | Fill the proposed correction for review |
| `no` + Enter / Ctrl-G | Restore the original input |
| Ctrl-Space | Fill a history suggestion |
| Ctrl-X, then Enter | Execute the current input while bypassing correction |
| `jis-off` / `jis-on` | Disable / enable JIS in the current shell |
| `jis-refresh` | Reconnect and refresh known aliases and functions |
| `jis-status` | Show daemon status and history counts |

### Command-line interface

For a pipx install, or with the pip virtual environment activated:

```sh
jis status
jis correct 'gti status'
jis suggest 'echo jis-'
jis stop
jis start
```

Run `jis --help` for available commands. The checkout also retains `./bin/jis`
and `shell/jis.plugin.zsh` for existing source installations.

## Configuration

Set environment variables **before** sourcing the plugin:

| Variable | Default | Purpose |
| --- | --- | --- |
| `JIS_PYTHON` | Interpreter running `jis shell`; otherwise `python`, falling back to `python3` | Interpreter used by the plugin (`jis shell` selects it automatically) |
| `JIS_STATE_DIR` | `${XDG_STATE_HOME:-$HOME/.local/state}/jis` | Local socket, history database, lock, and log directory |

For example, to use a separate history and daemon:

```zsh
export JIS_STATE_DIR="$HOME/.local/state/jis-work"
eval "$(jis shell)"
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
  your state directory. Run `jis start` to see the error.
- **Suggestions stop appearing:** run `jis start`, then `jis-refresh` in
  the affected shell. Check that JIS is enabled with `jis-on`.
- **A command keeps triggering correction:** use Ctrl-X, then Enter to run the
  original input. Run `jis-refresh` after adding aliases or functions.
- **Disable JIS permanently:** remove its lines from `~/.zshrc` and open a new
  shell. Run `jis stop` to stop the shared daemon. `jis-off` only affects
  the current shell.

## Bug reports and contributions

Report bugs or propose features through the
[issue tracker](https://github.com/Bintaplaptrinh/JIS/issues). Include your OS,
Python and zsh versions, a minimal reproduction, and relevant log output with
private information removed.

This repository publishes the official heuristic runtime, shell integration,
installation metadata, package workflow, and this README. Tests, recipes, research documentation,
notebooks, model checkpoints, generated output, and experimental tooling are
kept outside the tracked source through `.gitignore`.

## Publishing a PyPI release

The package workflow builds a source archive and wheel, checks their metadata,
and verifies the installed CLI and zsh integration on Linux. It runs on pushes,
pull requests, manual dispatch, and published GitHub releases.

For the first release:

1. Sign in to PyPI and [add a pending trusted publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
   with project name `jis-terminal`, owner `Bintaplaptrinh`, repository `JIS`,
   workflow filename `package.yml`, and environment `pypi`. Confirm the package
   name is available; a pending publisher does not reserve it.
2. Create the GitHub Actions environment `pypi` in the repository settings.
3. Keep the versions in `pyproject.toml` and `src/jis/__init__.py` aligned, then
   commit and push the changes.
4. Publish a GitHub release with a tag matching the version, such as `v0.1.0`.
   After package validation passes, the workflow publishes to PyPI using OIDC,
   without a stored PyPI API token.

Each release must use a new version. PyPI does not allow replacing an uploaded
distribution. Publishing requires the maintainer's PyPI/GitHub setup above;
building and installing from GitHub require no registry credentials.

## License

JIS is released under the [MIT License](LICENSE).
