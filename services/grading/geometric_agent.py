"""
Geometric Agent: deterministic Computer Vision processing for card grading.

Zero AI dependencies. Handles ingestion/normalization (crop + perspective flatten), edge wear
measurement, and centering measurement — the mathematically verifiable defects, as opposed to
the surface defects (scratches/creases) judged by the VLM Inspector Agent (ai_agent.py).
"""
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

import config


class CardDetectionError(Exception):
    """Raised when the card outline cannot be located in the source image at all."""


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


def _quad_is_plausible(rect: np.ndarray) -> bool:
    """
    Reject a 4-point polygon approximation that is a poor stand-in for a physical card: aspect
    ratio far from 63x88mm, or corners far from 90 degrees (perspective/skew noise from glare or
    a slightly imprecise Canny edge). When this returns False, the caller should fall back to the
    more robust `minAreaRect` crop instead of trusting a shaky 4-point homography.
    """
    tl, tr, br, bl = rect
    width = (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2.0
    height = (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2.0
    if height == 0:
        return False

    expected_ratio = config.NORMALIZED_CARD_WIDTH / config.NORMALIZED_CARD_HEIGHT
    if abs((width / height) - expected_ratio) / expected_ratio > 0.15:
        return False

    corners = [tl, tr, br, bl]
    for i in range(4):
        p0, p1, p2 = corners[i - 1], corners[i], corners[(i + 1) % 4]
        v1, v2 = p0 - p1, p2 - p1
        cos_angle = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-6)
        angle = np.degrees(np.arccos(np.clip(cos_angle, -1.0, 1.0)))
        if abs(angle - 90.0) > 25.0:
            return False
    return True


def _largest_contour(gray: np.ndarray) -> Optional[np.ndarray]:
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    return max(contours, key=cv2.contourArea)


def _foreground_contour(image: np.ndarray) -> Optional[np.ndarray]:
    """
    Segment the card from the background by HSV saturation instead of gradient/edge detection.
    A busy background texture (e.g. wood grain) generates lots of small Canny edges that
    fragment the card's true outline and can make `_largest_contour` lock onto an internal
    contour (like the printed art frame) instead of the physical card edge — and even a plain
    color-distance mask gets fooled by the brightness variation of the grain itself. A printed
    card is consistently far more saturated than a wood/plastic/fabric surface, which holds even
    when that surface has natural texture and shading, so thresholding on saturation alone
    segments the card cleanly where both alternatives fail.
    """
    saturation = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)[:, :, 1]
    mask = (saturation > config.CARD_SATURATION_THRESHOLD).astype("uint8") * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    return max(contours, key=cv2.contourArea)


def normalize_card_image(image_path: Path) -> np.ndarray:
    """
    Load a raw photo of a physical card, detect its outline, and perspective-warp it into a
    flat canonical rectangle (config.NORMALIZED_CARD_WIDTH x config.NORMALIZED_CARD_HEIGHT).
    """
    image = cv2.imread(str(image_path))
    if image is None:
        raise CardDetectionError(f"Could not read image file: {image_path}")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    image_area = image.shape[0] * image.shape[1]

    def _plausible_card_area(c) -> bool:
        return c is not None and 0.1 <= (cv2.contourArea(c) / image_area) <= 0.95

    # Prefer color-based segmentation (robust to busy backgrounds like wood grain, which
    # fragments Canny edges and can make the gradient-based detector lock onto an internal
    # contour instead of the true card outline); fall back to the gradient-based one otherwise.
    foreground_contour = _foreground_contour(image)
    edge_contour = _largest_contour(gray)

    if _plausible_card_area(foreground_contour):
        contour = foreground_contour
    elif _plausible_card_area(edge_contour):
        contour = edge_contour
    else:
        contour = foreground_contour or edge_contour

    if contour is None:
        raise CardDetectionError("No card outline detected in the image.")

    peri = cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, 0.02 * peri, True)

    src_pts = None
    if len(approx) == 4:
        candidate = _order_points(approx.reshape(4, 2).astype("float32"))
        if _quad_is_plausible(candidate):
            src_pts = candidate

    if src_pts is None:
        # Fallback: the 4-point approximation is missing or implausible (skewed corners, wrong
        # aspect ratio) — use the rotated bounding box of the largest contour instead, a simple
        # crop+rotate that is far less sensitive to noisy corner points than a full homography.
        rect = cv2.minAreaRect(contour)
        box = cv2.boxPoints(rect)
        src_pts = _order_points(box.astype("float32"))

    dst_w, dst_h = config.NORMALIZED_CARD_WIDTH, config.NORMALIZED_CARD_HEIGHT
    dst_pts = np.array(
        [[0, 0], [dst_w - 1, 0], [dst_w - 1, dst_h - 1], [0, dst_h - 1]],
        dtype="float32",
    )
    matrix = cv2.getPerspectiveTransform(src_pts, dst_pts)
    return cv2.warpPerspective(image, matrix, (dst_w, dst_h))


