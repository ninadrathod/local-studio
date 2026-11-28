/**
 * Frontend entry — preset gallery, keyword search, upload, and apply-preset generate flow.
 * All session state is in-memory; a page refresh clears upload + result.
 */
import {
  applyPreset,
  listPopularPresets,
  previewImage,
  recordPresetUse,
  searchPresets,
} from "./js/api.js";
import { isImageFile, createObjectUrl, revokeObjectUrl } from "./js/image.js";

/**
 * The API is always same-origin: the frontend container's nginx proxies /api/* to
 * the backend container, which has no port of its own on the host.
 */
const API_BASE = "";
const PRESETS_MANIFEST = "previews/presets.json";
/** The manifest lists newest presets first (the gallery keeps that order); this many get a "New" badge. */
const NEW_BADGE_COUNT = 5;
const SEARCH_DEBOUNCE_MS = 180;

/** Allowed relative paths for gallery thumbnails (no schemes / traversal). */
const PREVIEW_PATH_RE =
  /^previews\/(pre-edit|post-edit)\/[A-Za-z0-9][A-Za-z0-9._-]*\.(jpe?g|png|webp|gif)$/i;

/** DB / JSON preset_name shape used by this project. */
const PRESET_NAME_RE = /^[a-z0-9][a-z0-9_]{0,63}$/;
/** Name words shown fully upper-case in labels (e.g. `full_hd` → "Full HD", `4k_crisp` → "4K Crisp", `doodle_corner_xo` → "Doodle Corner XO"). */
const UPPERCASE_LABEL_WORD_RE = /^(hd|uhd|xo|\d+k)$/i;
const MAX_PRESET_TEXT_CHARS = 200;

const els = {
  presetGrid: document.getElementById("preset-grid"),
  presetScroller: document.getElementById("preset-scroller"),
  presetLoading: document.getElementById("preset-loading"),
  presetError: document.getElementById("preset-error"),
  selectedPresetLabel: document.getElementById("selected-preset-label"),
  presetSearch: document.getElementById("preset-search"),
  presetReset: document.getElementById("preset-reset"),
  presetCount: document.getElementById("preset-count"),
  presetCountSr: document.getElementById("preset-count-sr"),
  squareFilter: document.getElementById("square-filter"),
  popularSortBtn: document.getElementById("popular-sort-btn"),
  searchError: document.getElementById("search-error"),
  input: document.getElementById("image-input"),
  dropZone: document.getElementById("drop-zone"),
  uploadPrompt: document.getElementById("upload-prompt"),
  previewOriginal: document.getElementById("preview-original"),
  previewEdited: document.getElementById("preview-edited"),
  resultPlaceholder: document.getElementById("result-placeholder"),
  generateBtn: document.getElementById("generate-btn"),
  downloadBtn: document.getElementById("download-btn"),
  loading: document.getElementById("loading"),
  fileError: document.getElementById("file-error"),
  apiError: document.getElementById("api-error"),
  fileMeta: document.getElementById("file-meta"),
  presetTextWrap: document.getElementById("preset-text-wrap"),
  presetText: document.getElementById("preset-text"),
  presetTextCount: document.getElementById("preset-text-count"),
  uploadPromptTitle: document.getElementById("upload-prompt-title"),
  uploadPromptSub: document.getElementById("upload-prompt-sub"),
};

/** @type {string|null} */
let selectedPresetName = null;
/** @type {File|null} */
let selectedFile = null;
/** @type {string|null} */
let originalUrl = null;
/** @type {string|null} */
let editedUrl = null;
/** In-flight apply-preset request, so a busy preview can wait for it. @type {Promise<unknown>|null} */
let activeGenerate = null;
/** Bumped when inputs change or a new generate starts — ignores stale responses. */
let generateGeneration = 0;
/** Nested dragenter counter so child nodes don't flicker the drop highlight. */
let dragDepth = 0;
/** @type {Array<{ preset_name: string, ar: string, text_input: string, default_text: string, text_character_limit: number, pre_edit_image: string, post_edit_image: string }>} */
let allGalleryPresets = [];
/** Bumped on each search keystroke — ignores stale responses. */
let searchGeneration = 0;
/** @type {ReturnType<typeof setTimeout>|null} */
let searchDebounceTimer = null;
/** Last search match names; `null` means no search filter. */
let searchMatchNames = null;
/** When false, hide square-only presets. Default yes → show all. */
let inputImageIsSquare = true;
/** When true, the search-row refresh loads gallery order from the `popular` table. */
let popularSortActive = false;
/** Last applied popular `preset_name` order; `null` means the default newest-first order. */
let popularOrderNames = null;
/** Bumped on each popular refresh — ignores stale responses. */
let popularGeneration = 0;

function formatPresetLabel(name) {
  return String(name || "")
    .split("_")
    .filter(Boolean)
    .map((word) =>
      UPPERCASE_LABEL_WORD_RE.test(word)
        ? word.toUpperCase()
        : word.charAt(0).toUpperCase() + word.slice(1),
    )
    .join(" ");
}

