# xhs-paper-cards

Agent skill and Playwright renderer that turns academic papers, technical reports, or rough slide screenshots into a **5-card `3:4` (`1080×1440`) Xiaohongshu (小红书) editorial carousel** plus ready-to-post copy.

## Structure

- [`SKILL.md`](./SKILL.md) — Agent workflow (source grounding → `carousel.json` authoring → Playwright render & DOM/visual verification → `xiaohongshu-copy.md`).
- [`scripts/render_xhs_cards.py`](./scripts/render_xhs_cards.py) — Zero-extra-dependency Python + Playwright HTML/SVG renderer with 4 semantic palettes (`sage`, `terracotta`, `blueprint`, `terminal`), `2×2` chartless fallback, and automated DOM overflow guard.
- [`references/example_agensh.json`](./references/example_agensh.json) — Complete 5-card schema and copy-length reference (`arXiv:2609.26781`).

## Install as an Agent Skill

```bash
# GitHub Copilot CLI / VS Code
git clone https://github.com/frankdarkluo/xhs-paper-cards.git ~/.copilot/skills/xhs-paper-cards

# Claude Code
git clone https://github.com/frankdarkluo/xhs-paper-cards.git ~/.claude/skills/xhs-paper-cards
```

## Standalone CLI Usage

Requires Python 3.10+ and `playwright` (`pip install playwright && playwright install chromium`).

```bash
# Render 5 standalone 3:4 PNGs (default --scale 1.5 -> 1620x2160)
python3 scripts/render_xhs_cards.py references/example_agensh.json -o ./output

# Run built-in layout, fallback, dark-theme, escaping, and overflow self-check
python3 scripts/render_xhs_cards.py --self-check
```
