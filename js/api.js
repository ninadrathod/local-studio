/**
 * Talks to The Local Studio backend.
 */

/**
 * POST an image to /api/blur and return the blurred image as a Blob.
 * @param {string} baseUrl - API origin, e.g. http://localhost:8000
 * @param {File} file - Image file selected by the user
 * @returns {Promise<Blob>}
 */
export async function blurImage(baseUrl, file) {
  const form = new FormData();
  form.append("file", file);

  let response;
  try {
    response = await fetch(`${baseUrl}/api/blur`, {
      method: "POST",
      body: form,
    });
  } catch {
    throw new Error(
      `Could not reach the API at ${baseUrl}. Is the backend running (./scripts/run.sh)?`,
    );
  }

  if (!response.ok) {
    let detail = "Blur request failed.";
    try {
      const data = await response.json();
      if (data.detail) detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* ignore non-JSON error bodies */
    }
    throw new Error(detail);
  }

  return response.blob();
}

/**
 * POST an image to /api/preview and return a small JPEG/PNG preview Blob —
 * for uploads the browser can't render itself (HEIC outside Safari, TIFF).
 * @param {string} baseUrl - API origin, e.g. http://localhost:8000
 * @param {File} file - Image file selected by the user
 * @returns {Promise<Blob>}
 */
export async function previewImage(baseUrl, file) {
  const form = new FormData();
  form.append("file", file);

  let response;
  try {
    response = await fetch(`${baseUrl}/api/preview`, {
      method: "POST",
      body: form,
    });
  } catch {
    throw new Error(
      `Could not reach the API at ${baseUrl}. Is the backend running (./scripts/run.sh)?`,
    );
  }

  if (!response.ok) {
    let detail = "Preview request failed.";
    try {
      const data = await response.json();
      if (data.detail) detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* ignore non-JSON error bodies */
    }
    const error = new Error(detail);
    // 503 = an edit holds the server's single job slot; callers may retry.
    error.status = response.status;
    throw error;
  }

  return response.blob();
}

/**
 * GET presets whose name or keywords match `query` (case-insensitive substring).
 * Results are newest `preset_id` first.
 * @param {string} baseUrl - API origin, e.g. http://localhost:8000
 * @param {string} query - Search text
 * @returns {Promise<Array<{ preset_name: string, keywords: string[], ar?: string, text_input?: string, default_text?: string, text_character_limit?: number }>>}
 */
export async function searchPresets(baseUrl, query) {
  const q = String(query || "").trim();
  if (!q) return [];

  const url = `${baseUrl}/api/presets/search?q=${encodeURIComponent(q)}`;
  let response;
  try {
    response = await fetch(url);
  } catch {
    throw new Error(
      `Could not reach the API at ${baseUrl}. Is the backend running (./scripts/run.sh)?`,
    );
  }

  if (!response.ok) {
    let detail = "Preset search failed.";
    try {
      const data = await response.json();
      if (data.detail) detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* ignore non-JSON error bodies */
    }
    throw new Error(detail);
  }

  const data = await response.json();
  return Array.isArray(data) ? data : [];
}

/**
 * GET popular presets ordered by used_count descending.
 * @param {string} baseUrl - API origin, e.g. http://localhost:8000
 * @returns {Promise<Array<{ preset_id: number, preset_name: string, used_count: number }>>}
 */
export async function listPopularPresets(baseUrl) {
  let response;
  try {
    response = await fetch(`${baseUrl}/api/presets/popular`);
  } catch {
    throw new Error(
      `Could not reach the API at ${baseUrl}. Is the backend running (./scripts/run.sh)?`,
    );
  }

  if (!response.ok) {
    let detail = "Could not load popular presets.";
    try {
      const data = await response.json();
      if (data.detail) detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* ignore non-JSON error bodies */
    }
    throw new Error(detail);
  }

  const data = await response.json();
  return Array.isArray(data) ? data : [];
}

/**
 * POST a download/use event to /api/presets/use (increments popular.used_count).
 * @param {string} baseUrl - API origin, e.g. http://localhost:8000
 * @param {string} presetName - DB preset_name
 * @returns {Promise<{ preset_id: number, used_count: number }>}
 */
export async function recordPresetUse(baseUrl, presetName) {
  const name = String(presetName || "").trim();
  if (!name) {
    throw new Error("preset_name is required");
  }

  const form = new URLSearchParams();
  form.set("preset_name", name);

  let response;
  try {
    // urlencoded body is a "simple" CORS request (no preflight). Do not use
    // keepalive: browsers can drop cross-origin keepalive POSTs.
    response = await fetch(`${baseUrl}/api/presets/use`, {
      method: "POST",
      body: form,
    });
  } catch {
    throw new Error(
      `Could not reach the API at ${baseUrl}. Is the backend running (./scripts/run.sh)?`,
    );
  }

  if (!response.ok) {
    let detail = "Could not record preset use.";
    try {
      const data = await response.json();
      if (data.detail) detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* ignore non-JSON error bodies */
    }
    throw new Error(detail);
  }

  return response.json();
}

/**
 * POST preset name + image (+ optional text) to /api/apply-preset and return the result as a Blob.
 * @param {string} baseUrl - API origin, e.g. http://localhost:8000
 * @param {string} presetName - DB preset_name
 * @param {File} file - Image file selected by the user
 * @param {string} [text] - User text for presets with text_input=yes
 * @returns {Promise<Blob>}
 */
export async function applyPreset(baseUrl, presetName, file, text) {
  const form = new FormData();
  form.append("preset_name", presetName);
  // Always send text for text-input presets (including "" for a blank caption).
  if (typeof text === "string") {
    form.append("text", text);
  }
  // File last — more reliable for some multipart parsers.
  form.append("file", file);

  let response;
  try {
    response = await fetch(`${baseUrl}/api/apply-preset`, {
      method: "POST",
      body: form,
    });
  } catch {
    throw new Error(
      `Could not reach the API at ${baseUrl}. Is the backend running (./scripts/run.sh)?`,
    );
  }

  if (!response.ok) {
    let detail = "Apply-preset request failed.";
    try {
      const data = await response.json();
      if (data.detail) detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* ignore non-JSON error bodies */
    }
    throw new Error(detail);
  }

  return response.blob();
}
