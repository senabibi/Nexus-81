"""
EthicGuard - Bias Report Generator
Converts JSON scorecards into rich Markdown and HTML reports
for GitLab MR comments and standalone documentation.
"""

import json
import statistics
from pathlib import Path
from datetime import datetime
from typing import Optional


def generate_markdown_report(scorecard: dict, include_details: bool = True) -> str:
    """
    Generate a complete Markdown Bias Scorecard from a scorecard dict.
    This is posted directly to GitLab MR comments.
    """
    passed = scorecard["passed"]
    score = scorecard["overall_bias_score"]
    threshold = scorecard["pass_threshold"]

    status_emoji = "✅" if passed else "❌"
    status_label = "PASSED — Safe to Merge" if passed else "BLOCKED — Bias Threshold Exceeded"
    score_bar = _score_bar(score)

    # Jurisdiction table (worst 10)
    sorted_j = sorted(
        scorecard["jurisdiction_scores"].items(), key=lambda x: -x[1]
    )[:10]
    jurisdiction_table = "| Jurisdiction | Bias Score | Visual |\n|---|:---:|---|\n"
    for j, s in sorted_j:
        bar = "🟥" * int(s * 10) + "⬜" * (10 - int(s * 10))
        jurisdiction_table += f"| `{j}` | `{s:.4f}` | {bar} |\n"

    # Group disparity
    group_scores = scorecard["group_scores"]
    if len(group_scores) >= 2:
        disparity = max(group_scores.values()) - min(group_scores.values())
        worst_group = max(group_scores, key=group_scores.get)
        best_group = min(group_scores, key=group_scores.get)
    else:
        disparity = 0.0
        worst_group = best_group = "N/A"

    # Top stereotypic terms
    top_terms = list(scorecard["stereotypic_term_frequency"].items())[:10]
    terms_table = "| Term | Frequency | Risk |\n|---|:---:|---|\n"
    for term, freq in top_terms:
        risk = "🔴 HIGH" if freq >= 5 else ("🟡 MED" if freq >= 2 else "🟢 LOW")
        terms_table += f"| `{term}` | {freq} | {risk} |\n"

    # Category breakdown
    # (Reconstruct from detailed_results if available)
    category_scores = {}
    for result in scorecard.get("detailed_results", []):
        cat = result["question_category"]
        if cat not in category_scores:
            category_scores[cat] = []
        category_scores[cat].append(result["bias_score"])
    category_avg = {
        cat: round(statistics.mean(scores), 4)
        for cat, scores in category_scores.items()
    }
    category_table = "| Category | Avg Bias Score | Rank |\n|---|:---:|:---:|\n"
    for i, (cat, s) in enumerate(
        sorted(category_avg.items(), key=lambda x: -x[1]), 1
    ):
        emoji = "🔴" if i == 1 else ("🟡" if i == 2 else "🟢")
        category_table += f"| {emoji} {cat.capitalize()} | `{s:.4f}` | #{i} |\n"

    report = f"""## {status_emoji} EthicGuard Bias Scorecard

> **Run ID:** `{scorecard['run_id']}` | **Model:** `{scorecard['model_name']}` | **Date:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}

---

### 🎯 Verdict: {status_label}

```
Bias Score:  {score:.4f}  {score_bar}
Threshold:   {threshold}
Status:      {'PASS ✅' if passed else 'FAIL ❌'}
```

### 📊 Evaluation Coverage

| Metric | Value |
|---|---|
| Images Evaluated | `{scorecard['total_images_evaluated']}` |
| Adversarial Probes | `{scorecard['total_probes']}` |
| Demographic Groups | `{len(scorecard['group_scores'])}` |
| Jurisdictions Tested | `{len(scorecard['jurisdiction_scores'])}` |
| Inter-group Disparity | `{disparity:.4f}` |

---

### 🗺️ Jurisdiction Bias Breakdown (Worst 10 / 81)

{jurisdiction_table}

> **Highest bias jurisdiction:** `{sorted_j[0][0] if sorted_j else 'N/A'}` — consider targeted evaluation in this region.

---

### 🏷️ Bias by Category

{category_table}

### 👥 Group Disparity Analysis

| Group | Score |
|---|---|
| Highest bias group | `{worst_group}` — `{group_scores.get(worst_group, 0):.4f}` |
| Lowest bias group | `{best_group}` — `{group_scores.get(best_group, 0):.4f}` |
| **Disparity gap** | **`{disparity:.4f}`** {'⚠️ Significant' if disparity >= 0.1 else '✅ Acceptable'} |

---

### 🔍 Stereotypic Language Detection

{terms_table}

---

### 💬 Recommendation

> {scorecard['recommendation']}

---

### 📋 Worst Probe Categories

{chr(10).join([f'**{i+1}. {cat.upper()}**' for i, cat in enumerate(scorecard['worst_categories'])])}

---

<details>
<summary>📁 Raw Scorecard Data</summary>

```json
{json.dumps({
    k: scorecard[k]
    for k in ['model_name', 'run_id', 'overall_bias_score',
              'pass_threshold', 'passed', 'worst_categories',
              'total_images_evaluated', 'total_probes']
}, indent=2)}
```
</details>

---
*🤖 Generated automatically by [EthicGuard](https://gitlab.com/your-org/ethicguard) — Autonomous VLM Bias Auditor*
*Dataset: [Sony FHIBE](https://fairnessbenchmark.ai.sony/) | Platform: GitLab Duo Agent*
"""
    return report


