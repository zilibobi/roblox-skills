# roblox-skills

Roblox/Luau skills for AI coding agents. Right now there's one skill,
`roblox-docs`, but the repo is set up to hold more. It ships as a Claude Code
plugin, and you can also install it into other agents (Cursor, Codex, Gemini)
with the [`skills`](https://skills.sh) CLI.

## The `roblox-docs` skill

Roblox's API moves faster than any model's training data, so agents tend to
guess at method names and signatures that don't exist anymore (or never did).
This skill fixes that by having the agent look things up in the official
[Roblox/creator-docs](https://github.com/Roblox/creator-docs) instead of
trusting its memory.

Here's the flow when a Roblox question comes up:

1. The skill triggers on anything Roblox or Luau related: a class, a method, an
   enum, a Studio feature, a "how do I..." question.
2. The agent hands the lookup to an `Explore` subagent so the search and the
   big doc files stay out of the main conversation.
3. That subagent runs `skills/roblox-docs/scripts/robloxdocs.py`, which keeps a
   local clone of the docs (cached, auto-updated) and searches all ~2,200 files
   at once: the API reference YAML and the written guides.
4. It reads the top hits and replies with a short answer plus `path:line`
   citations. Your context never fills up with raw reference dumps.

Why a local clone instead of fetching `create.roblox.com` pages live? Because a
clone lets the agent grep across every method and property in one pass. The
official per-page index can't do that, and that search reach is the whole point.

## Install

Use the `skills` CLI ([skills.sh](https://skills.sh)) for any agent. It detects
what you have installed and puts the skill in the right place:

```sh
npx skills add https://github.com/zilibobi/roblox-skills --skill roblox-docs
```

Or, in Claude Code, add it as a plugin:

```sh
/plugin marketplace add zilibobi/roblox-skills
/plugin install roblox-skills@roblox-skills
```

## Requirements

You need `git` and Python 3 on your PATH. `ripgrep` (`rg`) is optional; if it's
there the search runs faster.

## Running the search tool yourself

You don't need an agent to use it:

```sh
cd skills/roblox-docs
python3 scripts/robloxdocs.py "TweenService:Create"   # ranked, cited snippets
python3 scripts/robloxdocs.py "anchored part" --top 5 --context 4
python3 scripts/robloxdocs.py --update                # force a git pull
```

The clone lives in your OS cache directory, which you can override with
`ROBLOX_DOCS_CACHE`:

- Linux: `$XDG_CACHE_HOME/roblox-docs-explorer` (or `~/.cache/...`)
- macOS: `~/Library/Caches/roblox-docs-explorer`
- Windows: `%LOCALAPPDATA%\roblox-docs-explorer`

It pulls fresh docs once a day. If you're offline, it just uses the copy it has.

## Adding another skill

Drop a new `skills/<name>/SKILL.md` in (plus any `scripts/`, `references/`, or
`assets/` it needs). Both the plugin loader and the `skills` CLI find it on their
own, so there's no manifest to edit. Bump `version` in
`.claude-plugin/plugin.json` when you publish.

```
roblox-skills/
├── .claude-plugin/{plugin.json, marketplace.json}
└── skills/
    └── roblox-docs/{SKILL.md, scripts/, tests/}
```
