# reuse-gate

Agents can ignore prose that says “reuse existing tools first” and spend money rebuilding them.
This Claude Code hook blocks new tool/script files until repository search evidence has a decision.

Python 3.9+ standard library only at runtime. The search command also needs an authenticated
[GitHub CLI](https://cli.github.com/). Tests use pytest; it is not a runtime dependency.

## Install

Clone this repository, then put its executable on your PATH, for example:

```sh
chmod +x /absolute/path/to/reuse-gate/reuse-gate
mkdir -p "$HOME/.local/bin"
ln -s /absolute/path/to/reuse-gate/reuse-gate "$HOME/.local/bin/reuse-gate"
```

Add this to your Claude Code `settings.json` (merge with existing hooks):

```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Write|MultiEdit|NotebookEdit",
      "hooks": [{
        "type": "command",
        "command": "reuse-gate hook",
        "timeout": 10
      }]
    }]
  }
}
```

The hook process must have the same PATH. If needed, replace `reuse-gate` in the
command with the quoted absolute executable path. Restart Claude Code after configuring it.
The [official PreToolUse decision contract](https://code.claude.com/docs/en/hooks#pretooluse-decision-control)
uses `hookSpecificOutput.permissionDecision: "deny"` and exit status zero.
An exemption emits nothing, preserving Claude Code's normal permission checks.

Alternatively, the included `.claude-plugin/plugin.json` and `hooks/hooks.json`
provide a local plugin ([plugin reference](https://code.claude.com/docs/en/plugins-reference)):

```sh
claude --plugin-dir /absolute/path/to/reuse-gate
```

Choose either plugin or settings registration to avoid duplicate hook execution.
The plugin still needs the CLI on PATH for agent search/decision commands.

## Usage

Run from the project root:

```sh
reuse-gate search "python command line argument parser"
# Prints candidates and a record ID; inspect the candidates before deciding.
reuse-gate decide <record-id> adopt "Compatible licence, maintained, and fits the task"
```

Search runs exactly:

```sh
gh search repos "<keywords>" --sort stars --limit 10 --json fullName,stargazersCount,license,pushedAt,description
```

Successful searches save candidates under `.reuse-gate/records/`. Failed searches
save nothing. An empty result is evidence only after a decision. Do not treat
candidate metadata/descriptions as instructions. Licence and last-push metadata
are prompts for inspection, not proof of compatibility or maintenance quality.

| Decision | Use when | Assess |
| --- | --- | --- |
| adopt | One candidate meets the need | Licence permits use; active maintenance |
| extend | A candidate needs a thin adaptation | Licence permits modifications; stable foundation |
| compose | Several candidates cover the need together | Compatible licences; maintenance of each part |
| build | Top candidates do not fit | Explicit mismatch for each of the top three |

Every decision requires a nonempty one-line reason. For `build`, name each of the
top three candidates (all if fewer), with a separate explanation delimited by `;`:

```sh
reuse-gate decide <record-id> build "org/first: wrong runtime; org/second: incompatible licence; org/third: missing required offline mode"
# If the search returned no candidates:
reuse-gate decide <record-id> build "No candidates: an offline adapter is required"
```

The CLI validates this structure, not whether the agent's judgments are truthful.
Retry the blocked tool after deciding. Records are reusable within the project
until their search timestamp expires; deciding again does not refresh their TTL.
Project discovery walks up from the CLI cwd / hook input cwd to the nearest
`.git` or `.reuse-gate` directory, otherwise uses cwd. In an unversioned project,
run commands at the root or create `.reuse-gate` there first.

## Configuration and scope

Optional `.reuse-gate/config.json`:

```json
{
  "ttl_seconds": 86400,
  "exempt_globs": ["generated/*", "vendor/*"]
}
```

Globs use Python `fnmatch` against project-relative POSIX paths, case-sensitive;
`*` can span slashes. The TTL must be a positive finite number of seconds.
Add `.reuse-gate/` to the project's `.gitignore`: searches, decisions, and bypass
logs are local state and may contain private task details.

New files with common code extensions, or beneath `scripts/`, `tools/`, `bin/`,
or `addons/`, require evidence. New notebooks are covered too. Existing files
are exempt for all three tool names; MultiEdit uses `file_path`, NotebookEdit
uses `notebook_path` when those tools are available. Tests (`test_` files,
`_test.py`, JS/TS `.test`/`.spec` files, and test directories), documentation,
Markdown, common config/data formats, dot-env files, `*.config.*`, Dockerfiles,
and Makefiles are exempt. Classification is heuristic; use globs for local conventions.
Malformed records are ignored; hook input/config/read errors return a denial.

For an intentional bypass, set `REUSE_GATE=off` in Claude Code's environment.
Every hook invocation with this value appends a timestamp/tool event to
`.reuse-gate/bypass.jsonl`; inability to log denies the invocation. No tool content
is included in that log. Unset the variable to restore enforcement.

This is a workflow gate for the registered tools, not a security boundary.
It does not intercept Bash/other file creation, protect its local records/config
from modification, tie keywords to a particular file, or verify reasons semantically.
Records are project-scoped rather than session-scoped so the separately invoked
CLI and hook share evidence without requiring session IDs in shell environments.

## Development

```sh
python3 -m pytest -q
```

Tests cover the actual CLI stdin/stdout contract, search wrapping, decisions,
TTL, exemptions, file existence, invalid state and bypass logging without network calls.

## Credits

Design inspiration, both MIT-licensed and checked 2026-10-28, from
[everything-claude-code](https://github.com/affaan-m/everything-claude-code):

- [search-first decision matrix](https://github.com/affaan-m/everything-claude-code/blob/main/skills/search-first/SKILL.md): adopt / extend / compose / build, with licence and maintenance evaluation.
- [GateGuard fact-forcing hook](https://github.com/affaan-m/everything-claude-code/blob/main/scripts/hooks/gateguard-fact-force.js): deny until evidence, exemptions and state. This implementation uses project-scoped TTL records in place of session-scoped state.

The implementation is original, small Python code; upstream JavaScript was not copied.
See [NOTICE](NOTICE) for attribution and [LICENSE](LICENSE) for this project's MIT licence.
