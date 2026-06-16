---
name: roblox-docs
description: >-
  Look up the official Roblox creator documentation (Engine API + creator
  guides) and get back an accurate, cited summary. This is a tool for YOU, the
  agent — not just the user. Reach for it proactively: whenever you are even
  slightly unsure about a Roblox/Luau API (a class, method, property, event,
  datatype, enum, global, library, service, or Studio feature), whenever you
  need deeper knowledge than you can confidently recall, and whenever you want
  to compare or explore alternative APIs for a task. Especially use it while
  PLANNING Roblox work — before committing to an approach — to ground your
  assumptions in real docs instead of guessing. Roblox's API changes often, so
  prefer verifying here over answering from memory; it is the reliable way to
  avoid hallucinated or outdated API signatures. Triggers on any Roblox or Luau
  development task, even when the user never says "docs".
---

# Roblox creator-docs search

This skill answers Roblox/Luau questions from the *official* docs instead of
memory. It works off a local, auto-updating clone of
[Roblox/creator-docs](https://github.com/Roblox/creator-docs), so it stays
current and can full-text search every class, datatype, enum, global, library,
and guide at once — something live web fetching of single doc pages can't do.

## When to reach for this

This is primarily a tool for *you*, the agent, to keep yourself honest about an
API surface that changes faster than training data. Don't wait for the user to
ask for "docs". Use it when:

- **You're unsure.** You're about to write or recommend an API call (a method
  name, its arguments, return type, an enum value, a property) and you aren't
  fully confident it's correct and current. Verifying costs little; a
  hallucinated signature costs the user real debugging time.
- **You need depth.** The task needs more than a name — behavior, edge cases,
  deprecations, replacements, or how pieces fit together.
- **You're exploring alternatives.** There's more than one API/approach for the
  goal and you want to compare what the docs actually recommend.
- **You're planning.** *Especially* during planning, before you lock in an
  approach — check the docs first so the plan isn't built on wrong assumptions.
  A plan grounded in real APIs beats one you have to unwind later.

When in doubt, look it up. The whole point is to replace confident guessing with
cited fact.

## Why a subagent

Doc files are large (a single class YAML can be thousands of lines). Reading
several of them directly into this conversation would bury the actual answer in
raw reference text. So delegate the lookup to an **`Explore` subagent**: it does
the searching and full-file reading in its own context and returns only a tight,
cited answer. Your context stays clean.

## How to use it

When a Roblox/Luau question comes up, dispatch one `Explore` subagent (via the
Agent tool) with the prompt below. The search script lives at:

```
${CLAUDE_PLUGIN_ROOT}/skills/roblox-docs/scripts/robloxdocs.py
```

Substitute that absolute path and the user's question into this prompt:

> You are looking up official Roblox documentation to answer a question.
> Use the bundled search tool — do not fetch the web and do not answer from
> memory.
>
> 1. Run: `python3 <SCRIPT_PATH> "<search query>"`
>    The first run clones the docs (~1 min); later runs reuse a cached clone and
>    auto-pull when stale. It prints ranked `path:line` matches with snippets.
> 2. Pick the most relevant files and `Read` them in full (the snippets are only
>    for ranking — the real answer is in the file).
> 3. If the first query misses, try again with different terms (an exact API
>    name, a related class, or the feature's plain-English name). The tool
>    accepts dotted/colon forms like `TweenService:Create`.
> 4. Return a concise answer: the relevant API signatures / steps, a short code
>    example if useful, and cite each fact as `path:line` from the clone. If the
>    docs genuinely don't cover it, say so — don't invent API.
>
> Question: <THE USER'S QUESTION>

Then relay the subagent's answer to the user, keeping its citations.

## Notes

- **Prerequisites:** `git` and Python 3 on PATH. `ripgrep` (`rg`) is used if
  present for faster search but isn't required.
- **Freshness:** the clone auto-pulls when older than 24h. To force a refresh,
  the subagent (or you) can run `python3 <SCRIPT_PATH> --update`.
- **Multiple questions:** batch related lookups into one subagent prompt so it
  can search and read once rather than spinning up repeatedly.
- **Offline:** if a pull fails, the tool falls back to the cached clone and
  notes it — the answer may be slightly stale but still works.
