"""
EthicGuard - Priority 2: FHIBE Metadata Analysis

Analyses the Sony FHIBE dataset structure using the official
fhibe_evaluation_api directory layout:

  fhibe.{version}_downsampled_public/
    data/
      processed/           ← metadata CSVs (primary source)
        fhibe_downsampled.csv
        fhibe_face_crop_align.csv
      annotator_metadata/  ← annotator attribute data
      aggregated_results/  ← pre-computed task results
      protocol/            ← evaluation protocol files
      raw/
        fhibe_downsampled/ ← actual image files

Outputs:
  - Coverage statistics across all 81 jurisdictions
  - Demographic balance assessment (age, gender, skin tone)
  - Under/over-represented group identification
  - Sampling strategy recommendations for bias evaluation
  - JSON + Markdown reports

Usage:
  python fhibe_analysis.py --fhibe-root /data/fhibe.v1_downsampled_public
  python fhibe_analysis.py --fhibe-root /data/fhibe.v1_downsampled_public \\
      --output-dir ./reports
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("EthicGuard.FHIBEAnalysis")


# ─────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────

# Primary metadata file names (checked in order)
METADATA_CANDIDATES = [
    "fhibe_downsampled.csv",
    "fhibe_face_crop_align.csv",
    "metadata.csv",
    "fhibe_metadata.csv",
    "fhibe.csv",
]

# Map EthicGuard standard field names → known FHIBE CSV column variants
COLUMN_ALIASES: dict[str, list[str]] = {
    "image_id":            ["image_id", "id", "img_id", "image_name"],
    "filename":            ["filename", "file_name", "file", "image_file", "path"],
    "jurisdiction":        ["jurisdiction", "country", "region", "location_code"],
    "age_group":           ["age_group", "age_bracket", "age_range", "age"],
    "gender_presentation": ["gender_presentation", "gender", "gender_identity",
                            "self_reported_gender"],
    "skin_tone":           ["skin_tone", "monk_scale", "monk_skin_tone",
                            "fitzpatrick", "skin_tone_monk"],
    "environment":         ["environment", "setting", "location_type", "scene"],
    "camera_type":         ["camera_type", "camera", "device_type"],
    "num_subjects":        ["num_subjects", "n_subjects", "subject_count",
                            "number_of_subjects"],
    "annotator_id":        ["annotator_id", "annotator", "rater_id"],
}

# Continent grouping for regional bias analysis (ISO 2-letter codes)
JURISDICTION_REGION: dict[str, str] = {
    # Africa
    "ZA": "Africa", "NG": "Africa", "KE": "Africa", "GH": "Africa",
    "ET": "Africa", "TZ": "Africa", "EG": "Africa", "MA": "Africa",
    "SN": "Africa", "CI": "Africa", "CM": "Africa", "UG": "Africa",
    "ZW": "Africa", "MZ": "Africa", "ZM": "Africa", "RW": "Africa",
    "AO": "Africa", "SD": "Africa", "DZ": "Africa", "TN": "Africa",
    # Asia
    "IN": "Asia", "CN": "Asia", "JP": "Asia", "KR": "Asia",
    "ID": "Asia", "PH": "Asia", "VN": "Asia", "TH": "Asia",
    "BD": "Asia", "PK": "Asia", "LK": "Asia", "NP": "Asia",
    "MM": "Asia", "KH": "Asia", "MY": "Asia", "SG": "Asia",
    "HK": "Asia", "TW": "Asia", "MN": "Asia", "LA": "Asia",
    # Middle East
    "SA": "Middle East", "AE": "Middle East", "TR": "Middle East",
    "IL": "Middle East", "JO": "Middle East", "IQ": "Middle East",
    "IR": "Middle East", "LB": "Middle East", "KW": "Middle East",
    "QA": "Middle East", "BH": "Middle East", "OM": "Middle East",
    # Europe
    "DE": "Europe", "FR": "Europe", "GB": "Europe", "IT": "Europe",
    "ES": "Europe", "SE": "Europe", "NO": "Europe", "FI": "Europe",
    "PL": "Europe", "NL": "Europe", "BE": "Europe", "CH": "Europe",
    "AT": "Europe", "PT": "Europe", "GR": "Europe", "RO": "Europe",
    "HU": "Europe", "CZ": "Europe", "UA": "Europe", "RU": "Europe",
    "DK": "Europe", "IE": "Europe", "HR": "Europe", "SK": "Europe",
    # Americas
    "US": "Americas", "CA": "Americas", "BR": "Americas", "MX": "Americas",
    "AR": "Americas", "CO": "Americas", "CL": "Americas", "PE": "Americas",
    "VE": "Americas", "EC": "Americas", "BO": "Americas", "UY": "Americas",
    "PY": "Americas", "GT": "Americas", "CU": "Americas", "DO": "Americas",
    # Oceania
    "AU": "Oceania", "NZ": "Oceania", "FJ": "Oceania", "PG": "Oceania",
}

MONK_SCALE_LABELS = {
    "1": "Monk 1 (lightest)", "2": "Monk 2", "3": "Monk 3",
    "4": "Monk 4", "5": "Monk 5", "6": "Monk 6",
    "7": "Monk 7", "8": "Monk 8", "9": "Monk 9",
    "10": "Monk 10 (darkest)",
}


# ─────────────────────────────────────────────────────────────────
# FHIBEAnalyzer
# ─────────────────────────────────────────────────────────────────

class FHIBEAnalyzer:
    """
    Analyses the Sony FHIBE dataset's demographic coverage and
    generates bias evaluation sampling strategy recommendations.
    """

    def __init__(self, fhibe_root: str):
        self.fhibe_root  = Path(fhibe_root)
        self.metadata_dir = self.fhibe_root / "data" / "processed"
        self.images_dir  = (
            self.fhibe_root / "data" / "raw" / "fhibe_downsampled"
        )
        self.annotator_dir = self.fhibe_root / "data" / "annotator_metadata"

        self.df: Optional[pd.DataFrame]          = None
        self.ann_df: Optional[pd.DataFrame]      = None
        self._col_map: dict[str, str]            = {}
        self._metadata_path: Optional[Path]      = None

    # ── Loading ───────────────────────────────────────────────────

    def load(self) -> "FHIBEAnalyzer":
        """
        Load FHIBE metadata and optionally annotator metadata.
        Auto-discovers CSV files in the official directory structure.
        """
        self._metadata_path = self._find_metadata()
        logger.info(f"Loading FHIBE metadata: {self._metadata_path}")
        self.df = pd.read_csv(self._metadata_path, low_memory=False)
        self._build_column_map()
        logger.info(
            f"  Loaded {len(self.df):,} records | "
            f"{len(self.df.columns)} columns"
        )

        # Try loading annotator metadata (optional)
        ann_candidates = list(self.annotator_dir.glob("*.csv")) if self.annotator_dir.exists() else []
        if ann_candidates:
            try:
                self.ann_df = pd.read_csv(ann_candidates[0], low_memory=False)
                logger.info(
                    f"  Annotator metadata: {len(self.ann_df):,} records "
                    f"from {ann_candidates[0].name}"
                )
            except Exception as e:
                logger.warning(f"  Could not load annotator metadata: {e}")

        return self

    def _find_metadata(self) -> Path:
        if not self.metadata_dir.exists():
            raise FileNotFoundError(
                f"FHIBE processed/ directory not found: {self.metadata_dir}\n"
                "Download dataset from https://fairnessbenchmark.ai.sony/download\n"
                "Expected: fhibe.{{version}}_downsampled_public/data/processed/"
            )
        for name in METADATA_CANDIDATES:
            p = self.metadata_dir / name
            if p.exists():
                return p
        # Fallback: any CSV in the directory
        csvs = sorted(self.metadata_dir.glob("*.csv"))
        if csvs:
            logger.warning(
                f"Primary metadata files not found; using first CSV: {csvs[0].name}"
            )
            return csvs[0]
        raise FileNotFoundError(
            f"No CSV metadata found in {self.metadata_dir}"
        )

    def _build_column_map(self) -> None:
        actual = {c.lower(): c for c in self.df.columns}
        for standard, aliases in COLUMN_ALIASES.items():
            for alias in aliases:
                if alias.lower() in actual:
                    self._col_map[standard] = actual[alias.lower()]
                    break

        mapped = list(self._col_map.keys())
        missing = [k for k in ["image_id", "jurisdiction"] if k not in mapped]
        if missing:
            logger.warning(
                f"Column mapping incomplete for: {missing}. "
                f"Available columns: {list(self.df.columns)}"
            )
        logger.info(f"  Column map: {self._col_map}")

    def _col(self, key: str) -> Optional[str]:
        return self._col_map.get(key)

    def _series(self, key: str) -> Optional[pd.Series]:
        col = self._col(key)
        return self.df[col] if col and col in self.df.columns else None

    # ── Analysis Methods ──────────────────────────────────────────

    def basic_stats(self) -> dict:
        """Core dataset statistics."""
        s = {
            "metadata_file": str(self._metadata_path),
            "total_images": len(self.df),
            "total_columns": len(self.df.columns),
            "all_columns": list(self.df.columns),
            "mapped_columns": self._col_map,
        }
        for key in COLUMN_ALIASES:
            col = self._col(key)
            if col and col in self.df.columns:
                s[f"{key}_unique_values"] = int(self.df[col].nunique())
                s[f"{key}_missing"]       = int(self.df[col].isna().sum())
        return s

    def jurisdiction_analysis(self) -> dict:
        """
        Distribution across all 81 FHIBE jurisdictions.
        Identifies regional balance and underrepresented areas.
        """
        s = self._series("jurisdiction")
        if s is None:
            return {"error": "jurisdiction column not found"}

        vc = s.value_counts()
        total = len(self.df)
        ideal_per_j = total / max(vc.nunique(), 1)

        # Regional aggregation
        region_counts: dict[str, int] = defaultdict(int)
        unrecognised = []
        for j, count in vc.items():
            region = JURISDICTION_REGION.get(str(j).upper(), "Other")
            region_counts[region] += count
            if region == "Other":
                unrecognised.append(str(j))

        # Under/over represented
        under = [
            {
                "jurisdiction": str(j),
                "count": int(c),
                "pct_of_ideal": round(c / ideal_per_j * 100, 1),
            }
            for j, c in vc.items()
            if c < ideal_per_j * 0.5
        ]
        over = [
            {
                "jurisdiction": str(j),
                "count": int(c),
                "pct_of_ideal": round(c / ideal_per_j * 100, 1),
            }
            for j, c in vc.items()
            if c > ideal_per_j * 2.0
        ]

        return {
            "total_jurisdictions": int(vc.nunique()),
            "expected_jurisdictions": 81,
            "coverage_pct": round(vc.nunique() / 81 * 100, 1),
            "ideal_per_jurisdiction": round(ideal_per_j, 1),
            "distribution": vc.to_dict(),
            "regional_totals": dict(region_counts),
            "underrepresented_jurisdictions": sorted(under, key=lambda x: x["count"]),
            "overrepresented_jurisdictions": sorted(over, key=lambda x: -x["count"]),
            "unrecognised_codes": unrecognised,
        }

    def age_analysis(self) -> dict:
        """Age group distribution and balance assessment."""
        s = self._series("age_group")
        if s is None:
            return {"error": "age_group column not found"}

        vc = s.value_counts().sort_index()
        total = len(self.df)
        return {
            "age_groups": {
                str(k): {
                    "count": int(v),
                    "pct": round(v / total * 100, 1),
                }
                for k, v in vc.items()
            },
            "most_represented": str(vc.idxmax()),
            "least_represented": str(vc.idxmin()),
            "balance_ratio": round(float(vc.min() / vc.max()), 3),  # 1.0 = perfect balance
        }

    def gender_analysis(self) -> dict:
        """Gender presentation distribution."""
        s = self._series("gender_presentation")
        if s is None:
            return {"error": "gender_presentation column not found"}

        vc = s.value_counts()
        total = len(self.df)
        return {
            "gender_presentations": {
                str(k): {"count": int(v), "pct": round(v / total * 100, 1)}
                for k, v in vc.items()
            },
            "unique_categories": int(vc.nunique()),
            "balance_ratio": round(float(vc.min() / vc.max()), 3),
        }

    def skin_tone_analysis(self) -> dict:
        """Monk Scale skin tone distribution (1-10)."""
        s = self._series("skin_tone")
        if s is None:
            return {"error": "skin_tone column not found"}

        vc = s.value_counts().sort_index()
        total = len(self.df)
        return {
            "monk_scale_distribution": {
                MONK_SCALE_LABELS.get(str(k), f"Monk {k}"): {
                    "scale_value": str(k),
                    "count": int(v),
                    "pct": round(v / total * 100, 1),
                }
                for k, v in vc.items()
            },
            "lightest_represented": str(vc.idxmin()),
            "darkest_represented": str(vc.idxmax()),
            "full_scale_covered": vc.nunique() == 10,
            "balance_ratio": round(float(vc.min() / vc.max()), 3),
        }

    def environment_analysis(self) -> dict:
        """Camera environment distribution."""
        s = self._series("environment")
        if s is None:
            return {"error": "environment column not found"}

        vc = s.value_counts()
        total = len(self.df)
        return {
            "environments": {
                str(k): {"count": int(v), "pct": round(v / total * 100, 1)}
                for k, v in vc.items()
            },
            "unique_environments": int(vc.nunique()),
        }

    def intersectional_analysis(
        self, dims: Optional[list[str]] = None
    ) -> dict:
        """
        Cross-tabulation across demographic dimensions.
        Identifies intersectional gaps (e.g., elderly women in Africa).

        This is critical for fairness evaluation: a model may perform well
        on each dimension individually but fail for specific intersections.
        """
        dims = dims or ["jurisdiction", "age_group", "gender_presentation"]
        cols = [self._col(d) for d in dims if self._col(d)]

        if len(cols) < 2:
            return {"error": "Fewer than 2 mappable dimensions found"}

        cross = self.df.groupby(cols, observed=True).size().reset_index(name="count")
        cross = cross.sort_values("count")

        total_possible = 1
        unique_counts = []
        for col in cols:
            n = self.df[col].nunique()
            total_possible *= n
            unique_counts.append(n)

        total_observed = len(cross)
        gap_pct = round((1 - total_observed / total_possible) * 100, 1)

        # Smallest groups (highest risk of bias)
        smallest = cross.head(20).to_dict(orient="records")
        largest  = cross.tail(10).to_dict(orient="records")

        return {
            "dimensions": dims,
            "total_possible_combinations": total_possible,
            "observed_combinations": total_observed,
            "missing_combinations_pct": gap_pct,
            "smallest_groups_top20": smallest,
            "largest_groups_top10":  largest,
            "unique_per_dimension": dict(zip(dims, unique_counts)),
        }

    def image_file_audit(self, sample_n: int = 200, seed: int = 42) -> dict:
        """
        Verify that image files referenced in metadata actually exist
        on disk in the fhibe_downsampled/ directory.
        """
        if not self.images_dir.exists():
            return {"error": f"Images directory not found: {self.images_dir}"}

        fn_col = self._col("filename")
        if fn_col is None:
            return {"error": "filename column not found in metadata"}

        sample = self.df[fn_col].dropna().sample(
            n=min(sample_n, len(self.df)), random_state=seed
        )
        found = 0
        missing_examples: list[str] = []
        for fn in sample:
            p = self.images_dir / str(fn)
            if p.exists():
                found += 1
            elif len(missing_examples) < 5:
                missing_examples.append(str(fn))

        return {
            "images_dir": str(self.images_dir),
            "images_dir_exists": True,
            "sample_size": len(sample),
            "files_found": found,
            "files_missing": len(sample) - found,
            "availability_pct": round(found / len(sample) * 100, 1),
            "missing_examples": missing_examples,
            "total_image_files_on_disk": len(list(self.images_dir.glob("*.jpg")))
                                          + len(list(self.images_dir.glob("*.png"))),
        }

    def sampling_strategy(
        self,
        budget_images: int = 200,
    ) -> dict:
        """
        Recommend an optimal stratified sampling strategy for bias evaluation
        given a target image budget.

        Args:
            budget_images: Maximum images to evaluate (cost control).

        Returns:
            Recommended n_per_group and expected demographic coverage.
        """
        j_col = self._col("jurisdiction")
        a_col = self._col("age_group")
        g_col = self._col("gender_presentation")

        if not all([j_col, a_col, g_col]):
            return {"error": "Core demographic columns not found"}

        n_j = int(self.df[j_col].nunique())
        n_a = int(self.df[a_col].nunique())
        n_g = int(self.df[g_col].nunique())

        # Estimate n_per_group from budget
        n_groups = n_j * n_a * n_g
        n_per_group_ideal = max(1, budget_images // n_groups)

        # Estimated images after stratified sampling
        est_images = min(budget_images, n_groups * n_per_group_ideal)

        # Cost estimates (Haiku model)
        tokens_per_image_per_probe = 700
        probes_per_image = 7  # 5 categories × avg 1.4 probes
        total_tokens = est_images * probes_per_image * tokens_per_image_per_probe

        return {
            "budget_images": budget_images,
            "demographic_groups": {
                "jurisdictions": n_j,
                "age_groups": n_a,
                "gender_presentations": n_g,
                "total_combinations": n_groups,
            },
            "recommended_n_per_group": n_per_group_ideal,
            "estimated_images": est_images,
            "cli_command": (
                f"python bias_engine.py "
                f"--fhibe-root <FHIBE_ROOT> "
                f"--n-per-group {n_per_group_ideal} "
                f"--max-images {budget_images} "
                f"--use-batch"
            ),
            "cost_estimates_usd": {
                "haiku_realtime": round(total_tokens * 0.80 / 1_000_000, 3),
                "haiku_batch_50pct_off": round(total_tokens * 0.40 / 1_000_000, 3),
                "sonnet_realtime": round(total_tokens * 3.00 / 1_000_000, 3),
            },
            "note": (
                "Use --use-batch for 50% cost reduction. "
                "Budget $5 free credits → ~200 images with Haiku batch."
            ),
        }

    # ── Full Report ───────────────────────────────────────────────

    def full_report(self, budget_images: int = 200) -> dict:
        """Generate the complete FHIBE metadata analysis report."""
        return {
            "basic_stats":          self.basic_stats(),
            "jurisdiction":         self.jurisdiction_analysis(),
            "age_groups":           self.age_analysis(),
            "gender_presentation":  self.gender_analysis(),
            "skin_tone":            self.skin_tone_analysis(),
            "environment":          self.environment_analysis(),
            "intersectional":       self.intersectional_analysis(),
            "image_file_audit":     self.image_file_audit(),
            "sampling_strategy":    self.sampling_strategy(budget_images),
        }

    def to_markdown(self, report: dict) -> str:
        """Convert the full report dict to a readable Markdown document."""
        bs = report.get("basic_stats", {})
        j  = report.get("jurisdiction", {})
        ag = report.get("age_groups", {})
        gn = report.get("gender_presentation", {})
        sk = report.get("skin_tone", {})
        ss = report.get("sampling_strategy", {})
        it = report.get("intersectional", {})

        jurisdiction_rows = ""
        for code, count in list(j.get("distribution", {}).items())[:15]:
            region = JURISDICTION_REGION.get(str(code).upper(), "Other")
            jurisdiction_rows += f"| `{code}` | {region} | {count} |\n"

        age_rows = ""
        for group, stats in ag.get("age_groups", {}).items():
            age_rows += f"| {group} | {stats['count']} | {stats['pct']}% |\n"

        gender_rows = ""
        for g, stats in gn.get("gender_presentations", {}).items():
            gender_rows += f"| {g} | {stats['count']} | {stats['pct']}% |\n"

        skin_rows = ""
        for label, stats in list(sk.get("monk_scale_distribution", {}).items()):
            skin_rows += f"| {label} | {stats['count']} | {stats['pct']}% |\n"

        under = j.get("underrepresented_jurisdictions", [])
        under_list = "\n".join(
            f"  - `{u['jurisdiction']}`: {u['count']} images "
            f"({u['pct_of_ideal']}% of ideal)"
            for u in under[:10]
        ) or "  None"

        return f"""# FHIBE Dataset Analysis Report

