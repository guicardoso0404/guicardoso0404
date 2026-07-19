#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import os
from pathlib import Path
import re
import urllib.request

USERNAME = "guicardoso0404"
ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
README = ROOT / "README.md"

THEMES = {
    "light": {
        "bg": "#f6f8fa", "panel": "#ffffff", "fg": "#24292f",
        "muted": "#57606a", "key": "#0969da", "value": "#1a7f37",
        "border": "#d0d7de", "track": "#eaeef2",
    },
    "dark": {
        "bg": "#0d1117", "panel": "#161b22", "fg": "#e6edf3",
        "muted": "#8b949e", "key": "#58a6ff", "value": "#7ee787",
        "border": "#30363d", "track": "#21262d",
    },
}


def graphql(query: str, variables: dict) -> dict:
    token = os.environ.get("PROFILE_STATS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError(
            "Set PROFILE_STATS_TOKEN or GITHUB_TOKEN before generating the stats."
        )
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": f"{USERNAME}-profile-readme",
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = json.load(response)
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"], ensure_ascii=False))
    return payload["data"]


def public_repositories() -> list[dict]:
    query = """
    query($login:String!, $cursor:String) {
      user(login:$login) {
        repositories(
          first:100,
          after:$cursor,
          ownerAffiliations:[OWNER],
          privacy:PUBLIC
        ) {
          nodes {
            nameWithOwner
            isFork
            stargazerCount
            languages(first:10, orderBy:{field:SIZE, direction:DESC}) {
              edges { size node { name color } }
            }
          }
          pageInfo { hasNextPage endCursor }
        }
      }
    }
    """
    repositories: list[dict] = []
    cursor = None

    while True:
        connection = graphql(query, {"login": USERNAME, "cursor": cursor})["user"][
            "repositories"
        ]
        repositories.extend(connection.get("nodes") or [])
        page = connection["pageInfo"]
        if not page["hasNextPage"]:
            return repositories
        cursor = page["endCursor"]
        if not cursor:
            raise RuntimeError("Repository pagination ended without a cursor.")


def repository_line_stats(name_with_owner: str, author_id: str) -> tuple[int, int]:
    owner, name = name_with_owner.split("/", 1)
    query = """
    query($owner:String!, $name:String!, $author:ID!, $cursor:String) {
      repository(owner:$owner, name:$name) {
        defaultBranchRef {
          target {
            ... on Commit {
              history(first:100, after:$cursor, author:{id:$author}) {
                nodes { additions deletions }
                pageInfo { hasNextPage endCursor }
              }
            }
          }
        }
      }
    }
    """
    additions = 0
    deletions = 0
    cursor = None

    # Up to 500 authored commits per public repository.
    for _ in range(5):
        data = graphql(query, {
            "owner": owner,
            "name": name,
            "author": author_id,
            "cursor": cursor,
        })
        repository = data.get("repository") or {}
        branch = repository.get("defaultBranchRef") or {}
        target = branch.get("target") or {}
        history = target.get("history") or {}
        for commit in history.get("nodes") or []:
            additions += int(commit.get("additions") or 0)
            deletions += int(commit.get("deletions") or 0)

        page = history.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            break
        cursor = page.get("endCursor")
        if not cursor:
            break

    return additions, deletions


