"""
Geometric Agent: deterministic Computer Vision processing for card grading.

Zero AI dependencies. Handles normalization (perspective flatten of a user-picked crop), edge
wear measurement, corner whitening measurement, and centering measurement — the mathematically
verifiable defects, as opposed to the surface defects (scratches/creases) judged by the VLM
Inspector Agent (ai_agent.py).
"""
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

import config


class CardCropError(Exception):
    """Raised when the image can't be read or the supplied crop corners are invalid."""


def _order_points(pts: np.ndarray) -> np.ndarray:
    """Order 4 points as top-left, top-right, bottom-right, bottom-left."""
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def normalize_card_image(image_path: Path, corners: List[Tuple[float, float]]) -> np.ndarray:
    """
    Load a raw photo of a physical card and perspective-warp the given quadrilateral — the 4
    corners of the card, picked manually by the user in the web UI — into a flat canonical
    rectangle (config.NORMALIZED_CARD_WIDTH x config.NORMALIZED_CARD_HEIGHT).

    The card outline used to be auto-detected (Canny edges, then HSV saturation segmentation,
    with shape validation and a border-recovery expansion added across several rounds in the
    same session) — every version still cropped imprecisely on some real photos, most notably
    excluding the card's black border (and therefore the corners) because that border is nearly
    as desaturated as a typical background. Manual corner selection sidesteps all of that: the
    user sees the actual photo and places the corners exactly on the physical card edge. See
    "Cronologia: indagine precisione CV" in .CLAUDE/07-grading.md for the abandoned attempts.
    """
    image = cv2.imread(str(image_path))
    if image is None:
        raise CardCropError(f"Could not read image file: {image_path}")

    if len(corners) != 4:
        raise CardCropError(f"Expected 4 corner points, got {len(corners)}.")

    src_pts = _order_points(np.array(corners, dtype="float32"))

    dst_w, dst_h = config.NORMALIZED_CARD_WIDTH, config.NORMALIZED_CARD_HEIGHT
    dst_pts = np.array(
        [[0, 0], [dst_w - 1, 0], [dst_w - 1, dst_h - 1], [0, dst_h - 1]],
        dtype="float32",
    )
    matrix = cv2.getPerspectiveTransform(src_pts, dst_pts)
    return cv2.warpPerspective(image, matrix, (dst_w, dst_h))


def calculate_edge_wear(normalized_img: np.ndarray) -> tuple:
    """
    Extract a thin outer perimeter and return the % of pixels flagged as whitened — the classic
    sign of edge wear, where a chipped black border exposes the white cardstock underneath.

    Uses an absolute grayscale brightness threshold (config.CARD_GRAYSCALE_WHITENESS_THRESHOLD)
    rather than a color-distance-to-a-reference-ring measurement: a card's border is dark
    regardless of lighting or which card it is, and true whitening is unambiguously light, so no
    reference ring is needed at all. This also sidesteps a real calibration problem the older
    reference-ring version had — see "Cronologia: indagine precisione CV" in .CLAUDE/07-grading.md.

    The outermost `config.EDGE_WEAR_SKIN_PX` pixels are excluded: normalize_card_image()'s
    perspective warp leaves a couple of blended/anti-aliased pixels right at the crop boundary
    that would otherwise be misread as whitening.

    Returns (whitened_pct, damaged_mask), where damaged_mask is a boolean (h, w) array marking
    exactly which pixels in the outer perimeter were flagged as worn — used by
    build_annotated_image() to visualize what the geometric agent actually detected.
    """
    h, w = normalized_img.shape[:2]
    border = config.EDGE_WEAR_BORDER_PX
    skin = config.EDGE_WEAR_SKIN_PX
    threshold = config.CARD_GRAYSCALE_WHITENESS_THRESHOLD

    gray = cv2.cvtColor(normalized_img, cv2.COLOR_BGR2GRAY)

    outer_mask = np.zeros((h, w), dtype=bool)
    outer_mask[skin:skin + border, :] = True
    outer_mask[h - border - skin:h - skin, :] = True
    outer_mask[:, skin:skin + border] = True
    outer_mask[:, w - border - skin:w - skin] = True

    damaged_mask = outer_mask & (gray > threshold)

    damaged_ratio = float(np.count_nonzero(damaged_mask)) / float(np.count_nonzero(outer_mask))
    return round(damaged_ratio * 100.0, 2), damaged_mask