def calculate_edge_wear(normalized_img: np.ndarray) -> tuple:
    """
    Extract a thin outer perimeter and return the % of pixels that deviate from the expected
    (undamaged) border color, sampled from a slightly deeper reference ring.

    The reference color is computed **per side** (top/bottom/left/right independently) rather
    than as a single card-wide median: a directional light source produces a natural brightness
    gradient across the card that a single reference color would misread as wear on the darker/
    brighter sides. Corners belong to the top/bottom strips (which span the full width) so each
    pixel is only ever compared against one side's reference.

    Returns (damaged_pct, damaged_mask), where damaged_mask is a boolean (h, w) array marking
    exactly which pixels in the outer perimeter were flagged as worn — used by
    build_annotated_image() to visualize what the geometric agent actually detected.
    """
    h, w = normalized_img.shape[:2]
    border = config.EDGE_WEAR_BORDER_PX
    ref_offset = config.EDGE_WEAR_REFERENCE_OFFSET_PX
    threshold = config.EDGE_WEAR_COLOR_DISTANCE_THRESHOLD
    img = normalized_img.astype("float32")

    sides = {
        "top": (
            (slice(0, border), slice(None)),
            (slice(ref_offset, ref_offset + border), slice(None)),
        ),
        "bottom": (
            (slice(h - border, h), slice(None)),
            (slice(h - ref_offset - border, h - ref_offset), slice(None)),
        ),
        "left": (
            (slice(border, h - border), slice(0, border)),
            (slice(border, h - border), slice(ref_offset, ref_offset + border)),
        ),
        "right": (
            (slice(border, h - border), slice(w - border, w)),
            (slice(border, h - border), slice(w - ref_offset - border, w - ref_offset)),
        ),
    }

    outer_mask = np.zeros((h, w), dtype=bool)
    damaged_mask = np.zeros((h, w), dtype=bool)
    for outer_slice, ref_slice in sides.values():
        outer_mask[outer_slice] = True
        reference_color = np.median(img[ref_slice].reshape(-1, 3), axis=0)
        distances = np.linalg.norm(img[outer_slice] - reference_color, axis=2)
        damaged_mask[outer_slice] = distances > threshold

    damaged_ratio = float(np.count_nonzero(damaged_mask)) / float(np.count_nonzero(outer_mask))
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


def build_annotated_image(normalized_img: np.ndarray, damaged_mask: np.ndarray, centering: dict) -> np.ndarray:
    """
    Draw a visual debug overlay on top of the normalized card image, showing exactly what the
    geometric agent measured: the perimeter band checked for edge wear (yellow), the pixels
    actually flagged as worn within it (red), and the detected centering frame (cyan).
    """
    annotated = normalized_img.copy()
    h, w = annotated.shape[:2]
    border = config.EDGE_WEAR_BORDER_PX

    # Yellow outline of the perimeter band inspected for wear.
    cv2.rectangle(annotated, (border, border), (w - border, h - border), (0, 255, 255), 1)

    # Red highlight on pixels actually flagged as damaged.
    annotated[damaged_mask] = (0, 0, 255)

    # Cyan rectangle on the detected centering frame, if any.
    bbox = centering.get("bbox")
    if centering.get("detected") and bbox:
        x, y, cw, ch = bbox
        cv2.rectangle(annotated, (x, y), (x + cw, y + ch), (255, 255, 0), 2)

    return annotated
