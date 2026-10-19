#!/usr/bin/env python3
import json, re, shlex, sys
from collections import Counter
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / ".claude/projects")

READ_CMDS = {"cat", "sed", "head", "tail", "grep", "rg", "find", "ls", "wc", "awk", "tree", "less",
             "git show", "git grep", "git diff", "git log", "git ls-files", "git blame"}
BUILD_TOOLS = {"mvn", "gradle", "gradlew", "make", "pytest", "jest", "vitest", "tsc", "javac", "ctest"}
BUILD_SUBS = {"test", "build", "install", "run", "check", "lint", "compile", "verify", "package"}


def tokens(chars):
    return chars // 4


def result_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def command_names(cmd):
    for part in re.split(r"&&|\|\||;|\n", cmd):
        try:
            words = shlex.split(part, comments=True)
        except ValueError:
            words = part.split()
        words = [w for w in words if not re.match(r"^\w+=", w)]
        if not words or words[0] in ("cd", "export", "set", "source", "."):
            continue
        name = Path(words[0]).name
        if name in ("npx", "uv", "poetry", "bunx", "pnpm", "yarn", "npm", "python3", "python", "go", "cargo", "git", "docker", "mvn", "gradle", "gradlew") and len(words) > 1:
            sub, skip = "", False
            for w in words[1:]:
                if skip:
                    skip = False
                elif w in ("-C", "-c", "-f", "-p", "-s"):
                    skip = True
                elif not w.startswith("-"):
                    sub = w
                    break
            yield f"{name} {Path(sub).name if '/' in sub else sub}".strip()
        else:
            yield name


def command_name(cmd):
    return next(command_names(cmd), "(empty)")


def is_build(c):
    words = c.split()
    return bool(words) and words[0] in BUILD_TOOLS or (len(words) > 1 and words[1] in BUILD_SUBS)


def bucket(tool, cmd=""):
    if tool == "Read":
        return "reading files"
    if tool == "Bash":
        names = list(command_names(cmd))
        if any(is_build(c) for c in names):
            return "tests/builds/installs"
        if any(c in READ_CMDS for c in names):
            return "reading files"
        return "other bash"
    if tool.startswith("mcp__"):
        return "MCP tools"
    if tool in ("WebFetch", "WebSearch"):
        return "web"
    return "other"


def analyze(files):
    by_tool = Counter()
    by_tool_n = Counter()
    by_cmd = Counter()
    by_cmd_n = Counter()
    by_bucket = Counter()
    carried = Counter()
    biggest = []
    reread_tokens = 0
    reread_n = 0
    dup_tokens = 0
    persisted = 0
    sessions = 0
    total = 0

    for f in files:
        try:
            lines = [json.loads(l) for l in open(f, errors="replace") if l.strip()]
        except (OSError, json.JSONDecodeError):
            continue
        sessions += 1
        calls = {}
        assistant_ids = []
        results = []
        for d in lines:
            m = d.get("message")
            if not isinstance(m, dict):
                continue
            if d.get("type") == "assistant" and m.get("id") and (not assistant_ids or assistant_ids[-1] != m["id"]):
                assistant_ids.append(m["id"])
            if not isinstance(m.get("content"), list):
                continue
            for b in m["content"]:
                if b.get("type") == "tool_use":
                    calls[b["id"]] = (b.get("name", "?"), b.get("input") or {})
                elif b.get("type") == "tool_result":
                    results.append((len(assistant_ids), b))

        seen_reads = set()
        seen_outputs = set()
        for turn, b in results:
            name, inp = calls.get(b.get("tool_use_id"), ("?", {}))
            text = result_text(b.get("content"))
            t = tokens(len(text))
            total += t
            by_tool[name] += t
            by_tool_n[name] += 1
            by_bucket[bucket(name, inp.get("command", ""))] += t
            carried[name] += t * max(len(assistant_ids) - turn, 0)
            if "<persisted-output>" in text or "tool-results/" in text:
                persisted += 1
            label = name
            if name == "Bash":
                c = command_name(inp.get("command", ""))
                by_cmd[c] += t
                by_cmd_n[c] += 1
                label = f"Bash: {c}"
            elif name == "Read":
                p = inp.get("file_path", "")
                key = (p, inp.get("offset"), inp.get("limit"))
                if key in seen_reads:
                    reread_tokens += t
                    reread_n += 1
                seen_reads.add(key)
                label = f"Read: *{Path(p).suffix or '(no ext)'}"
            if t > 50 and text in seen_outputs:
                dup_tokens += t
            seen_outputs.add(text)
            biggest.append((t, label))

    return dict(sessions=sessions, total=total, by_tool=by_tool, by_tool_n=by_tool_n, by_cmd=by_cmd,
                by_cmd_n=by_cmd_n, by_bucket=by_bucket, carried=carried, biggest=sorted(biggest, reverse=True)[:15],
                reread_tokens=reread_tokens, reread_n=reread_n, dup_tokens=dup_tokens, persisted=persisted)


def pct(a, b):
    return f"{100 * a / b:5.1f}%" if b else "  -  "


def report(r):
    total = r["total"]
    print(f"Sessions: {r['sessions']}   Tool-result tokens (~chars/4): {total:,}\n")
    print("Summary                          tokens   share")
    for name, t in r["by_bucket"].most_common():
        print(f"  {name:24} {t:12,} {pct(t, total)}")
    print()
    print("By tool                     calls      tokens   share   carried*")
    for name, t in r["by_tool"].most_common(12):
        print(f"  {name[:24]:24} {r['by_tool_n'][name]:7} {t:11,} {pct(t, total)} {r['carried'][name]:12,}")
    print("  * carried = tokens x later model calls in the session (re-sent each turn, mostly as cache reads)\n")
    bash = r["by_tool"]["Bash"]
    print("Bash by first command       calls      tokens   of Bash")
    for c, t in r["by_cmd"].most_common(20):
        print(f"  {c[:24]:24} {r['by_cmd_n'][c]:7} {t:11,} {pct(t, bash)}")
    print()
    read = r["by_tool"]["Read"]
    print(f"Read re-reads (same file+range in a session): {r['reread_n']} calls, {r['reread_tokens']:,} tokens ({pct(r['reread_tokens'], read).strip()} of Read)")
    print(f"Exact duplicate outputs (any tool, >50 tok): {r['dup_tokens']:,} tokens")
    print(f"Results already spilled to file by Claude Code: {r['persisted']}\n")
    print("Biggest single results")
    for t, label in r["biggest"]:
        print(f"  {t:8,}  {label[:60]}")


def selftest():
    assert command_name("cd foo && npm test -- --watch") == "npm test"
    assert command_name("FOO=1 ./gradlew build") == "gradlew build"
    assert command_name("/usr/bin/git -C x status") == "git status"
    assert command_name("mvn -s settings.xml verify") == "mvn verify"
    assert command_name("ls -la | head") == "ls"
    assert bucket("Bash", "echo --- && cat a.py") == "reading files"
    assert bucket("Bash", "cd x && ./gradlew test | tail") == "tests/builds/installs"
    assert bucket("Bash", "git status") == "other bash"
    assert bucket("Bash", "/ x") == "other bash"
    assert bucket("mcp__jira__getJiraIssue") == "MCP tools"
    assert result_text([{"type": "text", "text": "a"}, {"type": "image"}]) == "a"


if __name__ == "__main__":
    selftest()
    report(analyze(sorted(ROOT.rglob("*.jsonl"))))