/**
 * @param {unknown} name
 * @returns {name is string}
 */
function isValidPresetName(name) {
  return typeof name === "string" && PRESET_NAME_RE.test(name);
}

/**
 * @param {unknown} value
 * @returns {"square"|"non-square"}
 */
function normalizeAr(value) {
  return value === "square" ? "square" : "non-square";
}

/**
 * @param {unknown} value
 * @returns {"yes"|"no"}
 */
function normalizeTextInput(value) {
  return value === "yes" ? "yes" : "no";
}

/**
 * @param {unknown} value
 * @returns {number}
 */
function normalizeTextLimit(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n < 0) return 0;
  return Math.min(MAX_PRESET_TEXT_CHARS, Math.floor(n));
}

/**
 * @param {unknown} value
 * @param {number} limit
 * @returns {string}
 */
function normalizeDefaultText(value, limit) {
  const text = typeof value === "string" ? value : "";
  if (limit > 0 && text.length > limit) return text.slice(0, limit);
  if (text.length > MAX_PRESET_TEXT_CHARS) {
    return text.slice(0, MAX_PRESET_TEXT_CHARS);
  }
  return text;
}

function selectedGalleryPreset() {
  if (!selectedPresetName) return null;
  return allGalleryPresets.find((p) => p.preset_name === selectedPresetName) ?? null;
}

function selectedPresetNeedsText() {
  return selectedGalleryPreset()?.text_input === "yes";
}

/**
 * Only allow relative gallery paths under previews/pre-edit|post-edit.
 * @param {unknown} path
 * @returns {path is string}
 */
function isSafePreviewPath(path) {
  if (typeof path !== "string" || !path) return false;
  if (path.includes("..") || path.includes("\\") || path.includes("\0")) return false;
  if (path.startsWith("/") || path.startsWith("//")) return false;
  if (/^[a-z][a-z0-9+.-]*:/i.test(path)) return false;
  return PREVIEW_PATH_RE.test(path);
}

