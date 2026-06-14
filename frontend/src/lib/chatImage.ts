/** Client-side image prep for multimodal chat (resize + JPEG compress). */

const MAX_EDGE = 1536;
const JPEG_QUALITY = 0.82;
export const MAX_IMAGES = 4;

export type PendingImage = {
  id: string;
  dataUrl: string;
  name: string;
  isLoading?: boolean;
  error?: string;
};

function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("无法读取图片"));
    };
    img.src = url;
  });
}

export async function fileToChatDataUrl(file: File): Promise<string> {
  if (!file.type.startsWith("image/")) {
    throw new Error("仅支持图片文件");
  }
  const img = await loadImage(file);
  let { width, height } = img;
  const scale = Math.min(1, MAX_EDGE / Math.max(width, height));
  width = Math.max(1, Math.round(width * scale));
  height = Math.max(1, Math.round(height * scale));

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas 不可用");
  ctx.drawImage(img, 0, 0, width, height);

  const dataUrl = canvas.toDataURL("image/jpeg", JPEG_QUALITY);
  if (dataUrl.length > 6_000_000) {
    throw new Error("图片过大，请换一张或裁剪后重试");
  }
  return dataUrl;
}

/** Clipboard / drop — goose & construct-os pattern (items first, then files). */
export function extractImageFilesFromDataTransfer(data: DataTransfer | null): File[] {
  if (!data) return [];
  const fromItems = Array.from(data.items)
    .filter((it) => it.kind === "file" && it.type.startsWith("image/"))
    .map((it) => it.getAsFile())
    .filter((f): f is File => f !== null);
  if (fromItems.length) return fromItems;
  return Array.from(data.files).filter((f) => f.type.startsWith("image/"));
}

export async function filesToPendingImages(
  files: FileList | File[],
  existingCount = 0,
): Promise<PendingImage[]> {
  const list = Array.from(files).slice(0, MAX_IMAGES - existingCount);
  const out: PendingImage[] = [];
  for (const file of list) {
    const dataUrl = await fileToChatDataUrl(file);
    out.push({
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      dataUrl,
      name: file.name || "pasted-image.jpg",
    });
  }
  return out;
}

export function createPendingPlaceholders(count: number): PendingImage[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `loading-${Date.now()}-${i}`,
    dataUrl: "",
    name: "",
    isLoading: true,
  }));
}

export async function resolvePlaceholderImages(
  placeholders: PendingImage[],
  files: File[],
): Promise<PendingImage[]> {
  const resolved: PendingImage[] = [];
  for (let i = 0; i < placeholders.length; i++) {
    try {
      const dataUrl = await fileToChatDataUrl(files[i]);
      resolved.push({
        ...placeholders[i],
        dataUrl,
        name: files[i].name || "pasted-image.jpg",
        isLoading: false,
        error: undefined,
      });
    } catch (err) {
      resolved.push({
        ...placeholders[i],
        dataUrl: "",
        isLoading: false,
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }
  return resolved;
}
