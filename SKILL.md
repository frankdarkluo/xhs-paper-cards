---
name: xhs-paper-cards
description: "Generates 5-card 3:4 Xiaohongshu (小红书) paper-sharing carousels (PNG) and post copy from PDFs, LaTeX/arXiv manuscripts, notes, or rough slide screenshots. Use for 小红书论文分享, 论文解读卡片, paper-to-carousel graphics, or redesigning auto-generated paper cards."
---

# Xiaohongshu Paper Cards

Turns a research paper, technical report, or rough slide screenshot into five `3:4` (`1080x1440`, `@1.5x` default) editorial PNG cards plus ready-to-publish Xiaohongshu copy.

Resolve `SKILL_DIR` to the absolute directory containing this `SKILL.md` from runtime skill context before invoking bundled files.

## Workflow

### 1. Ground facts in the source
Read the user's paper (LaTeX, PDF, arXiv text, notes, or screenshot) and extract verbatim numbers, baselines, benchmark count, mechanism thresholds, and author-acknowledged caveats.
- Pair every quantitative claim with its comparison baseline and evaluation scope.
- Attribute strong claims to the authors (`作者在 5 个代码库上验证`) and reserve adjectives on a card for properties directly shown by that card's evidence.
- **Completion**: Every number slated for the deck traces to a verified source passage with explicit baseline context.

### 2. Author `carousel.json`
Read [`$SKILL_DIR/references/example_agensh.json`](references/example_agensh.json) once as the single schema and copy-length contract, then write `<output_dir>/carousel.json`.
- **Route `"theme"` by domain**:
  - `"sage"` — multi-agent systems, software engineering, lab technical reports.
  - `"terracotta"` — LLM methodology, benchmarks, surveys, reading notes.
  - `"blueprint"` — systems/infra acceleration, computer vision, robotics.
  - `"terminal"` — weekly multi-paper roundups or hardware/compute digests.
- **Assign distinct signal per stratum on Card 01 (`cover`)**:
  - `title` (`<= 20` chars, 2 lines via `\n`, wrap one phrase in `{...}` for accent): counter-intuitive conflict or scale hook.
  - Hero visual: use `chart` (3–8 points; set `pos` for log/non-uniform x-spacing) when a clear progression exists, or omit `chart` and populate `hero_grid` (`4` cells) for architectural/survey papers.
  - `metrics` (`2` items): cross-task delta + structural invariant, carrying fresh numbers distinct from `title` and `chart`.
- **Keep inner cards (`02`–`05`) tight**:
  - `02` (`problem`): 3 naive-baseline bottlenecks (`<= 14` chars head, `<= 32` chars body) vs. 3 new-perspective shifts + 1 root-cause `insight` (`<= 65` chars).
  - `03` (`method`): 3–4 causal steps (`name`, `tag`, `desc <= 48` chars; mark decisive step `"highlight": true`) + `key_knife` (`<= 65` chars).
  - `04` (`evidence`): conclusion-led `title`, 3–5 horizontal `bars` (`"is_ours": true` on proposed method), and 2 `ablations`.
  - `05` (`takeaways`): 2 transferable engineering/research judgments, 1–2 concrete `limitations` (cost, assumptions, validator dependency), and 3 `cheat_sheet` metadata pairs.
- **Completion**: `<output_dir>/carousel.json` is valid JSON satisfying all six required sections with zero number repeated across Card 01 strata.

### 3. Render and visually verify all 5 PNGs
Run the bundled Playwright renderer:

```bash
python3 "$SKILL_DIR/scripts/render_xhs_cards.py" "<output_dir>/carousel.json" -o "<output_dir>"
```

- When the renderer's DOM guard raises `Layout overflow detected on <file>`, tighten the named card's text fields in `carousel.json` and re-run until exit code `0`.
- View the generated `01_cover.png` through `05_takeaways.png` at full resolution. Check for single-character orphan wraps (`孤字成行`) or chart label collisions (`"label_pos": "below"` flips any crowded point label below the curve), and re-render if needed.
- **Completion**: Renderer exits `0`, all five PNGs exist, and visual inspection confirms clean line breaks and unobstructed labels across `01`–`05`.

### 4. Write `xiaohongshu-copy.md`
Save `<output_dir>/xiaohongshu-copy.md` alongside the PNGs containing:
- **Title** (`<= 20` CJK chars) + 2 alternatives.
- **Body** (`<= 850` chars, well inside Xiaohongshu's `1,000`-char ceiling): 1-sentence hook → 3–5 bullet takeaways → 1 honest boundary → discussion question.
- **Tags**: 5–7 relevant `#topic` tags.
- **Completion**: `xiaohongshu-copy.md` saved in `<output_dir>` with title `<= 20` chars and body `<= 850` chars.