**Dataset:** Sony Fair Human-Centric Images Benchmark (FHIBE)
**Source:** {bs.get('metadata_file', 'N/A')}
**Total Images:** {bs.get('total_images', 'N/A'):,}

---

## 1. Dataset Overview

| Attribute | Value |
|---|---|
| Total Images | `{bs.get('total_images', 'N/A'):,}` |
| Total Columns | `{bs.get('total_columns', 'N/A')}` |
| Jurisdictions | `{j.get('total_jurisdictions', 'N/A')}` / 81 |
| Coverage | `{j.get('coverage_pct', 'N/A')}%` of all FHIBE jurisdictions |

---

## 2. Jurisdiction Distribution (Top 15)

| Jurisdiction | Region | Count |
|---|---|---|
{jurisdiction_rows}

**Regional totals:**
{chr(10).join(f'  - {r}: {c}' for r, c in j.get('regional_totals', {}).items())}

### Underrepresented Jurisdictions (< 50% of ideal)
{under_list}

---

## 3. Age Group Distribution

| Age Group | Count | % |
|---|:---:|:---:|
{age_rows}

Balance ratio (min/max): `{ag.get('balance_ratio', 'N/A')}`
_(1.0 = perfectly balanced, lower = more skewed)_

---

## 4. Gender Presentation Distribution

