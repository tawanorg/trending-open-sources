#!/usr/bin/env python3
"""Fetch interesting open-source projects and render README.md + a dated archive.

Runs in GitHub Actions (stdlib only, no pip install). GITHUB_TOKEN raises the
search rate limit from 10/min to 30/min.
"""
import json, os, sys, time, urllib.request, urllib.error, urllib.parse
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.github.com/search/repositories"
TODAY = time.strftime("%Y-%m-%d", time.gmtime())

def _days_ago(n):
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() - n * 86400))

# section title -> list of search queries
SECTIONS = OrderedDict([
    ("Self-hosted", [
        f"topic:self-hosted stars:>300 pushed:>{_days_ago(60)}",
        f"topic:self-hosted stars:>50 created:>{_days_ago(365)}",
    ]),
    ("AI & LLM", [
        f"topic:llm stars:>500 pushed:>{_days_ago(30)}",
        f"topic:ai-agents stars:>100 created:>{_days_ago(270)}",
    ]),
    ("MCP", [
        f"topic:mcp stars:>100 pushed:>{_days_ago(60)}",
    ]),
    ("Developer tools", [
        f"topic:developer-tools stars:>800 pushed:>{_days_ago(30)}",
    ]),
])

def _clean(t):
    return " ".join((t or "").split())

def search(q, token):
    url = f"{API}?{urllib.parse.urlencode({'q': q, 'sort': 'stars', 'order': 'desc', 'per_page': 30})}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "trending-open-sources",
        **({"Authorization": f"Bearer {token}"} if token else {}),
    })
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r).get("items", [])
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):              # secondary rate limit — back off
                time.sleep(15 * (attempt + 1)); continue
            raise
    return []

def collect(token):
    out, seen = OrderedDict(), set()
    for title, queries in SECTIONS.items():
        rows = []
        for q in queries:
            for it in search(q, token):
                name = it["full_name"]
                if name in seen or it.get("archived") or it.get("fork"):
                    continue
                seen.add(name)
                rows.append({
                    "name": name,
                    "url": it["html_url"],
                    "stars": it["stargazers_count"],
                    "desc": _clean(it.get("description")),
                    "lang": it.get("language") or "",
                })
            time.sleep(2)
        rows.sort(key=lambda r: -r["stars"])
        out[title] = rows
    return out

def stars(n):
    return f"{n/1000:.1f}k" if n >= 1000 else str(n)

def table(rows):
    if not rows:
        return "_No results this run._\n"
    out = ["| Repo | Stars | Language | Description |", "|---|---:|---|---|"]
    for r in rows:
        desc = r["desc"].replace("|", "\\|")
        if len(desc) > 110:
            desc = desc[:109].rstrip() + "…"
        out.append(f"| [{r['name']}]({r['url']}) | {stars(r['stars'])} | {r['lang']} | {desc} |")
    return "\n".join(out) + "\n"

def render(data, *, for_readme):
    total = sum(len(v) for v in data.values())
    head = "# Trending open source\n\n" if for_readme else f"# {TODAY}\n\n"
    if for_readme:
        head += (
            "Interesting self-hosted, AI/LLM, MCP and developer-tooling projects,\n"
            "refreshed daily by GitHub Actions. Past snapshots live in "
            "[`archive/`](archive/).\n\n"
        )
    head += f"_Updated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())} · {total} projects_\n"
    body = [head]
    for title, rows in data.items():
        body.append(f"\n## {title}\n\n{table(rows)}")
    return "".join(body)

def main():
    token = os.environ.get("GITHUB_TOKEN")
    data = collect(token)
    if sum(len(v) for v in data.values()) == 0:
        print("no results — leaving files untouched", file=sys.stderr)
        return 1
    with open(os.path.join(ROOT, "README.md"), "w") as f:
        f.write(render(data, for_readme=True))
    os.makedirs(os.path.join(ROOT, "archive"), exist_ok=True)
    with open(os.path.join(ROOT, "archive", f"{TODAY}.md"), "w") as f:
        f.write(render(data, for_readme=False))
    print(f"wrote README.md and archive/{TODAY}.md")
    return 0

if __name__ == "__main__":
    sys.exit(main())