def calculate_corner_whitening(normalized_img: np.ndarray) -> tuple:
    """
    Detect whitening in a square ROI (config.CORNER_ROI_PX) around each of the 4 physical
    corners — where chipping/whitening from handling is most visible, and graded separately from
    edges in real PSA/BGS grading. Reuses the same absolute-brightness logic as
    calculate_edge_wear (see its docstring for why an absolute threshold, not a color-distance
    one), inset by the same `config.EDGE_WEAR_SKIN_PX` to skip the perspective warp's boundary
    blend artifact.

    Note: this only measures corner *whitening* (a color/material defect that survives the
    perspective warp), not corner *rounding* (a geometric defect that the warp itself erases by
    construction — it forces whatever was near the detected corner point onto a perfect right
    angle). See .CLAUDE/07-grading.md.

    Returns (whitened_pct, damaged_mask) — damaged_mask covers just the 4 corner ROIs.
    """
    h, w = normalized_img.shape[:2]
    roi = config.CORNER_ROI_PX
    skin = config.EDGE_WEAR_SKIN_PX
    threshold = config.CARD_GRAYSCALE_WHITENESS_THRESHOLD

    gray = cv2.cvtColor(normalized_img, cv2.COLOR_BGR2GRAY)

    corner_mask = np.zeros((h, w), dtype=bool)
    corner_mask[skin:skin + roi, skin:skin + roi] = True
    corner_mask[skin:skin + roi, w - roi - skin:w - skin] = True
    corner_mask[h - roi - skin:h - skin, skin:skin + roi] = True
    corner_mask[h - roi - skin:h - skin, w - roi - skin:w - skin] = True

    damaged_mask = corner_mask & (gray > threshold)

    damaged_ratio = float(np.count_nonzero(damaged_mask)) / float(np.count_nonzero(corner_mask))
    return round(damaged_ratio * 100.0, 2), damaged_mask


def calculate_centering(normalized_img: np.ndarray) -> dict:
    """
    Detect the printed frame inside the normalized card and measure how centered it is relative
    to the physical card edges. Returns a dict with "horizontal"/"vertical" ratios (50.0 = perfect)
    and "detected" (False if no confident frame contour was found, in which case the ratios
    default to 50/50 and the caller should treat the measurement as unreliable).
    """
    h, w = normalized_img.shape[:2]
    card_area = h * w
    min_ratio, max_ratio = config.CENTERING_FRAME_AREA_RATIO_RANGE

    gray = cv2.cvtColor(normalized_img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 30, 100)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    best = None
    best_area = 0.0
    for c in contours:
        area = cv2.contourArea(c)
        ratio = area / card_area
        if not (min_ratio <= ratio <= max_ratio) or area <= best_area:
            continue

        x, y, cw, ch = cv2.boundingRect(c)
        # A real inner print frame has margin on all sides; a box touching the image edge is
        # almost certainly the outer card border being picked up again, not the inner frame.
        if x <= 1 or y <= 1 or (x + cw) >= w - 1 or (y + ch) >= h - 1:
            continue

        # Require a convex quadrilateral (the print frame is a rectangle, not an arbitrary blob).
        approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue

        best = (x, y, cw, ch)
        best_area = area

    if best is None:
        return {"horizontal": 50.0, "vertical": 50.0, "detected": False, "bbox": None}

    x, y, cw, ch = best
    left, right = x, w - (x + cw)
    top, bottom = y, h - (y + ch)

    horizontal = 50.0 if (left + right) == 0 else round(left / (left + right) * 100.0, 2)
    vertical = 50.0 if (top + bottom) == 0 else round(top / (top + bottom) * 100.0, 2)
    return {"horizontal": horizontal, "vertical": vertical, "detected": True, "bbox": best}


def build_annotated_image(
    normalized_img: np.ndarray,
    damaged_mask: np.ndarray,
    centering: dict,
    corner_damaged_mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    Draw a visual debug overlay on top of the normalized card image, showing exactly what the
    geometric agent measured: the perimeter band checked for edge wear (yellow), the 4 corner
    ROIs checked for whitening (orange), the pixels actually flagged as worn within either (red),
    and the detected centering frame (cyan).
    """
    annotated = normalized_img.copy()
    h, w = annotated.shape[:2]
    border = config.EDGE_WEAR_BORDER_PX
    skin = config.EDGE_WEAR_SKIN_PX
    roi = config.CORNER_ROI_PX

    # Yellow outline of the perimeter band inspected for edge wear.
    cv2.rectangle(annotated, (skin, skin), (w - skin, h - skin), (0, 255, 255), 1)
    cv2.rectangle(
        annotated, (skin + border, skin + border), (w - skin - border, h - skin - border), (0, 255, 255), 1
    )

    # Orange outline of the 4 corner ROIs inspected for whitening.
    for cx, cy in [(skin, skin), (w - roi - skin, skin), (skin, h - roi - skin), (w - roi - skin, h - roi - skin)]:
        cv2.rectangle(annotated, (cx, cy), (cx + roi, cy + roi), (0, 140, 255), 1)

    # Red highlight on pixels actually flagged as damaged (edge wear and/or corner whitening).
    annotated[damaged_mask] = (0, 0, 255)
    if corner_damaged_mask is not None:
        annotated[corner_damaged_mask] = (0, 0, 255)

    # Cyan rectangle on the detected centering frame, if any.
    bbox = centering.get("bbox")
    if centering.get("detected") and bbox:
        x, y, cw, ch = bbox
        cv2.rectangle(annotated, (x, y), (x + cw, y + ch), (255, 255, 0), 2)

    return annotated
