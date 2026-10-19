# Buzzcut

Where do your coding agent's tokens actually go?

`analyze.py` reads your local Claude Code transcripts and shows which tool outputs fill the context: file reads, test and build logs, MCP calls, web fetches. Read-only, runs locally, Python 3 standard library only.

## Run

```sh
python3 analyze.py                      # scans ~/.claude/projects
python3 analyze.py /path/to/projects    # or another folder of .jsonl transcripts
```

## Sharing your results

The report shows tool names, command names and file extensions only. No file paths, file contents or full commands. Skim it before you paste it anywhere anyway.

The **Summary** table is the part to compare between people:

| Bucket | Means |
|---|---|
| reading files | `cat`, `sed`, `grep`, `ls`, `git show/diff/log`... and the Read tool |
| tests/builds/installs | `mvn`, `gradle`, `npm test`, `pytest`, `cargo build`... |
| MCP tools | Jira, Confluence, Notion, etc. |
| web | WebFetch, WebSearch |

## Caveats

- Tokens are estimated as characters / 4, not counted with a tokenizer.
- "carried" multiplies each result by the number of later model calls in its session. Most of that is re-sent as cheaper cache reads, so treat it as relative weight, not cost.
- Context compaction is not modelled, so "carried" overstates long sessions.