function formatFileMeta(file) {
  const kb = file.size / 1024;
  const size = kb >= 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(kb))} KB`;
  return `${file.name} · ${size}`;
}

function clearFileMeta() {
  if (!els.fileMeta) return;
  els.fileMeta.textContent = "";
  els.fileMeta.classList.add("hidden");
}

function setFileMeta(file) {
  if (!els.fileMeta) return;
  els.fileMeta.textContent = formatFileMeta(file);
  els.fileMeta.classList.remove("hidden");
  els.fileMeta.title = file.name;
}

function showError(el, message) {
  el.textContent = message;
  el.classList.remove("hidden");
}

function clearError(el) {
  el.textContent = "";
  el.classList.add("hidden");
}

function canGenerate() {
  if (!selectedPresetName || !selectedFile) return false;
  if (selectedPresetNeedsText()) {
    const preset = selectedGalleryPreset();
    const limit = preset?.text_character_limit ?? 0;
    const value = els.presetText?.value ?? "";
    if (limit > 0 && value.length > limit) return false;
  }
  return true;
}

function isUploadEnabled() {
  return Boolean(selectedPresetName);
}

function updateUploadPromptCopy() {
  if (!els.uploadPromptTitle || !els.uploadPromptSub) return;
  if (!isUploadEnabled()) {
    els.uploadPromptTitle.textContent = "Select a preset first";
    els.uploadPromptSub.textContent = "Then drop an image, or browse";
    return;
  }
  els.uploadPromptTitle.textContent = "Drop an image, or browse";
  els.uploadPromptSub.textContent = "PNG, JPG, WEBP, GIF";
}

function setUploadEnabled(enabled) {
  els.dropZone.classList.toggle("drop-zone--locked", !enabled);
  els.dropZone.setAttribute("aria-disabled", enabled ? "false" : "true");
  els.input.disabled = !enabled;
  updateUploadPromptCopy();
}

function updateTextCount() {
  if (!els.presetTextCount || !els.presetText) return;
  const limit = Number(els.presetText.maxLength) || 0;
  const used = els.presetText.value.length;
  els.presetTextCount.textContent = limit > 0 ? `${used} / ${limit}` : "";
}

function syncPresetTextField() {
  if (!els.presetTextWrap || !els.presetText) return;
  const preset = selectedGalleryPreset();
  const needsText = preset?.text_input === "yes";
  els.presetTextWrap.classList.toggle("hidden", !needsText);
  els.presetTextWrap.toggleAttribute("hidden", !needsText);
  if (!needsText) {
    els.presetText.value = "";
    els.presetText.removeAttribute("maxlength");
    els.presetText.setAttribute("aria-hidden", "true");
    if (els.presetTextCount) els.presetTextCount.textContent = "";
    return;
  }
  const limit = preset.text_character_limit > 0
    ? preset.text_character_limit
    : MAX_PRESET_TEXT_CHARS;
  els.presetText.removeAttribute("aria-hidden");
  els.presetText.maxLength = limit;
  els.presetText.value = normalizeDefaultText(preset.default_text, limit);
  updateTextCount();
}

function isLoading() {
  return !els.loading.classList.contains("hidden");
}

function updateGenerateEnabled() {
  els.generateBtn.disabled = !canGenerate() || isLoading();
}

function invalidateInFlightGenerate() {
  generateGeneration += 1;
}

function resetResult() {
  invalidateInFlightGenerate();
  els.loading.classList.add("hidden");
  if (editedUrl) {
    revokeObjectUrl(editedUrl);
    editedUrl = null;
  }
  els.previewEdited.classList.add("hidden");
  els.previewEdited.removeAttribute("src");
  els.resultPlaceholder.classList.remove("hidden");
  els.downloadBtn.classList.add("hidden");
  els.downloadBtn.removeAttribute("href");
  els.downloadBtn.setAttribute("download", "edited-image.png");
  updateGenerateEnabled();
}

function setSelectedPreset(name) {
  selectedPresetName = name;
  clearError(els.apiError);
  resetResult();

  /** @type {HTMLElement|null} */
  let activeCard = null;
  const cards = els.presetGrid.querySelectorAll(".preset-card");
  cards.forEach((card) => {
    const isActive = card.dataset.presetName === name;
    card.classList.toggle("preset-card--selected", isActive);
    card.setAttribute("aria-selected", isActive ? "true" : "false");
    if (isActive) activeCard = card;
  });

  if (name) {
    const label = formatPresetLabel(name);
    els.selectedPresetLabel.textContent = label;
    els.selectedPresetLabel.title = name;
    els.presetGrid.setAttribute("aria-activedescendant", `preset-${name}`);
    activeCard?.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
  } else {
    els.selectedPresetLabel.textContent = "No preset selected";
    els.selectedPresetLabel.removeAttribute("title");
    els.presetGrid.removeAttribute("aria-activedescendant");
    // Select-preset-first flow: clearing the preset also clears the upload.
    if (selectedFile || originalUrl) {
      els.input.value = "";
      setSelectedFile(null);
    }
  }

  if (els.presetReset) {
    updateGalleryActionButton();
  }

  setUploadEnabled(Boolean(name));
  syncPresetTextField();
  updateGenerateEnabled();
}

function setSelectedFile(file) {
  // Allow clearing even when upload is locked; only block new picks.
  if (file && !isUploadEnabled()) {
    els.input.value = "";
    return;
  }
  clearError(els.fileError);
  clearError(els.apiError);
  resetResult();

  if (!file) {
    selectedFile = null;
    if (originalUrl) {
      revokeObjectUrl(originalUrl);
      originalUrl = null;
    }
    els.previewOriginal.classList.add("hidden");
    els.previewOriginal.removeAttribute("src");
    els.uploadPrompt.classList.remove("hidden");
    els.dropZone.classList.remove("drop-zone--filled");
    clearFileMeta();
    updateGenerateEnabled();
    return;
  }

  if (!isImageFile(file)) {
    selectedFile = null;
    if (originalUrl) {
      revokeObjectUrl(originalUrl);
      originalUrl = null;
    }
    els.previewOriginal.classList.add("hidden");
    els.previewOriginal.removeAttribute("src");
    els.uploadPrompt.classList.remove("hidden");
    els.dropZone.classList.remove("drop-zone--filled");
    clearFileMeta();
    showError(els.fileError, "Please choose an image file (PNG, JPG, HEIC, WEBP, or GIF).");
    updateGenerateEnabled();
    return;
  }

  if (originalUrl) revokeObjectUrl(originalUrl);
  originalUrl = createObjectUrl(file);
  selectedFile = file;

  // Browsers that can't decode the file (HEIC outside Safari, TIFF) get a
  // server-rendered preview instead; the original file is still what's edited.
  els.previewOriginal.onerror = () => {
    els.previewOriginal.onerror = null;
    loadServerPreview(file);
  };
  els.previewOriginal.src = originalUrl;
  els.previewOriginal.classList.remove("hidden");
  els.uploadPrompt.classList.add("hidden");
  els.dropZone.classList.add("drop-zone--filled");
  setFileMeta(file);
  updateGenerateEnabled();
}

/**
 * While an edit holds the server's job slot (503), wait for our own edit to
 * finish, or back off (1 s doubling to 8 s) — each retry re-uploads the file.
 */
const PREVIEW_BUSY_RETRIES = 10;
const PREVIEW_BUSY_MAX_DELAY_MS = 8000;

async function loadServerPreview(file) {
  for (let attempt = 0; selectedFile === file; attempt++) {
    try {
      const blob = await previewImage(API_BASE, file);
      if (selectedFile !== file) return;
      if (originalUrl) revokeObjectUrl(originalUrl);
      originalUrl = createObjectUrl(blob);
      els.previewOriginal.src = originalUrl;
      return;
    } catch (err) {
      if (selectedFile !== file) return;
      if (err.status === 503 && attempt < PREVIEW_BUSY_RETRIES) {
        if (activeGenerate) {
          await activeGenerate.catch(() => {});
        } else {
          const delay = Math.min(1000 * 2 ** attempt, PREVIEW_BUSY_MAX_DELAY_MS);
          await new Promise((resolve) => setTimeout(resolve, delay));
        }
        continue;
      }
      showError(els.fileError, `Preview unavailable: ${err.message || "could not decode image."}`);
      return;
    }
  }
}

function setLoading(loading) {
  els.loading.classList.toggle("hidden", !loading);
  updateGenerateEnabled();
}

async function handleGenerate() {
  if (!canGenerate() || isLoading()) return;

  const presetName = selectedPresetName;
  const file = selectedFile;
  const token = ++generateGeneration;

  clearError(els.apiError);

  const selected = selectedGalleryPreset();
  const uploadedIsSquare = isPreviewImageSquare();
  if (
    selected &&
    selected.ar === "square" &&
    uploadedIsSquare === false
  ) {
    showError(els.apiError, "This preset only applies to square images.");
    return;
  }

  const text = selectedPresetNeedsText() ? (els.presetText?.value ?? "") : undefined;

  setLoading(true);

  try {
    const request = applyPreset(API_BASE, presetName, file, text);
    activeGenerate = request;
    const blob = await request.finally(() => {
      if (activeGenerate === request) activeGenerate = null;
    });
    if (token !== generateGeneration) return;

    if (editedUrl) revokeObjectUrl(editedUrl);
    editedUrl = createObjectUrl(blob);

    els.previewEdited.src = editedUrl;
    els.previewEdited.classList.remove("hidden");
    els.resultPlaceholder.classList.add("hidden");
    els.downloadBtn.href = editedUrl;
    // JPEG uploads come back as JPEG; everything else as PNG.
    const ext = blob.type === "image/jpeg" ? "jpg" : "png";
    els.downloadBtn.download = `${presetName}-edit.${ext}`;
    els.downloadBtn.classList.remove("hidden");
  } catch (err) {
    if (token !== generateGeneration) return;
    showError(els.apiError, err.message || "Something went wrong. Is the server running?");
  } finally {
    if (token === generateGeneration) {
      setLoading(false);
    }
  }
}

/**
 * @param {{ preset_name: string, pre_edit_image: string, post_edit_image: string }} preset
 */
function createPresetCard(preset) {
  const name = preset.preset_name;
  const label = formatPresetLabel(name);

  const button = document.createElement("button");
  button.type = "button";
  button.id = `preset-${name}`;
  button.className = "preset-card";
  button.dataset.presetName = name;
  button.setAttribute("role", "option");
  const isSelected = name === selectedPresetName;
  button.setAttribute("aria-selected", isSelected ? "true" : "false");
  if (isSelected) button.classList.add("preset-card--selected");
  button.setAttribute(
    "aria-label",
    `Select ${preset.is_new ? "new " : ""}preset ${label}. Hover, focus, or press and hold to compare with the original photo.`,
  );

  const media = document.createElement("span");
  media.className = "preset-card__media";

  const imgEdited = document.createElement("img");
  imgEdited.className = "preset-card__img preset-card__img--edited";
  imgEdited.src = preset.post_edit_image;
  imgEdited.alt = "";
  imgEdited.loading = "lazy";
  imgEdited.decoding = "async";
  // A long-press drag "lift" (iOS) would cancel the press-and-hold compare.
  imgEdited.draggable = false;

  const imgOriginal = document.createElement("img");
  imgOriginal.className = "preset-card__img preset-card__img--original";
  imgOriginal.src = preset.pre_edit_image;
  imgOriginal.alt = "";
  imgOriginal.loading = "lazy";
  imgOriginal.decoding = "async";
  imgOriginal.draggable = false;
  primeOriginalImage(button, imgEdited, imgOriginal);

  media.append(imgEdited, imgOriginal);
  if (preset.is_new) {
    const badge = document.createElement("span");
    badge.className = "preset-card__badge";
    badge.textContent = "New";
    badge.setAttribute("aria-hidden", "true"); // announced via the card's aria-label
    media.append(badge);
  }

  const nameEl = document.createElement("span");
  nameEl.className = "preset-card__name";
  nameEl.textContent = label;

  button.append(media, nameEl);
  button.addEventListener("click", () => setSelectedPreset(name));
  return button;
}

/**
 * The original photo sits fully clipped until a hover/peek wipes it in, so the
 * browser would otherwise fetch and decode it only at that moment and the wipe
 * would reveal an empty frame. Once the card's edited image has loaded (the card
 * is near the viewport), fetch + decode the original ahead of time, and mark the
 * card ready so the CSS only starts the wipe when there is a picture to show.
 * @param {HTMLElement} card
 * @param {HTMLImageElement} imgEdited
 * @param {HTMLImageElement} imgOriginal
 */
function primeOriginalImage(card, imgEdited, imgOriginal) {
  let primed = false;
  const markReady = () => card.classList.add("preset-card--ready");
  const prime = () => {
    if (primed) return;
    primed = true;
    imgOriginal.loading = "eager";
    imgOriginal.decode().then(markReady, markReady);
  };
  imgEdited.addEventListener("load", prime, { once: true });
  imgEdited.addEventListener("error", prime, { once: true });
  // Hovering, focusing, or pressing before the edited image arrived: start now.
  card.addEventListener("pointerenter", prime, { once: true });
  card.addEventListener("pointerdown", prime, { once: true });
  card.addEventListener("focus", prime, { once: true });
}

function isPreviewImageSquare() {
  const img = els.previewOriginal;
  if (!img || img.classList.contains("hidden")) return null;
  const width = img.naturalWidth;
  const height = img.naturalHeight;
  if (!width || !height) return null;
  return width === height;
}

/**
 * @param {Array<{ preset_name: string, ar: string, text_input: string, default_text: string, text_character_limit: number, pre_edit_image: string, post_edit_image: string }>} presets
 * @param {{ emptyMessage?: string }} [options]
 */
function renderPresetGrid(presets, options = {}) {
  els.presetGrid.replaceChildren();

  if (!presets.length) {
    els.presetGrid.removeAttribute("aria-activedescendant");
    const empty = document.createElement("p");
    empty.className = "col-span-full text-sm text-mute py-8 text-center";
    empty.textContent = options.emptyMessage || "No presets to show.";
    els.presetGrid.appendChild(empty);
    return;
  }

  for (const preset of presets) {
    els.presetGrid.appendChild(createPresetCard(preset));
  }

  const activeCard = selectedPresetName
    ? els.presetGrid.querySelector(`#preset-${selectedPresetName}`)
    : null;
  if (activeCard) {
    els.presetGrid.setAttribute("aria-activedescendant", activeCard.id);
  } else {
    els.presetGrid.removeAttribute("aria-activedescendant");
  }
}

