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


def _largest_contour(gray: np.ndarray) -> Optional[np.ndarray]:
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
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
    contour = _largest_contour(gray)
    if contour is None:
        raise CardDetectionError("No card outline detected in the image.")

    peri = cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, 0.02 * peri, True)

    if len(approx) == 4:
        src_pts = _order_points(approx.reshape(4, 2).astype("float32"))
    else:
        # Fallback: use the rotated bounding box of the largest contour instead of a perfect quad.
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

    Returns (damaged_pct, damaged_mask), where damaged_mask is a boolean (h, w) array marking
    exactly which pixels in the outer perimeter were flagged as worn — used by
    build_annotated_image() to visualize what the geometric agent actually detected.
    """
    h, w = normalized_img.shape[:2]
    border = config.EDGE_WEAR_BORDER_PX
    ref_offset = config.EDGE_WEAR_REFERENCE_OFFSET_PX

    outer_mask = np.zeros((h, w), dtype=bool)
    outer_mask[:border, :] = True
    outer_mask[-border:, :] = True
    outer_mask[:, :border] = True
    outer_mask[:, -border:] = True

    ref_mask = np.zeros((h, w), dtype=bool)
    ref_mask[ref_offset:ref_offset + border, :] = True
    ref_mask[-(ref_offset + border):-ref_offset, :] = True
    ref_mask[:, ref_offset:ref_offset + border] = True
    ref_mask[:, -(ref_offset + border):-ref_offset] = True

    reference_color = np.median(normalized_img[ref_mask].reshape(-1, 3), axis=0)

    distances = np.linalg.norm(normalized_img.astype("float32") - reference_color, axis=2)
    damaged_mask = outer_mask & (distances > config.EDGE_WEAR_COLOR_DISTANCE_THRESHOLD)

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
        if min_ratio <= ratio <= max_ratio and area > best_area:
            x, y, cw, ch = cv2.boundingRect(c)
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
