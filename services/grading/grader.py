"""
CardGrader: orchestrator that merges the Geometric Agent (deterministic CV) and the Inspector
Agent (local VLM) into a single 1-10 grade with PSA/BGS-style subgrades (Centering, Edges,
Corners, Surface).
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Union

import cv2
from PIL import Image

import config
from models import GradingResult
from services.grading.ai_agent import InspectorAgent
from services.grading.geometric_agent import (
    build_annotated_image,
    calculate_centering,
    calculate_corner_whitening,
    calculate_edge_wear,
    normalize_card_image,
)


@dataclass
class DebugImages:
    """Images for the Grading tab's transparency panel. Not a Pydantic model — PIL Images
    aren't JSON-serializable and don't need to be, they're never persisted to collection.db."""
    original: Image.Image
    annotated: Image.Image


def _lookup_subgrade(value: float, thresholds: List[Tuple[float, float]], min_subgrade: float) -> float:
    """Return the subgrade for the first threshold `value` is <= to; thresholds must be ascending."""
    for max_value, subgrade in thresholds:
        if value <= max_value:
            return subgrade
    return min_subgrade


def _bgr_to_pil(img) -> Image.Image:
    return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))


def _build_explanation(
    centering_subgrade: float,
    edges_subgrade: float,
    corners_subgrade: float,
    surface_subgrade: float,
    edge_wear_pct: float,
    corner_whitening_pct: float,
    centering: Dict,
    surface_details: Dict,
) -> str:
    """Compose a deterministic, human-readable explanation of why the final grade came out as it
    did — grounded in the actual numbers/formula, not just re-stating the VLM's own prose."""
    subgrades = {
        "Centering": centering_subgrade,
        "Edges": edges_subgrade,
        "Corners": corners_subgrade,
        "Surface": surface_subgrade,
    }
    bottleneck_name = min(subgrades, key=subgrades.get)
    bottleneck_value = subgrades[bottleneck_name]
    cap = round(bottleneck_value + 1.0, 1)

    if bottleneck_name == "Centering":
        reason = (
            f"the detected centering (H {centering.get('horizontal', 50):.0f}/"
            f"{100 - centering.get('horizontal', 50):.0f}, V {centering.get('vertical', 50):.0f}/"
            f"{100 - centering.get('vertical', 50):.0f}) is far from the ideal 50/50"
            if centering.get("detected")
            else "centering could not be reliably detected, so a conservative value was used"
        )
    elif bottleneck_name == "Edges":
        reason = f"{edge_wear_pct:.1f}% of the border shows signs of whitening/wear"
    elif bottleneck_name == "Corners":
        reason = f"{corner_whitening_pct:.1f}% of the 4 corners' area shows signs of whitening"
    else:
        scratch = surface_details.get("scratch_severity", "none")
        crease = surface_details.get("crease_severity", "none")
        reason = f"the AI detected '{scratch}' scratches and '{crease}' creases on the surface"

    return (
        f"The lowest subgrade is {bottleneck_name} ({bottleneck_value:.1f}/10), because {reason}. "
        f"Per BGS-style rules, the final grade cannot exceed the worst subgrade + 1.0 "
        f"({cap:.1f}/10), even if the weighted average of the four subgrades would be higher."
    )


class CardGrader:
    """Runs both agents on a card photo and computes the final weighted/capped grade."""

    def __init__(self):
        self.inspector = InspectorAgent()

    async def grade_card(
        self, image_path: Path, corners: List[Union[Tuple[float, float], List[float]]]
    ) -> Tuple[GradingResult, DebugImages]:
        """`corners` are the 4 card corners in original-photo pixel coordinates, picked manually
        by the user in the web UI (see .CLAUDE/07-grading.md — the outline is no longer
        auto-detected)."""
        # 0. Keep the original photo for the transparency panel (separate read from the one
        # inside normalize_card_image — a second decode of one image is cheap and avoids
        # touching that function's signature).
        original = cv2.imread(str(image_path))

        # 1. Geometric Agent — deterministic, synchronous, no AI involved.
        normalized = normalize_card_image(image_path, corners)
        edge_wear_pct, damaged_mask = calculate_edge_wear(normalized)
        corner_whitening_pct, corner_damaged_mask = calculate_corner_whitening(normalized)
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

        corners_subgrade = _lookup_subgrade(
            corner_whitening_pct, config.CORNER_WHITENESS_PCT_TO_SUBGRADE, config.CORNER_MIN_SUBGRADE
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
            + corners_subgrade * weights["corners"]
            + surface_subgrade * weights["surface"]
        )
        worst_subgrade = min(centering_subgrade, edges_subgrade, corners_subgrade, surface_subgrade)
        final_grade = min(weighted_avg, worst_subgrade + 1.0)
        final_grade = round(final_grade * 2) / 2.0  # nearest 0.5
        final_grade = max(1.0, min(10.0, final_grade))

        # 5. Map to the existing NM/EX/GD/LP/PO market condition scale
        condition = config.GRADE_TO_CONDITION_FALLBACK
        for min_grade, bucket in config.GRADE_TO_CONDITION:
            if final_grade >= min_grade:
                condition = bucket
                break

        explanation = _build_explanation(
            centering_subgrade,
            edges_subgrade,
            corners_subgrade,
            surface_subgrade,
            edge_wear_pct,
            corner_whitening_pct,
            centering,
            surface_details,
        )

        result = GradingResult(
            centering_ratio={"horizontal": centering["horizontal"], "vertical": centering["vertical"]},
            edge_wear_pct=edge_wear_pct,
            corner_whitening_pct=corner_whitening_pct,
            surface_details=surface_details,
            centering_subgrade=centering_subgrade,
            edges_subgrade=edges_subgrade,
            corners_subgrade=corners_subgrade,
            surface_subgrade=surface_subgrade,
            final_grade=final_grade,
            condition=condition,
            explanation=explanation,
        )

        annotated = build_annotated_image(normalized, damaged_mask, centering, corner_damaged_mask)
        debug_images = DebugImages(original=_bgr_to_pil(original), annotated=_bgr_to_pil(annotated))

        return result, debug_images

    async def close(self) -> None:
        await self.inspector.close()
