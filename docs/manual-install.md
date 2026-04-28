# Manual install (no npx)

If you don't have `npx skills` available, copy `SKILL.md` directly into your agent's skills directory. Same file for every agent — only the path differs.

Pick the one matching your tool:

```bash
# Claude Code (personal: works in every project)
mkdir -p ~/.claude/skills/clipsheet
curl -L https://raw.githubusercontent.com/poonamsnair/clipsheet/main/skills/clipsheet/SKILL.md \
  -o ~/.claude/skills/clipsheet/SKILL.md
```

```bash
# Cursor (project-scoped, run from your project root)
mkdir -p .cursor/skills/clipsheet
curl -L https://raw.githubusercontent.com/poonamsnair/clipsheet/main/skills/clipsheet/SKILL.md \
  -o .cursor/skills/clipsheet/SKILL.md
```

```bash
# Codex CLI
mkdir -p ~/.codex/skills/clipsheet
curl -L https://raw.githubusercontent.com/poonamsnair/clipsheet/main/skills/clipsheet/SKILL.md \
  -o ~/.codex/skills/clipsheet/SKILL.md
```

```bash
# Gemini CLI
mkdir -p ~/.gemini/skills/clipsheet
curl -L https://raw.githubusercontent.com/poonamsnair/clipsheet/main/skills/clipsheet/SKILL.md \
  -o ~/.gemini/skills/clipsheet/SKILL.md
```

For other agents (Aider, Goose, OpenClaw, Antigravity, etc.), check that agent's docs for its skills directory. The file goes in a `clipsheet/` subdirectory and must be named exactly `SKILL.md`.

After install, ask the agent: "What skills are available?" — `clipsheet` should appear in the list.