async function loadPresets() {
  clearError(els.presetError);

  try {
    const response = await fetch(PRESETS_MANIFEST);
    if (!response.ok) throw new Error(`Could not load presets (${response.status}).`);

    const presets = await response.json();
    if (!Array.isArray(presets) || presets.length === 0) {
      throw new Error("No presets found in the gallery.");
    }

    els.presetLoading?.remove();
    allGalleryPresets = [];

    let skipped = 0;
    for (const preset of presets) {
      if (
        !isValidPresetName(preset?.preset_name) ||
        !isSafePreviewPath(preset?.pre_edit_image) ||
        !isSafePreviewPath(preset?.post_edit_image)
      ) {
        skipped += 1;
        continue;
      }
      const textLimit = normalizeTextLimit(preset.text_character_limit);
      allGalleryPresets.push({
        preset_name: preset.preset_name,
        ar: normalizeAr(preset.ar),
        text_input: normalizeTextInput(preset.text_input),
        default_text: normalizeDefaultText(preset.default_text, textLimit),
        text_character_limit: textLimit,
        pre_edit_image: preset.pre_edit_image,
        post_edit_image: preset.post_edit_image,
        // Manifest order is newest first, so the first valid entries are the newest.
        is_new: allGalleryPresets.length < NEW_BADGE_COUNT,
      });
    }

    if (!allGalleryPresets.length) {
      throw new Error(
        skipped
          ? "No valid presets found (entries failed name or image-path checks)."
          : "No valid presets found in the gallery.",
      );
    }

    // Manifest order is the default: newest first. Search / Popular reorder on top of it.
    renderVisibleGallery();
  } catch (err) {
    els.presetLoading?.remove();
    allGalleryPresets = [];
    showError(
      els.presetError,
      err.message || "Could not load the preset gallery.",
    );
  }
}

