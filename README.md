# reuse-gate

Agents can ignore prose that says “reuse existing tools first” and spend money rebuilding them.
This Claude Code hook covers Write/Edit/NotebookEdit (and optional MultiEdit), blocking new
tool/script files until repository search evidence has a decision. Bash writers (`cat >`,
`tee`, `cp`, heredocs), PowerShell and MCP writers are not covered.

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
      "matcher": "Write|Edit|NotebookEdit|MultiEdit",
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

Search splits the quoted keyword string on whitespace into separate arguments (not an exact phrase):

```sh
gh search repos <keyword1> <keyword2> ... --sort stars --limit 10 --json fullName,stargazersCount,license,pushedAt,description
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
or `addons/`, require evidence. Extensions include `.cs`, `.mts`, `.cts`, `.dart`,
`.bat`, `.cmd`, `.vue`, `.svelte` and `.sql`. New notebooks are covered too. Existing files
are exempt for all covered tool names; Write/Edit/MultiEdit use `file_path`, NotebookEdit
uses `notebook_path` when those tools are available. Tests (`test_` files,
stems ending `.test`, `.spec`, `_test` or `_spec` with any extension, Java `*Test.java`,
and `test`/`tests`/`__tests__`/`spec` directories), documentation,
Markdown, common config/data formats, exact `.env` / `.env.*` files, JS/TS `*.config.*` files, Dockerfiles,
and Makefiles are exempt. Classification is heuristic; use globs for local conventions.
Malformed records are ignored. Infrastructure errors (including invalid input, unreadable
state, symlink resolution and bypass logging failures) print to stderr and exit 1,
which is non-blocking in Claude Code; they never emit denial JSON. Built-in exemptions
are checked before reading config. Invalid config falls back to defaults for evaluation,
but the diagnostic still makes the hook exit 1 without a denial. Only verifiable
policy violations emit denial JSON: missing valid evidence for gated paths, or a
covered tool targeting protected `.reuse-gate/` state.

For an intentional bypass, set `REUSE_GATE=off` in Claude Code's environment.
Every hook invocation with this value appends a timestamp/tool event to
`.reuse-gate/bypass.jsonl`; logging is best-effort and inability to log reports a
non-blocking error (stderr and exit 1). No tool content
is included in that log. Unset the variable to restore enforcement.

This is a workflow gate for the registered tools, not a security boundary.
Covered tools cannot write inside `.reuse-gate/`, including existing state files.
Other writers can modify that state. The gate does not tie keywords to a particular
file or verify reasons semantically.
The hook discovers its project from the session cwd, not the target file's repository.
A valid decision clears every gated file evaluated against that project for its TTL;
it is not bound to a query, target, or session. Paths are resolved through symlinks
before classification: a symlinked `scripts/` pointing outside the project loses
that directory classification, so extensionless targets there can escape the gate
(code extensions still apply).
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
[ECC (formerly everything-claude-code)](https://github.com/affaan-m/ECC):

- [search-first decision matrix](https://github.com/affaan-m/ECC/blob/main/skills/search-first/SKILL.md): adopt / extend / compose / build, with licence and maintenance evaluation.
- [GateGuard fact-forcing hook](https://github.com/affaan-m/ECC/blob/main/scripts/hooks/gateguard-fact-force.js): deny until evidence, exemptions and state. This implementation uses project-scoped TTL records in place of session-scoped state.

The implementation is original, small Python code; upstream JavaScript was not copied.
See [NOTICE](NOTICE) for attribution and [LICENSE](LICENSE) for this project's MIT licence.