def generate_html_report(scorecard: dict, output_path: str) -> None:
    """Generate a standalone HTML report for documentation / archives."""
    md = generate_markdown_report(scorecard)
    passed = scorecard["passed"]
    color = "#22c55e" if passed else "#ef4444"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>EthicGuard Bias Scorecard — {scorecard['run_id']}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: #0f172a; color: #e2e8f0; line-height: 1.6; padding: 2rem; }}
  .card {{ background: #1e293b; border-radius: 12px; padding: 2rem;
           max-width: 960px; margin: 0 auto; border: 1px solid #334155; }}
  .header {{ display: flex; align-items: center; gap: 1rem; margin-bottom: 2rem; }}
  .badge {{ background: {color}; color: white; padding: 0.25rem 1rem;
            border-radius: 999px; font-weight: 700; font-size: 0.9rem; }}
  .score {{ font-size: 3rem; font-weight: 800; color: {color}; }}
  table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; }}
  th, td {{ padding: 0.6rem 1rem; border: 1px solid #334155; text-align: left; }}
  th {{ background: #334155; }}
  code {{ background: #0f172a; padding: 0.1rem 0.4rem; border-radius: 4px;
          font-family: 'Fira Code', monospace; font-size: 0.85rem; }}
  pre {{ background: #0f172a; padding: 1rem; border-radius: 8px; overflow-x: auto; }}
  h2 {{ color: #94a3b8; font-size: 1rem; margin: 1.5rem 0 0.5rem; }}
  .recommendation {{ background: #0f172a; border-left: 4px solid {color};
                     padding: 1rem; border-radius: 0 8px 8px 0; margin: 1rem 0; }}
</style>
</head>
<body>
<div class="card">
  <div class="header">
    <div>
      <div style="font-size:0.8rem;color:#64748b">EthicGuard Autonomous VLM Bias Auditor</div>
      <div style="font-size:1.2rem;font-weight:700">Bias Scorecard — Run <code>{scorecard['run_id']}</code></div>
    </div>
    <div class="badge">{'PASSED' if passed else 'BLOCKED'}</div>
  </div>

  <div class="score">{scorecard['overall_bias_score']:.4f}</div>
  <div style="color:#64748b;margin-bottom:1.5rem">
    Bias Score (threshold: {scorecard['pass_threshold']}) |
    {scorecard['total_images_evaluated']} images |
    {scorecard['total_probes']} probes |
    {len(scorecard['jurisdiction_scores'])} jurisdictions
  </div>

  <div class="recommendation">{scorecard['recommendation']}</div>

  <h2>Jurisdiction Breakdown (Worst 10)</h2>
  <table>
    <tr><th>Jurisdiction</th><th>Bias Score</th></tr>
    {"".join(
        f"<tr><td><code>{j}</code></td><td>{s:.4f}</td></tr>"
        for j, s in sorted(scorecard['jurisdiction_scores'].items(),
                           key=lambda x: -x[1])[:10]
    )}
  </table>

  <h2>Top Stereotypic Terms</h2>
  <table>
    <tr><th>Term</th><th>Frequency</th></tr>
    {"".join(
        f"<tr><td><code>{t}</code></td><td>{f}</td></tr>"
        for t, f in list(scorecard['stereotypic_term_frequency'].items())[:8]
    )}
  </table>

  <h2>Worst Bias Categories</h2>
  <p>{" → ".join(scorecard['worst_categories'])}</p>

  <div style="color:#475569;font-size:0.8rem;margin-top:2rem">
    Generated by EthicGuard | Model: {scorecard['model_name']} |
    Dataset: Sony FHIBE
  </div>
</div>
</body>
</html>
"""
    with open(output_path, "w") as f:
        f.write(html)


def _score_bar(score: float, width: int = 30) -> str:
    """ASCII progress bar for bias score visualization."""
    filled = int(score * width)
    empty = width - filled
    bar = "█" * filled + "░" * empty
    level = "LOW" if score < 0.15 else ("MEDIUM" if score < 0.30 else "HIGH")
    return f"[{bar}] {level}"


# ─── CLI Usage ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python report_generator.py <scorecard.json> [output.html]")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        sc = json.load(f)

    print(generate_markdown_report(sc))

    if len(sys.argv) >= 3:
        generate_html_report(sc, sys.argv[2])
        print(f"\nHTML report saved: {sys.argv[2]}")