/**
 * @param {string[]} matchNames
 */
function applySearchFilter(matchNames) {
  searchMatchNames = matchNames.filter((n) => isValidPresetName(n));
  renderVisibleGallery();
}

function clearSearchFilter() {
  searchMatchNames = null;
  renderVisibleGallery();
}

function galleryAfterArFilter(list) {
  if (inputImageIsSquare) return list;
  return list.filter((p) => p.ar !== "square");
}

/**
 * Reorders `list` to match the order of names in `orderNames`. Entries whose
 * name isn't in `orderNames` keep their current relative order after the
 * ranked ones (Array.prototype.sort is stable).
 * @param {Array<{ preset_name: string }>} list
 * @param {Array<string>|null} orderNames
 * @returns {Array<{ preset_name: string }>}
 */
function reorderByNameRank(list, orderNames) {
  if (!orderNames) return list;
  const rank = new Map(orderNames.map((name, i) => [name, i]));
  return [...list].sort((a, b) => {
    const ra = rank.has(a.preset_name) ? rank.get(a.preset_name) : Number.MAX_SAFE_INTEGER;
    const rb = rank.has(b.preset_name) ? rank.get(b.preset_name) : Number.MAX_SAFE_INTEGER;
    return ra - rb;
  });
}

/**
 * Search keeps only the matches, in the default newest-first order (stable while
 * typing, so cards don't jump on each keystroke). No search → the full gallery.
 * @param {Array<{ preset_name: string }>} list
 * @returns {Array<{ preset_name: string }>}
 */
