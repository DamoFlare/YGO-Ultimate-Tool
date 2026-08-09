// Manual 4-corner card cropper for the Grading page. No external dependencies (project-wide
// convention: vanilla JS, no build step). `createCornerPicker` is a factory so the page can run
// two fully independent instances (single-photo flow + bulk-photos flow) without their drag
// state interfering with each other. Each instance shows a magnifying loupe that follows the
// cursor while dragging, for sub-pixel precision.
function createCornerPicker(ids) {
  const wrap = document.getElementById(ids.wrap);
  const container = document.getElementById(ids.container);
  const img = document.getElementById(ids.image);
  const poly = document.getElementById(ids.poly);
  const magnifier = document.getElementById(ids.magnifier);
  const handles = Array.from(container.querySelectorAll(".cropper-handle"));

  const ZOOM = 3;
  const MAG_SIZE = 130; // must match .cropper-magnifier width/height in style.css
  const MAG_OFFSET = 90; // vertical distance from the touch point to the magnifier's center

  let naturalW = 0;
  let naturalH = 0;
  let points = [[0, 0], [0, 0], [0, 0], [0, 0]]; // displayed-preview pixel coords
  let draggingIdx = null;

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
  }

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

  handles.forEach((h) => {
    h.addEventListener("pointerdown", (e) => {
      draggingIdx = parseInt(h.dataset.idx, 10);
      const rect = container.getBoundingClientRect();
      showMagnifier(points[draggingIdx][0], points[draggingIdx][1], rect);
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
  });

  return {
    // Loads `file` into the preview and resets the 4 handles to a default inset quad. Calls
    // `onReady` once the image has actually loaded and the handles are positioned.
    loadFile(file, onReady) {
      const reader = new FileReader();
      reader.onload = (e) => {
        img.onload = () => {
          naturalW = img.naturalWidth;
          naturalH = img.naturalHeight;
          magnifier.style.backgroundImage = `url(${img.src})`;
          wrap.style.display = "block";
          initPoints();
          if (onReady) onReady();
        };
        img.src = e.target.result;
      };
      reader.readAsDataURL(file);
    },
    // Current 4 corners converted from displayed-preview pixels to the source image's own
    // pixel grid — what normalize_card_image() on the backend expects.
    cornersInNaturalCoords() {
      const rect = img.getBoundingClientRect();
      const scaleX = naturalW / rect.width;
      const scaleY = naturalH / rect.height;
      return points.map(([x, y]) => [x * scaleX, y * scaleY]);
    },
    hide() {
      wrap.style.display = "none";
    },
  };
}

(function () {
  // --- Single-photo flow: cropper feeds the hidden "corners" field of the existing htmx form.
  const singleInput = document.getElementById("grading-image-input");
  if (singleInput) {
    const picker = createCornerPicker({
      wrap: "cropper-wrap",
      container: "cropper-container",
      image: "cropper-image",
      poly: "cropper-poly",
      magnifier: "cropper-magnifier",
    });
    const hiddenInput = document.getElementById("grading-corners-input");

    singleInput.addEventListener("change", () => {
      const file = singleInput.files && singleInput.files[0];
      if (!file) {
        picker.hide();
        return;
      }
      picker.loadFile(file, () => {
        hiddenInput.value = JSON.stringify(picker.cornersInNaturalCoords());
      });
    });

    // Corners can still move after loading — refresh the hidden field right before submit so
    // htmx always sends the latest drag position, not just the one captured at load time.
    const form = singleInput.closest("form");
    if (form) {
      form.addEventListener("submit", () => {
        if (singleInput.files && singleInput.files[0]) {
          hiddenInput.value = JSON.stringify(picker.cornersInNaturalCoords());
        }
      });
    }
  }

  // --- Bulk flow, two phases:
  // 1) Cropping: pick N files (or a whole folder), crop them one at a time — no network calls,
  //    each confirmed crop is just stashed client-side ({file, corners}). The user doesn't wait
  //    on anything here; cropping N photos back-to-back is as fast as they can drag.
  // 2) Analysis: once every photo has been cropped (or skipped), POST each stashed crop to
  //    /grading/analyze in sequence via fetch (not htmx — needs imperative "wait for this one,
  //    then start the next"), refreshing the pending-gradings inbox after each. The user can
  //    walk away during this phase; nothing here requires their input. Note this loop is driven
  //    by this browser tab staying open — closing it stops any analyses not yet started.
  const bulkInput = document.getElementById("bulk-grading-input");
  const bulkFolderInput = document.getElementById("bulk-grading-folder-input");
  const bulkConfirmBtn = document.getElementById("bulk-confirm-btn");
  const bulkSkipBtn = document.getElementById("bulk-skip-btn");
  const bulkProgress = document.getElementById("bulk-grading-progress");
  const bulkLog = document.getElementById("bulk-grading-log");

  if (bulkInput && bulkConfirmBtn) {
    const picker = createCornerPicker({
      wrap: "bulk-cropper-wrap",
      container: "bulk-cropper-container",
      image: "bulk-cropper-image",
      poly: "bulk-cropper-poly",
      magnifier: "bulk-cropper-magnifier",
    });

    let cropQueue = []; // File objects still to crop
    let cropIndex = 0;
    let cropped = []; // { file, corners } already confirmed, awaiting analysis

    function logLine(text) {
      const p = document.createElement("p");
      p.className = "description";
      p.textContent = text;
      bulkLog.prepend(p);
    }

    function showCurrentCrop() {
      if (cropIndex >= cropQueue.length) {
        picker.hide();
        cropQueue = [];
        cropIndex = 0;
        startAnalysisPhase();
        return;
      }
      bulkProgress.textContent =
        `Cropping ${cropIndex + 1} of ${cropQueue.length}: "${cropQueue[cropIndex].name}" — drag the 4 corners, then confirm.`;
      picker.loadFile(cropQueue[cropIndex], () => {});
    }

    async function startAnalysisPhase() {
      if (!cropped.length) {
        bulkProgress.textContent = "";
        return;
      }
      const total = cropped.length;
      bulkConfirmBtn.disabled = true;
      bulkSkipBtn.disabled = true;
      logLine(`— Cropping complete, starting analysis of ${total} photo${total === 1 ? "" : "s"} —`);

      for (let i = 0; i < cropped.length; i++) {
        const { file, corners } = cropped[i];
        bulkProgress.textContent = `Analyzing ${i + 1} of ${total}: "${file.name}" (may take a few seconds)...`;
        try {
          const formData = new FormData();
          formData.append("image", file, file.name);
          formData.append("corners", JSON.stringify(corners));
          const res = await fetch("/grading/analyze", { method: "POST", body: formData });
          const html = await res.text();
          const errorEl = new DOMParser().parseFromString(html, "text/html").querySelector(".result-box.error");
          if (res.ok && !errorEl) {
            logLine(`✅ ${file.name} analyzed.`);
          } else {
            logLine(`❌ ${file.name}: ${errorEl ? errorEl.textContent.trim() : "analysis failed."}`);
          }
        } catch (err) {
          logLine(`❌ ${file.name}: network error (${err}).`);
        }
        // Refresh the inbox after each analysis, not just at the end, so progress is visible
        // live if the user is still watching (and already there once they come back if not).
        if (window.htmx) {
          window.htmx.ajax("GET", "/grading/pending", { target: "#grading-pending", swap: "outerHTML" });
        }
      }

      logLine(`— Analysis complete: ${total} photo${total === 1 ? "" : "s"} —`);
      bulkProgress.textContent = `Done: ${total} photo${total === 1 ? "" : "s"} analyzed.`;
      cropped = [];
      bulkConfirmBtn.disabled = false;
      bulkSkipBtn.disabled = false;
    }

    function startQueue(fileList) {
      cropQueue = Array.from(fileList).filter((f) => f.type.startsWith("image/"));
      cropIndex = 0;
      cropped = [];
      bulkLog.innerHTML = "";
      if (!cropQueue.length) {
        bulkProgress.textContent = "No images found in the selection.";
        return;
      }
      showCurrentCrop();
    }

    bulkInput.addEventListener("change", () => {
      if (bulkInput.files && bulkInput.files.length) startQueue(bulkInput.files);
    });
    if (bulkFolderInput) {
      bulkFolderInput.addEventListener("change", () => {
        if (bulkFolderInput.files && bulkFolderInput.files.length) startQueue(bulkFolderInput.files);
      });
    }

    bulkConfirmBtn.addEventListener("click", () => {
      if (cropIndex >= cropQueue.length) return;
      cropped.push({ file: cropQueue[cropIndex], corners: picker.cornersInNaturalCoords() });
      cropIndex += 1;
      showCurrentCrop();
    });

    bulkSkipBtn.addEventListener("click", () => {
      if (cropIndex < cropQueue.length) logLine(`⏭️ ${cropQueue[cropIndex].name} skipped from cropping.`);
      cropIndex += 1;
      showCurrentCrop();
    });
  }
})();