def collect() -> dict:
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(days=365)
    query = """
    query($login:String!, $from:DateTime!, $to:DateTime!) {
      user(login:$login) {
        id
        followers { totalCount }
        repositoriesContributedTo(
          first:1,
          includeUserRepositories:false,
          contributionTypes:[COMMIT, ISSUE, PULL_REQUEST]
        ) {
          totalCount
        }
        contributionsCollection(from:$from, to:$to) {
          totalCommitContributions
          totalPullRequestContributions
          totalIssueContributions
          restrictedContributionsCount
          contributionCalendar { totalContributions }
        }
      }
    }
    """
    user = graphql(query, {
        "login": USERNAME,
        "from": start.isoformat(),
        "to": end.isoformat(),
    })["user"]

    owned = [repo for repo in public_repositories() if not repo["isFork"]]
    stars = sum(int(repo["stargazerCount"]) for repo in owned)

    sizes: dict[str, int] = {}
    colors: dict[str, str] = {}
    for repo in owned:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            sizes[name] = sizes.get(name, 0) + int(edge["size"])
            colors[name] = edge["node"].get("color") or "#8b949e"

    total = sum(sizes.values()) or 1
    languages = [
        {"name": name, "percent": size / total * 100, "color": colors[name]}
        for name, size in sorted(sizes.items(), key=lambda item: item[1], reverse=True)[:5]
    ]

    additions = 0
    deletions = 0
    for repo in owned:
        try:
            added, removed = repository_line_stats(repo["nameWithOwner"], user["id"])
            additions += added
            deletions += removed
        except Exception as exc:
            print(f"Warning: line statistics failed for {repo['nameWithOwner']}: {exc}")

    contributions = user["contributionsCollection"]
    return {
        "repos": len(owned),
        "contributed": user["repositoriesContributedTo"]["totalCount"],
        "stars": stars,
        "followers": user["followers"]["totalCount"],
        "commits": contributions["totalCommitContributions"],
        "contributions": contributions["contributionCalendar"]["totalContributions"],
        "pull_requests": contributions["totalPullRequestContributions"],
        "issues": contributions["totalIssueContributions"],
        "restricted_contributions": contributions["restrictedContributionsCount"],
        "additions": additions,
        "deletions": deletions,
        "lines": additions - deletions,
        "languages": languages,
        "updated": end.strftime("%d/%m/%Y"),
    }


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def fmt(value: int) -> str:
    return f"{int(value):,}"


def replace_once(svg: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, svg)
    if count != 1:
        raise RuntimeError(f"Expected one {label} row, found {count}.")
    return updated


def update_profile(theme: str, stats: dict) -> None:
    path = ASSETS / f"profile-{theme}.svg"
    svg = path.read_text(encoding="utf-8")

    line_508 = (
        '<text x="0" y="508"><tspan class="key">Repos</tspan>'
        '<tspan class="muted"> ......... </tspan>'
        f'<tspan class="value">{fmt(stats["repos"])}</tspan>'
        '<tspan class="muted"> {Contributed: </tspan>'
        f'<tspan class="value">{fmt(stats["contributed"])}</tspan>'
        '<tspan class="muted">} | Stars .... </tspan>'
        f'<tspan class="value">{fmt(stats["stars"])}</tspan></text>'
    )
    line_533 = (
        '<text x="0" y="533"><tspan class="key">Commits · 12m</tspan>'
        '<tspan class="muted"> . </tspan>'
        f'<tspan class="value">{fmt(stats["commits"])}</tspan>'
        '<tspan class="muted"> | Followers .... </tspan>'
        f'<tspan class="value">{fmt(stats["followers"])}</tspan></text>'
    )
    line_558 = (
        '<text x="0" y="558"><tspan class="key">Lines of Code on GitHub</tspan>'
        '<tspan class="muted"> . </tspan>'
        f'<tspan class="value">{fmt(stats["lines"])}</tspan>'
        '<tspan class="muted"> (</tspan>'
        f'<tspan class="add">{fmt(stats["additions"])}++</tspan>'
        '<tspan class="muted">, </tspan>'
        f'<tspan class="del">{fmt(stats["deletions"])}--</tspan>'
        '<tspan class="muted">)</tspan></text>'
    )

    svg = replace_once(
        svg, r'<text x="0" y="508">.*?</text>', line_508, "repository stats"
    )
    svg = replace_once(
        svg, r'<text x="0" y="533">.*?</text>', line_533, "commit stats"
    )
    svg = replace_once(
        svg, r'<text x="0" y="558">.*?</text>', line_558, "line stats"
    )
    path.write_text(svg, encoding="utf-8")


def update_readme(version: str) -> None:
    readme = README.read_text(encoding="utf-8")
    asset_url = re.compile(
        rf"(https://raw\.githubusercontent\.com/{USERNAME}/{USERNAME}/main/assets/"
        r"(?:profile|github-stats)-(?:light|dark)\.svg)(?:\?v=[^\"'\s<>]+)?"
    )
    updated, count = asset_url.subn(lambda match: f"{match.group(1)}?v={version}", readme)
    if count != 6:
        raise RuntimeError(f"Expected six dynamic asset URLs in README.md, found {count}.")
    README.write_text(updated, encoding="utf-8")