function galleryAfterSearchOrder(list) {
  if (!searchMatchNames) return list;
  const allowed = new Set(searchMatchNames);
  return list.filter((p) => allowed.has(p.preset_name));
}

/**
 * @param {Array<{ preset_name: string }>} list
 * @returns {Array<{ preset_name: string }>}
 */
function galleryAfterPopularSort(list) {
  return reorderByNameRank(list, popularOrderNames);
}

function setPopularButtonPressed(pressed) {
  if (!els.popularSortBtn) return;
  els.popularSortBtn.setAttribute("aria-pressed", pressed ? "true" : "false");
}

function updateGalleryActionButton() {
  if (!els.presetReset) return;
  if (popularSortActive) {
    els.presetReset.disabled = false;
    els.presetReset.setAttribute("aria-label", "Refresh popular preset order");
    els.presetReset.title = "Refresh popular preset order";
    return;
  }
  if (popularOrderNames) {
    els.presetReset.disabled = false;
    els.presetReset.setAttribute("aria-label", "Restore default preset order");
    els.presetReset.title = "Restore default preset order";
    return;
  }
  els.presetReset.disabled = !selectedPresetName;
  els.presetReset.setAttribute("aria-label", "Clear selected preset");
  els.presetReset.title = "Clear selected preset";
}

function restoreDefaultOrder() {
  popularGeneration += 1;
  popularOrderNames = null;
}

function renderVisibleGallery() {
  const searching = searchMatchNames != null;
  const allowed = searching ? new Set(searchMatchNames) : null;
  const matched = allowed
    ? allGalleryPresets.filter((p) => allowed.has(p.preset_name))
    : allGalleryPresets;
  const visible = galleryAfterPopularSort(
    galleryAfterSearchOrder(galleryAfterArFilter(matched)),
  );

  let emptyMessage = "No presets to show.";
  if (searching) emptyMessage = "No presets match that search.";
  else if (!inputImageIsSquare) emptyMessage = "No non-square presets to show.";

  renderPresetGrid(visible, { emptyMessage });
  updatePresetCount(visible.length, allGalleryPresets.length);

  if (
    selectedPresetName &&
    !visible.some((p) => p.preset_name === selectedPresetName)
  ) {
    setSelectedPreset(null);
  }
}

/**
 * Pill beside the "Presets" heading: the total, or "shown / total" when a
 * search or the square filter narrows the gallery.
 * @param {number} shown
 * @param {number} total
 */
function updatePresetCount(shown, total) {
  const el = els.presetCount;
  if (!el) return;
  if (!total) {
    el.hidden = true;
    if (els.presetCountSr) els.presetCountSr.textContent = "";
    return;
  }
  const filtered = shown !== total;
  // Visible pill is aria-hidden; the sr-only twin carries the spoken sentence.
  el.textContent = filtered ? `${shown} / ${total}` : String(total);
  el.classList.toggle("preset-count--filtered", filtered);
  el.hidden = false;
  if (els.presetCountSr) {
    els.presetCountSr.textContent = filtered
      ? `Showing ${shown} of ${total} presets`
      : `${total} presets`;
  }
}

/**
 * Page-drawn scroller for the preset grid (the native bar is hidden in CSS,
 * because mobile browsers and Firefox ignore scrollbar styling). Keeps the
 * thumb in sync with scroll / resize / re-render, and supports dragging the
 * thumb or tapping the rail to page up / down — with mouse, pen or finger.
 */
