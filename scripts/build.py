#!/usr/bin/env python3
"""Fetch self-hosted software you could run internally or resell as a service,
and render README.md + a dated archive.

Runs in GitHub Actions (stdlib only, no pip install). GITHUB_TOKEN raises the
search rate limit from 10/min to 30/min.

Two filters do all the work here:

  * licence — permissive only (MIT / Apache-2.0 / BSD / MPL-2.0). AGPL, SSPL
    and the "sustainable use"/BUSL family are excluded on purpose: they are
    fine to self-host, but they are exactly the licences that make reselling
    the software as a hosted service either impossible or an obligation to
    publish your own changes. If you only ever run it internally, drop
    PERMISSIVE and the pool roughly triples.
  * topic — AI is filtered out rather than sought. GitHub's trending surface
    is saturated with it and it drowns everything shippable.

Kept in step with `bin/gh-trending` in tawanorg/dotfiles, which applies the
same two filters to feed a status line.
"""
import json, os, re, sys, time, urllib.request, urllib.error, urllib.parse
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.github.com/search/repositories"
TODAY = time.strftime("%Y-%m-%d", time.gmtime())

def _days_ago(n):
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() - n * 86400))

# Repeated `license:` qualifiers OR together; repeated `topic:` qualifiers AND.
# That asymmetry is why licences are one string and categories are one per query.
PERMISSIVE = "license:mit license:apache-2.0 license:bsd-3-clause license:bsd-2-clause license:mpl-2.0"
NO_AI = ("-topic:llm -topic:ai -topic:artificial-intelligence -topic:machine-learning "
         "-topic:ai-agents -topic:agents -topic:rag -topic:chatgpt -topic:mcp "
         "-topic:deep-learning -topic:generative-ai")

def _cat(topic):
    return f"topic:{topic} stars:>150 pushed:>{_days_ago(120)} {PERMISSIVE} {NO_AI}"

# Product categories that map onto something you could actually charge for,
# grouped so the README stays readable. Two broad self-hosted sweeps lead;
# everything after is one query per topic.
SECTIONS = OrderedDict([
    ("Self-hosted", [
        f"topic:self-hosted stars:>300 pushed:>{_days_ago(60)} {PERMISSIVE} {NO_AI}",
        f"topic:self-hosted stars:>50 created:>{_days_ago(365)} {PERMISSIVE} {NO_AI}",
    ]),
    ("Monitoring & analytics", [
        _cat(t) for t in
        ("monitoring", "observability", "analytics", "business-intelligence", "status-page")
    ]),
    ("Content & commerce", [
        _cat(t) for t in
        ("cms", "headless-cms", "ecommerce", "newsletter", "knowledge-base")
    ]),
    ("Business apps", [
        _cat(t) for t in
        ("crm", "erp", "billing", "project-management", "kanban", "scheduling",
         "helpdesk", "survey")
    ]),
    ("Automation & internal tools", [
        _cat(t) for t in
        ("low-code", "no-code", "workflow-automation", "internal-tools",
         "file-sharing", "identity-provider")
    ]),
])

# Descriptions give away the AI repos that never bothered to tag themselves.
AI_WORDS = re.compile(
    r"\b(ai|llm|llms|gpt|chatgpt|claude|gemini|rag|agentic|copilot|prompt|prompts"
    r"|embeddings?|inference|fine-?tun\w*|transformers?|mcp)\b", re.I)

# The category topics are also where dev libraries live: searching `forms` or
# `analytics` returns as many validation helpers and React wrappers as it does
# products. Nothing here is a thing you can stand up and charge someone for.
NOT_A_PRODUCT = re.compile(
    r"\b(librar(y|ies)|framework|hooks?|components?|sdk|bindings?|wrapper"
    r"|boilerplate|starter|template|awesome|cheat ?sheet|tutorials?|courses?"
    r"|roadmap|examples?|list of|collection of|curated)\b", re.I)

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
                desc = _clean(it.get("description"))
                if not desc:
                    continue                      # nothing to judge it on
                if AI_WORDS.search(desc) or AI_WORDS.search(name):
                    continue                      # untagged AI repo — the topic filter missed it
                if NOT_A_PRODUCT.search(desc):
                    continue
                seen.add(name)
                rows.append({
                    "name": name,
                    "url": it["html_url"],
                    "stars": it["stargazers_count"],
                    "desc": desc,
                    "lang": it.get("language") or "",
                    "license": (it.get("license") or {}).get("spdx_id") or "?",
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
    out = ["| Repo | Stars | Licence | Language | Description |", "|---|---:|---|---|---|"]
    for r in rows:
        desc = r["desc"].replace("|", "\\|")
        if len(desc) > 110:
            desc = desc[:109].rstrip() + "…"
        out.append(f"| [{r['name']}]({r['url']}) | {stars(r['stars'])} | {r['license']} "
                   f"| {r['lang']} | {desc} |")
    return "\n".join(out) + "\n"

def render(data, *, for_readme):
    total = sum(len(v) for v in data.values())
    head = "# Trending open source\n\n" if for_readme else f"# {TODAY}\n\n"
    if for_readme:
        head += (
            "Self-hosted software you could run internally or resell as a service,\n"
            "refreshed daily by GitHub Actions. Permissively licensed only (MIT,\n"
            "Apache-2.0, BSD, MPL-2.0) — AGPL, SSPL and BUSL are excluded because\n"
            "they are what stops you offering the thing as a hosted service. AI is\n"
            "filtered out rather than sought. Past snapshots live in "
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