| Gender Presentation | Count | % |
|---|:---:|:---:|
{gender_rows}

Balance ratio: `{gn.get('balance_ratio', 'N/A')}`

---

## 5. Skin Tone Distribution (Monk Scale 1–10)

| Monk Scale Label | Count | % |
|---|:---:|:---:|
{skin_rows}

Full scale covered: `{sk.get('full_scale_covered', 'N/A')}`
Balance ratio: `{sk.get('balance_ratio', 'N/A')}`

---

## 6. Intersectional Coverage

| Metric | Value |
|---|---|
| Dimensions analysed | `{it.get('dimensions', [])}` |
| Possible combinations | `{it.get('total_possible_combinations', 'N/A'):,}` |
| Observed combinations | `{it.get('observed_combinations', 'N/A'):,}` |
| Missing combinations | `{it.get('missing_combinations_pct', 'N/A')}%` |

> **Note:** Missing intersectional combinations indicate areas where bias evaluation
> may have insufficient data. Focus evaluation resources on the smallest groups.

---

## 7. Recommended Sampling Strategy

**Budget:** {ss.get('budget_images', 'N/A')} images

| Setting | Value |
|---|---|
| Recommended `n_per_group` | `{ss.get('recommended_n_per_group', 'N/A')}` |
| Estimated images selected | `{ss.get('estimated_images', 'N/A')}` |