function initPresetScroller() {
  const grid = els.presetGrid;
  const bar = els.presetScroller;
  const thumb = bar?.querySelector(".preset-scroller__thumb");
  if (!grid || !bar || !thumb) return;

  let frame = 0;
  let thumbTop = 0;
  let thumbHeight = 0;
  let travel = 0; // px the thumb can move
  let drag = null; // { pointerId, startY, startScroll }

  function inset() {
    return parseFloat(getComputedStyle(bar).getPropertyValue("--scroller-inset")) * 16 || 6;
  }

  function layout() {
    frame = 0;
    const view = grid.clientHeight;
    const total = grid.scrollHeight;
    const scrollable = total - view;
    if (scrollable <= 1 || view <= 0) {
      bar.hidden = true;
      return;
    }
    bar.hidden = false;
    // Sit over the grid's right padding, the full height of the grid box.
    bar.style.top = `${grid.offsetTop}px`;
    bar.style.height = `${view}px`;
    bar.style.left = `${grid.offsetLeft + grid.offsetWidth - bar.offsetWidth - 2}px`;
    const pad = inset();
    const track = Math.max(0, view - 2 * pad);
    const minThumb = parseFloat(getComputedStyle(thumb).minHeight) || 44;
    thumbHeight = Math.min(track, Math.max(minThumb, (track * view) / total));
    travel = Math.max(0, track - thumbHeight);
    thumbTop = pad + (travel * grid.scrollTop) / scrollable;
    thumb.style.height = `${thumbHeight}px`;
    thumb.style.transform = `translateY(${thumbTop}px)`;
    // ARIA scrollbar value (0–100) so assistive tech still gets the position.
    const percent = Math.round((100 * grid.scrollTop) / scrollable);
    if (bar.getAttribute("aria-valuenow") !== String(percent)) {
      bar.setAttribute("aria-valuenow", String(percent));
      bar.setAttribute("aria-valuetext", `Scrolled ${percent}% through presets`);
    }
  }

  function schedule() {
    if (!frame) frame = requestAnimationFrame(layout);
  }

  grid.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", schedule);
  if ("ResizeObserver" in window) new ResizeObserver(schedule).observe(grid);
  // Cards are re-rendered on search / filter / sort.
  new MutationObserver(schedule).observe(grid, { childList: true });

  thumb.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    event.stopPropagation();
    drag = { pointerId: event.pointerId, startY: event.clientY, startScroll: grid.scrollTop };
    bar.classList.add("preset-scroller--dragging");
    try {
      // Keep receiving moves when the finger / cursor leaves the thin thumb.
      thumb.setPointerCapture(event.pointerId);
    } catch {
      // Pointer already gone (or synthetic): dragging still works while over the thumb.
    }
  });

  thumb.addEventListener("pointermove", (event) => {
    if (!drag || event.pointerId !== drag.pointerId || travel <= 0) return;
    const scrollable = grid.scrollHeight - grid.clientHeight;
    grid.scrollTop = drag.startScroll + ((event.clientY - drag.startY) * scrollable) / travel;
  });

  const endDrag = (event) => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    drag = null;
    bar.classList.remove("preset-scroller--dragging");
  };
  thumb.addEventListener("pointerup", endDrag);
  thumb.addEventListener("pointercancel", endDrag);

  // Tap / click on the rail: page toward that point.
  bar.addEventListener("pointerdown", (event) => {
    if (event.target === thumb) return;
    const y = event.clientY - bar.getBoundingClientRect().top;
    const direction = y < thumbTop ? -1 : 1;
    grid.scrollBy({ top: direction * grid.clientHeight * 0.9, behavior: "smooth" });
  });

  schedule();
}

function readInputSquareSwitch() {
  const checked = els.squareFilter?.querySelector(
    'input[name="input-square"]:checked',
  );
  inputImageIsSquare = checked?.value !== "no";
}

async function refreshPopularGallery() {
  if (!els.presetReset) return;

  const token = ++popularGeneration;
  clearError(els.searchError);
  els.presetReset.disabled = true;

  try {
    const rows = await listPopularPresets(API_BASE);
    if (token !== popularGeneration) return;
    popularOrderNames = rows
      .map((row) => row.preset_name)
      .filter((name) => isValidPresetName(name));
    renderVisibleGallery();
  } catch (err) {
    if (token !== popularGeneration) return;
    if (!popularOrderNames) {
      popularSortActive = false;
      setPopularButtonPressed(false);
    }
    showError(els.searchError, err.message || "Could not load popular presets.");
  } finally {
    if (token === popularGeneration) {
      updateGalleryActionButton();
    }
  }
}

function handlePopularSortClick() {
  popularSortActive = !popularSortActive;
  setPopularButtonPressed(popularSortActive);
  if (popularSortActive) {
    refreshPopularGallery();
    return;
  }
  restoreDefaultOrder();
  renderVisibleGallery();
  updateGalleryActionButton();
}

function handleGalleryActionClick() {
  if (popularSortActive) {
    refreshPopularGallery();
    return;
  }
  if (popularOrderNames) {
    restoreDefaultOrder();
    updateGalleryActionButton();
    renderVisibleGallery();
    return;
  }
  setSelectedPreset(null);
}

async function runPresetSearch(query) {
  if (!els.presetSearch) return;

  const q = String(query || "").trim();
  const token = ++searchGeneration;
  clearError(els.searchError);

  if (!q) {
    clearSearchFilter();
    return;
  }

  try {
    const matches = await searchPresets(API_BASE, q);
    if (token !== searchGeneration) return;
    applySearchFilter(matches.map((m) => m.preset_name));
  } catch (err) {
    if (token !== searchGeneration) return;
    clearSearchFilter();
    showError(els.searchError, err.message || "Preset search failed.");
  }
}

/* —— Touch compare: press and hold a preset card to peek at the original —— */

