# agent-extract

Unified extractor for OpenCode and Codex JSONL output.

## Usage

```bash
ocxo run --format json "<prompt>" | agent-extract
codex exec --json "<prompt>" | agent-extract
```

Supported subcommands:

- `final-text` (default)
- `last-text`
- `before-finish`
- `tools`

Supported options:

- `--no-session`
- `--no-duration`
- `--no-agent`
- `--no-model`
- `--json`

## Compatibility

`cli/ops/ocxo-extract/ocxo-extract` is kept as a wrapper to this implementation.
