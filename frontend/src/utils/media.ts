const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:6200/api/v1";
const SERVER_ORIGIN = (() => {
  try { return new URL(API_BASE_URL).origin; } catch { return API_BASE_URL; }
})();
const IMAGE_EXTENSION_PATTERN = /\.(png|jpe?g|gif|webp|bmp)$/i;

export function resolveAssetUrl(sourceUrl: string | null | undefined) {
  if (!sourceUrl) {
    return "";
  }
  if (/^(https?:|data:|blob:)/i.test(sourceUrl)) {
    return sourceUrl;
  }
  return new URL(sourceUrl, SERVER_ORIGIN).toString();
}

export function isImageSource({
  sourceType,
  sourceUrl,
  fileName,
}: {
  sourceType?: string | null;
  sourceUrl?: string | null;
  fileName?: string | null;
}) {
  if (sourceType === "image") {
    return true;
  }
  return IMAGE_EXTENSION_PATTERN.test(fileName ?? sourceUrl ?? "");
}