// Touch screens have no hover. A short tap still selects the card; holding
// past PEEK_DELAY_MS shows the original until the finger lifts, and that
// release doesn't select. Moving (i.e. scrolling the gallery) cancels.
const PEEK_DELAY_MS = 180;
const PEEK_MOVE_TOLERANCE_PX = 10;
const PEEK_CLICK_GRACE_MS = 500;

/** @type {{ card: HTMLElement, pointerId: number, x: number, y: number, timer: number, shown: boolean } | null} */
let peek = null;
/** Card whose next click is the tail of a peek and must not select it. */
let peekClickCard = null;

/** Hide the original; returns the card if the peek had become visible. */
function endPeek() {
  if (!peek) return null;
  clearTimeout(peek.timer);
  peek.card.classList.remove("preset-card--peek");
  const shownCard = peek.shown ? peek.card : null;
  peek = null;
  return shownCard;
}

function bindTouchCompare(grid) {
  grid.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse") return;
    const card = event.target.closest(".preset-card");
    if (!card) return;
    endPeek();
    const state = {
      card,
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      shown: false,
      timer: 0,
    };
    state.timer = setTimeout(() => {
      if (peek !== state) return;
      state.shown = true;
      card.classList.add("preset-card--peek");
    }, PEEK_DELAY_MS);
    peek = state;
  });

  grid.addEventListener("pointermove", (event) => {
    if (!peek || event.pointerId !== peek.pointerId) return;
    const moved = Math.hypot(event.clientX - peek.x, event.clientY - peek.y);
    if (moved > PEEK_MOVE_TOLERANCE_PX) endPeek();
  });

  grid.addEventListener("pointerup", (event) => {
    if (!peek || event.pointerId !== peek.pointerId) return;
    const shownCard = endPeek();
    if (!shownCard) return;
    peekClickCard = shownCard;
    // Some browsers fire no click after a long press; don't swallow a later tap.
    setTimeout(() => {
      if (peekClickCard === shownCard) peekClickCard = null;
    }, PEEK_CLICK_GRACE_MS);
  });

  // The browser takes over the pointer when the gallery starts scrolling.
  grid.addEventListener("pointercancel", () => endPeek());

  // Capture phase runs before the card's own click handler.
  grid.addEventListener(
    "click",
    (event) => {
      if (!peekClickCard || event.target.closest(".preset-card") !== peekClickCard) return;
      peekClickCard = null;
      event.preventDefault();
      event.stopPropagation();
    },
    true,
  );

  // Android opens the long-press menu while the finger is still down.
  grid.addEventListener("contextmenu", (event) => {
    if (peek || peekClickCard) event.preventDefault();
  });
}

function schedulePresetSearch() {
  if (!els.presetSearch) return;
  const value = els.presetSearch.value;
  if (searchDebounceTimer != null) clearTimeout(searchDebounceTimer);
  searchDebounceTimer = setTimeout(() => {
    searchDebounceTimer = null;
    runPresetSearch(value);
  }, SEARCH_DEBOUNCE_MS);
}

/* —— Event listeners —— */

bindTouchCompare(els.presetGrid);

els.input.addEventListener("change", () => {
  setSelectedFile(els.input.files?.[0] ?? null);
});

els.generateBtn.addEventListener("click", handleGenerate);

if (els.downloadBtn) {
  els.downloadBtn.addEventListener("click", () => {
    if (els.downloadBtn.classList.contains("hidden")) return;
    if (!selectedPresetName || !editedUrl) return;
    recordPresetUse(API_BASE, selectedPresetName).catch(() => {
      /* Tracking is best-effort; the download itself must still proceed. */
    });
  });
}

if (els.presetSearch) {
  els.presetSearch.addEventListener("input", schedulePresetSearch);
}

if (els.presetReset) {
  els.presetReset.addEventListener("click", handleGalleryActionClick);
}

if (els.squareFilter) {
  els.squareFilter.addEventListener("change", () => {
    readInputSquareSwitch();
    renderVisibleGallery();
  });
}

if (els.popularSortBtn) {
  els.popularSortBtn.addEventListener("click", handlePopularSortClick);
}

els.dropZone.addEventListener("dragenter", (e) => {
  e.preventDefault();
  if (!isUploadEnabled()) return;
  dragDepth += 1;
  els.dropZone.classList.add("drop-zone--active");
});

els.dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
});

els.dropZone.addEventListener("dragleave", (e) => {
  e.preventDefault();
  dragDepth = Math.max(0, dragDepth - 1);
  if (dragDepth === 0) {
    els.dropZone.classList.remove("drop-zone--active");
  }
});

els.dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dragDepth = 0;
  els.dropZone.classList.remove("drop-zone--active");
  if (!isUploadEnabled()) return;

  const file = e.dataTransfer?.files?.[0] ?? null;
  if (file) {
    const dt = new DataTransfer();
    dt.items.add(file);
    els.input.files = dt.files;
    setSelectedFile(file);
  }
});

if (els.presetText) {
  els.presetText.addEventListener("input", () => {
    updateTextCount();
    updateGenerateEnabled();
  });
}

initPresetScroller();
loadPresets();
