/**
 * Small helpers for validating and previewing images in the browser.
 */

const ALLOWED_MIME = new Set([
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/gif",
  "image/bmp",
  "image/tiff",
  "image/heic",
  "image/heif",
]);

/**
 * @param {File} file
 * @returns {boolean}
 */
export function isImageFile(file) {
  if (!file) return false;
  if (file.type && ALLOWED_MIME.has(file.type)) return true;
  // Some browsers omit type; fall back to extension
  return /\.(jpe?g|png|webp|gif|bmp|tiff?|hei[cf])$/i.test(file.name);
}

/** @param {Blob|File} source */
export function createObjectUrl(source) {
  return URL.createObjectURL(source);
}

/** @param {string|null} url */
export function revokeObjectUrl(url) {
  if (url) URL.revokeObjectURL(url);
}
