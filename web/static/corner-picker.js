// Manual 4-corner card cropper for the Grading page. No external dependencies (project-wide
// convention: vanilla JS, no build step). Lets the user drag 4 handles onto the physical card's
// corners in the uploaded photo preview, with a magnifying loupe that follows the cursor while
// dragging for sub-pixel precision. On submit, the corners are converted from displayed-preview
// pixel coordinates to the original photo's pixel coordinates and written into a hidden form
// field as a JSON array, which the backend passes straight to normalize_card_image().
(function () {
  const fileInput = document.getElementById("grading-image-input");
  const wrap = document.getElementById("cropper-wrap");
  const container = document.getElementById("cropper-container");
  const img = document.getElementById("cropper-image");
  const poly = document.getElementById("cropper-poly");
  const magnifier = document.getElementById("cropper-magnifier");
  const hiddenInput = document.getElementById("grading-corners-input");
  const handles = Array.from(document.querySelectorAll(".cropper-handle"));

  if (!fileInput || !wrap) return;

  const ZOOM = 3;
  const MAG_SIZE = 130; // must match .cropper-magnifier width/height in style.css
  const MAG_OFFSET = 90; // vertical distance from the touch point to the magnifier's center

  let naturalW = 0;
  let naturalH = 0;
  let points = [[0, 0], [0, 0], [0, 0], [0, 0]]; // displayed-preview pixel coords

  function clamp(v, min, max) {
    return Math.max(min, Math.min(max, v));
  }

  function updateVisuals() {
    handles.forEach((h, i) => {
      h.style.left = points[i][0] + "px";
      h.style.top = points[i][1] + "px";
    });
    poly.setAttribute("points", points.map((p) => p.join(",")).join(" "));
  }

  function updateHiddenInput() {
    const rect = img.getBoundingClientRect();
    const scaleX = naturalW / rect.width;
    const scaleY = naturalH / rect.height;
    const naturalPoints = points.map(([x, y]) => [x * scaleX, y * scaleY]);
    hiddenInput.value = JSON.stringify(naturalPoints);
  }

  function initPoints() {
    const rect = img.getBoundingClientRect();
    const w = rect.width;
    const h = rect.height;
    const insetX = w * 0.08;
    const insetY = h * 0.08;
    points = [
      [insetX, insetY],
      [w - insetX, insetY],
      [w - insetX, h - insetY],
      [insetX, h - insetY],
    ];
    updateVisuals();
    updateHiddenInput();
  }

  fileInput.addEventListener("change", () => {
    const file = fileInput.files && fileInput.files[0];
    if (!file) {
      wrap.style.display = "none";
      return;
    }
    const reader = new FileReader();
    reader.onload = (e) => {
      img.onload = () => {
        naturalW = img.naturalWidth;
        naturalH = img.naturalHeight;
        magnifier.style.backgroundImage = `url(${img.src})`;
        wrap.style.display = "block";
        initPoints();
      };
      img.src = e.target.result;
    };
    reader.readAsDataURL(file);
  });

  function showMagnifier(x, y, rect) {
    const bgW = rect.width * ZOOM;
    const bgH = rect.height * ZOOM;
    magnifier.style.backgroundSize = `${bgW}px ${bgH}px`;
    magnifier.style.backgroundPosition = `${-(x * ZOOM - MAG_SIZE / 2)}px ${-(y * ZOOM - MAG_SIZE / 2)}px`;

    // Center the loupe above the touch point by default (so the cursor/finger never covers the
    // area it's magnifying); flip below if too close to the top edge of the preview.
    let magY = y - MAG_OFFSET - MAG_SIZE / 2;
    if (magY < 0) magY = y + MAG_OFFSET - MAG_SIZE / 2;
    magY = clamp(magY, 0, rect.height - MAG_SIZE);
    const magX = clamp(x - MAG_SIZE / 2, 0, rect.width - MAG_SIZE);

    magnifier.style.left = `${magX}px`;
    magnifier.style.top = `${magY}px`;
    magnifier.style.display = "block";
  }

  function hideMagnifier() {
    magnifier.style.display = "none";
  }

  let draggingIdx = null;

  handles.forEach((h) => {
    h.addEventListener("pointerdown", (e) => {
      draggingIdx = parseInt(h.dataset.idx, 10);
      const rect = container.getBoundingClientRect();
      const [x, y] = points[draggingIdx];
      showMagnifier(x, y, rect);
      e.preventDefault();
    });
  });

  document.addEventListener("pointermove", (e) => {
    if (draggingIdx === null) return;
    const rect = container.getBoundingClientRect();
    const x = clamp(e.clientX - rect.left, 0, rect.width);
    const y = clamp(e.clientY - rect.top, 0, rect.height);
    points[draggingIdx] = [x, y];
    updateVisuals();
    showMagnifier(x, y, rect);
  });

  document.addEventListener("pointerup", () => {
    if (draggingIdx === null) return;
    draggingIdx = null;
    hideMagnifier();
    updateHiddenInput();
  });
})();
