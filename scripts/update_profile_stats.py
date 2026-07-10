#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import html
import json
import os
from pathlib import Path
import re
import urllib.request

USERNAME = "guicardoso0404"
ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"

THEMES = {
    "light": {
        "bg": "#f6f8fa", "panel": "#ffffff", "fg": "#24292f",
        "muted": "#57606a", "value": "#1a7f37", "border": "#d0d7de",
        "track": "#eaeef2",
    },
    "dark": {
        "bg": "#0d1117", "panel": "#161b22", "fg": "#e6edf3",
        "muted": "#8b949e", "value": "#7ee787", "border": "#30363d",
        "track": "#21262d",
    },
}


def graphql(query: str, variables: dict) -> dict:
    token = os.environ["GITHUB_TOKEN"]
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
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"], ensure_ascii=False))
    return payload["data"]["user"]


def collect() -> dict:
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(days=365)
    query = """
    query($login:String!, $from:DateTime!, $to:DateTime!) {
      user(login:$login) {
        followers { totalCount }
        repositories(first:100, ownerAffiliations:[OWNER], privacy:PUBLIC) {
          totalCount
          nodes {
            isFork
            stargazerCount
            languages(first:10, orderBy:{field:SIZE, direction:DESC}) {
              edges { size node { name color } }
            }
          }
        }
        contributionsCollection(from:$from, to:$to) {
          totalCommitContributions
          totalPullRequestContributions
          totalIssueContributions
          contributionCalendar { totalContributions }
        }
      }
    }
    """
    user = graphql(query, {
        "login": USERNAME,
        "from": start.isoformat(),
        "to": end.isoformat(),
    })

    repos = user["repositories"]
    owned = [repo for repo in repos["nodes"] if not repo["isFork"]]
    stars = sum(repo["stargazerCount"] for repo in owned)

    sizes: dict[str, int] = {}
    colors: dict[str, str] = {}
    for repo in owned:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            sizes[name] = sizes.get(name, 0) + edge["size"]
            colors[name] = edge["node"].get("color") or "#8b949e"

    total = sum(sizes.values()) or 1
    languages = [
        {"name": name, "percent": size / total * 100, "color": colors[name]}
        for name, size in sorted(sizes.items(), key=lambda item: item[1], reverse=True)[:5]
    ]

    contributions = user["contributionsCollection"]
    return {
        "repos": repos["totalCount"],
        "stars": stars,
        "followers": user["followers"]["totalCount"],
        "commits": contributions["totalCommitContributions"],
        "contributions": contributions["contributionCalendar"]["totalContributions"],
        "pull_requests": contributions["totalPullRequestContributions"],
        "issues": contributions["totalIssueContributions"],
        "languages": languages,
        "updated": end.strftime("%d/%m/%Y"),
    }


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def update_profile(theme: str, stats: dict) -> None:
    path = ASSETS / f"profile-{theme}.svg"
    svg = path.read_text(encoding="utf-8")

    line_508 = (
        '<text x="0" y="508"><tspan class="key">Repos</tspan>'
        '<tspan class="muted"> ........... </tspan>'
        f'<tspan class="value">{esc(stats["repos"])}</tspan>'
        '<tspan class="muted">    Stars .... </tspan>'
        f'<tspan class="value">{esc(stats["stars"])}</tspan>'
        '<tspan class="muted">    Followers .... </tspan>'
        f'<tspan class="value">{esc(stats["followers"])}</tspan></text>'
    )
    line_533 = (
        '<text x="0" y="533"><tspan class="key">Commits</tspan>'
        '<tspan class="muted"> ......... </tspan>'
        f'<tspan class="value">{esc(stats["commits"])}</tspan>'
        '<tspan class="muted">    Contributions .... </tspan>'
        f'<tspan class="value">{esc(stats["contributions"])}</tspan></text>'
    )

    svg = re.sub(r'<text x="0" y="508">.*?</text>', line_508, svg)
    svg = re.sub(r'<text x="0" y="533">.*?</text>', line_533, svg)
    path.write_text(svg, encoding="utf-8")


def stats_svg(theme_name: str, stats: dict) -> str:
    theme = THEMES[theme_name]
    rows = []
    y = 240
    for language in stats["languages"][:5]:
        width = max(4, round(language["percent"] * 3.2))
        rows += [
            f'<text x="560" y="{y}" class="language">{esc(language["name"])}</text>',
            f'<text x="915" y="{y}" text-anchor="end" class="muted">{language["percent"]:.1f}%</text>',
            f'<rect x="560" y="{y + 8}" width="320" height="7" rx="3.5" fill="{theme["track"]}"/>',
            f'<rect x="560" y="{y + 8}" width="{width}" height="7" rx="3.5" fill="{esc(language["color"])}"/>',
        ]
        y += 35

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="420" viewBox="0 0 1000 420">
<style>
text{{font-family:Consolas,'Courier New',monospace;fill:{theme["fg"]}}}
.title{{font-size:20px;font-weight:700}}
.label{{font-size:13px;fill:{theme["muted"]}}}
.number{{font-size:27px;font-weight:700;fill:{theme["value"]}}}
.muted{{font-size:12px;fill:{theme["muted"]}}}
.language{{font-size:13px;font-weight:700}}
</style>
<rect x="1" y="1" width="998" height="418" rx="18" fill="{theme["bg"]}" stroke="{theme["border"]}" stroke-width="2"/>
<text x="28" y="38" class="title">GitHub Stats</text>
<text x="972" y="36" text-anchor="end" class="muted">atualizado em {stats["updated"]}</text>
<line x1="28" y1="54" x2="972" y2="54" stroke="{theme["border"]}"/>
<g transform="translate(28,78)"><rect width="220" height="82" rx="12" fill="{theme["panel"]}" stroke="{theme["border"]}"/><text x="18" y="27" class="label">COMMITS · 12 MESES</text><text x="18" y="62" class="number">{stats["commits"]}</text></g>
<g transform="translate(266,78)"><rect width="220" height="82" rx="12" fill="{theme["panel"]}" stroke="{theme["border"]}"/><text x="18" y="27" class="label">CONTRIBUIÇÕES</text><text x="18" y="62" class="number">{stats["contributions"]}</text></g>
<g transform="translate(504,78)"><rect width="220" height="82" rx="12" fill="{theme["panel"]}" stroke="{theme["border"]}"/><text x="18" y="27" class="label">REPOSITÓRIOS PÚBLICOS</text><text x="18" y="62" class="number">{stats["repos"]}</text></g>
<g transform="translate(742,78)"><rect width="230" height="82" rx="12" fill="{theme["panel"]}" stroke="{theme["border"]}"/><text x="18" y="27" class="label">SEGUIDORES · ESTRELAS</text><text x="18" y="62" class="number">{stats["followers"]} · {stats["stars"]}</text></g>
<text x="28" y="205" class="title">Atividade</text>
<text x="28" y="238" class="label">Pull requests</text><text x="235" y="238" class="number" style="font-size:20px">{stats["pull_requests"]}</text>
<text x="28" y="276" class="label">Issues</text><text x="235" y="276" class="number" style="font-size:20px">{stats["issues"]}</text>
<text x="28" y="314" class="label">Período</text><text x="235" y="314" class="muted">últimos 365 dias</text>
<text x="560" y="205" class="title">Linguagens mais usadas</text>
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
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