def stats_svg(theme_name: str, stats: dict) -> str:
    theme = THEMES[theme_name]
    rows = []
    y = 265
    for language in stats["languages"][:5]:
        width = max(4, round(language["percent"] * 3.25))
        rows += [
            f'<text x="575" y="{y}" class="language">{esc(language["name"])}</text>',
            f'<text x="950" y="{y}" text-anchor="end" class="muted">{language["percent"]:.1f}%</text>',
            f'<rect x="575" y="{y + 9}" width="325" height="7" rx="3.5" fill="{theme["track"]}"/>',
            f'<rect x="575" y="{y + 9}" width="{width}" height="7" rx="3.5" fill="{esc(language["color"])}"/>',
        ]
        y += 34

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="455" viewBox="0 0 1000 455">
<style>
text{{font-family:Consolas,'Courier New',monospace;fill:{theme["fg"]};font-size:15px}}
.title{{font-size:20px;font-weight:700}}
.key{{fill:{theme["key"]};font-weight:700}}
.value{{fill:{theme["value"]}}}
.label{{font-size:13px;fill:{theme["muted"]}}}
.muted{{font-size:13px;fill:{theme["muted"]}}}
.metric{{font-size:22px;font-weight:700;fill:{theme["value"]}}}
.language{{font-size:13px;font-weight:700}}
.add{{fill:#1a7f37}}
.del{{fill:#cf222e}}
</style>
<rect x="1" y="1" width="998" height="453" rx="18" fill="{theme["bg"]}" stroke="{theme["border"]}" stroke-width="2"/>
<text x="28" y="38" class="title">GitHub Stats</text>
<text x="972" y="36" text-anchor="end" class="muted">atualizado em {stats["updated"]}</text>
<line x1="28" y1="54" x2="972" y2="54" stroke="{theme["border"]}"/>

<text x="28" y="91"><tspan class="key">Repos</tspan><tspan class="muted"> ........ </tspan><tspan class="value">{fmt(stats["repos"])}</tspan><tspan class="muted"> {{Contributed: </tspan><tspan class="value">{fmt(stats["contributed"])}</tspan><tspan class="muted">}} | Stars ........ </tspan><tspan class="value">{fmt(stats["stars"])}</tspan></text>
<text x="28" y="123"><tspan class="key">Commits · 12 meses</tspan><tspan class="muted"> ........ </tspan><tspan class="value">{fmt(stats["commits"])}</tspan><tspan class="muted"> | Followers .... </tspan><tspan class="value">{fmt(stats["followers"])}</tspan></text>
<text x="28" y="155"><tspan class="key">Lines of Code on GitHub</tspan><tspan class="muted"> ... </tspan><tspan class="value">{fmt(stats["lines"])}</tspan><tspan class="muted"> (</tspan><tspan class="add">{fmt(stats["additions"])}++</tspan><tspan class="muted">, </tspan><tspan class="del">{fmt(stats["deletions"])}--</tspan><tspan class="muted">)</tspan></text>

<line x1="28" y1="181" x2="972" y2="181" stroke="{theme["border"]}"/>
<text x="28" y="220" class="title">Atividade · últimos 12 meses</text>
<text x="28" y="264" class="label">CONTRIBUIÇÕES</text><text x="28" y="296" class="metric">{fmt(stats["contributions"])}</text>
<text x="205" y="264" class="label">PULL REQUESTS</text><text x="205" y="296" class="metric">{fmt(stats["pull_requests"])}</text>
<text x="365" y="264" class="label">ISSUES</text><text x="365" y="296" class="metric">{fmt(stats["issues"])}</text>
<text x="575" y="220" class="title">Linguagens mais usadas</text>
{chr(10).join(rows)}
</svg>
'''


def main() -> None:
    stats = collect()
    for theme in THEMES:
        update_profile(theme, stats)
        (ASSETS / f"github-stats-{theme}.svg").write_text(
            stats_svg(theme, stats), encoding="utf-8"
        )

    version = hashlib.sha256(
        json.dumps(stats, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    update_readme(version)

    if stats["restricted_contributions"] and not os.environ.get(
        "PROFILE_STATS_TOKEN"
    ):
        print(
            "Warning: some private contribution details are hidden from "
            "GITHUB_TOKEN. "
            "Add the PROFILE_STATS_TOKEN repository secret to include activity "
            "that the token can access."
        )
    print(
        json.dumps(
            {"cache_version": version, **stats}, ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    main()