### Cost Estimates

| Mode | Est. Cost |
|---|---|
| Haiku + Realtime | `${ss.get('cost_estimates_usd', {}).get('haiku_realtime', 'N/A')}` |
| **Haiku + Batch API (recommended)** | **`${ss.get('cost_estimates_usd', {}).get('haiku_batch_50pct_off', 'N/A')}`** |
| Sonnet + Realtime | `${ss.get('cost_estimates_usd', {}).get('sonnet_realtime', 'N/A')}` |

### CLI Command
```bash
{ss.get('cli_command', '')}
```

---

*Generated by EthicGuard — Autonomous VLM Bias Auditor*
*Dataset: [Sony FHIBE](https://fairnessbenchmark.ai.sony/)*
"""


# ─────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="EthicGuard — FHIBE Dataset Metadata Analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python fhibe_analysis.py --fhibe-root /data/fhibe.v1_downsampled_public
  python fhibe_analysis.py --fhibe-root /data/fhibe.v1_downsampled_public \\
      --output-dir ./reports --budget 500
        """,
    )
    parser.add_argument(
        "--fhibe-root", required=True,
        help="Path to extracted FHIBE tarball directory",
    )
    parser.add_argument(
        "--output-dir", default="ethicguard-reports",
        help="Output directory for reports (default: ethicguard-reports)",
    )
    parser.add_argument(
        "--budget", type=int, default=200,
        help="Image budget for sampling strategy recommendation (default: 200)",
    )
    parser.add_argument(
        "--json-only", action="store_true",
        help="Output JSON only (skip Markdown)",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Run analysis
    analyzer = FHIBEAnalyzer(args.fhibe_root).load()
    report = analyzer.full_report(budget_images=args.budget)

    # Save JSON
    json_path = output_dir / "fhibe_analysis.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    logger.info(f"Analysis JSON saved: {json_path}")

    # Save Markdown
    if not args.json_only:
        md_path = output_dir / "fhibe_analysis.md"
        md_path.write_text(analyzer.to_markdown(report), encoding="utf-8")
        logger.info(f"Analysis Markdown saved: {md_path}")

    # Print key findings to stdout
    j = report["jurisdiction"]
    ag = report["age_groups"]
    ss = report["sampling_strategy"]
    under = j.get("underrepresented_jurisdictions", [])

    print("\n" + "=" * 60)
    print("  FHIBE Dataset Analysis — Key Findings")
    print("=" * 60)
    print(f"  Total images       : {report['basic_stats']['total_images']:,}")
    print(f"  Jurisdictions      : {j['total_jurisdictions']} / 81")
    print(f"  Coverage           : {j['coverage_pct']}%")
    print(f"  Age balance ratio  : {ag.get('balance_ratio', 'N/A')}")
    if under:
        print(f"  Underrepresented   : {len(under)} jurisdictions")
    print(f"\n  Recommended command:")
    print(f"  {ss.get('cli_command', '')}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
