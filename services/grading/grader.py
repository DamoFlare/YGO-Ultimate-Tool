"""
CardGrader: orchestrator that merges the Geometric Agent (deterministic CV) and the Inspector
Agent (local VLM) into a single 1-10 grade with PSA/BGS-style subgrades.

Known scope limitation: real BGS grades 4 subgrades (Centering, Corners, Edges, Surface). This
grader only computes 3 (Centering, Edges, Surface) — corner-specific wear detection isn't
implemented by either agent. See .CLAUDE/07-grading.md.
"""
from pathlib import Path
from typing import List, Tuple

import config
from models import GradingResult
from services.grading.ai_agent import InspectorAgent
from services.grading.geometric_agent import (
    calculate_centering,
    calculate_edge_wear,
    normalize_card_image,
)


def _lookup_subgrade(value: float, thresholds: List[Tuple[float, float]], min_subgrade: float) -> float:
    """Return the subgrade for the first threshold `value` is <= to; thresholds must be ascending."""
    for max_value, subgrade in thresholds:
        if value <= max_value:
            return subgrade
    return min_subgrade


class CardGrader:
    """Runs both agents on a card photo and computes the final weighted/capped grade."""

    def __init__(self):
        self.inspector = InspectorAgent()

    async def grade_card(self, image_path: Path) -> GradingResult:
        # 1. Geometric Agent — deterministic, synchronous, no AI involved.
        normalized = normalize_card_image(image_path)
        edge_wear_pct = calculate_edge_wear(normalized)
        centering = calculate_centering(normalized)

        # 2. Inspector Agent — local VLM, asynchronous.
        surface_details = await self.inspector.analyze_surface(normalized)

        # 3. Subgrades
        if centering.get("detected", False):
            deviation = max(abs(centering["horizontal"] - 50.0), abs(centering["vertical"] - 50.0))
            centering_subgrade = _lookup_subgrade(
                deviation, config.CENTERING_DEVIATION_TO_SUBGRADE, config.CENTERING_MIN_SUBGRADE
            )
        else:
            centering_subgrade = config.CENTERING_FALLBACK_SUBGRADE

        edges_subgrade = _lookup_subgrade(
            edge_wear_pct, config.EDGE_WEAR_PCT_TO_SUBGRADE, config.EDGE_WEAR_MIN_SUBGRADE
        )

        scratch_subgrade = config.SEVERITY_TO_SUBGRADE.get(
            surface_details["scratch_severity"], config.UNKNOWN_SEVERITY_FALLBACK_SUBGRADE
        )
        crease_subgrade = config.SEVERITY_TO_SUBGRADE.get(
            surface_details["crease_severity"], config.UNKNOWN_SEVERITY_FALLBACK_SUBGRADE
        )
        surface_subgrade = min(scratch_subgrade, crease_subgrade)

        # 4. Final grade: weighted average, capped BGS-style at worst-subgrade + 1.0, rounded to 0.5
        weights = config.GRADE_SUBGRADE_WEIGHTS
        weighted_avg = (
            centering_subgrade * weights["centering"]
            + edges_subgrade * weights["edges"]
            + surface_subgrade * weights["surface"]
        )
        worst_subgrade = min(centering_subgrade, edges_subgrade, surface_subgrade)
        final_grade = min(weighted_avg, worst_subgrade + 1.0)
        final_grade = round(final_grade * 2) / 2.0  # nearest 0.5
        final_grade = max(1.0, min(10.0, final_grade))

        # 5. Map to the existing NM/EX/GD/LP/PO market condition scale
        condition = config.GRADE_TO_CONDITION_FALLBACK
        for min_grade, bucket in config.GRADE_TO_CONDITION:
            if final_grade >= min_grade:
                condition = bucket
                break

        return GradingResult(
            centering_ratio={"horizontal": centering["horizontal"], "vertical": centering["vertical"]},
            edge_wear_pct=edge_wear_pct,
            surface_details=surface_details,
            centering_subgrade=centering_subgrade,
            edges_subgrade=edges_subgrade,
            surface_subgrade=surface_subgrade,
            final_grade=final_grade,
            condition=condition,
        )

    async def close(self) -> None:
        await self.inspector.close()
