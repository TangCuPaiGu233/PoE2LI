"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

type ChatMessageImageProps = {
  src: string;
  alt?: string;
  fileName?: string;
  className?: string;
  thumb?: boolean;
};

function dataUrlToBlobUrl(dataUrl: string): string | null {
  try {
    const [header, body] = dataUrl.split(",");
    if (!body) return null;
    const mime = header.match(/:(.*?);/)?.[1] || "image/jpeg";
    const binary = atob(body);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    return URL.createObjectURL(new Blob([bytes], { type: mime }));
  } catch {
    return null;
  }
}

async function fetchBlob(src: string): Promise<Blob> {
  const res = await fetch(src);
  return res.blob();
}

export default function ChatMessageImage({
  src,
  alt = "附件",
  fileName = "chat-image.jpg",
  className = "",
  thumb = false,
}: ChatMessageImageProps) {
  const blobUrl = useMemo(
    () => (src.startsWith("data:") ? dataUrlToBlobUrl(src) : null),
    [src],
  );
  const displaySrc = blobUrl || src;
  const [hint, setHint] = useState("");

  useEffect(() => {
    return () => {
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [blobUrl]);

  const flash = useCallback((msg: string) => {
    setHint(msg);
    window.setTimeout(() => setHint(""), 1800);
  }, []);

  const onCopy = useCallback(async () => {
    try {
      const blob = await fetchBlob(displaySrc);
      if (!navigator.clipboard?.write || typeof ClipboardItem === "undefined") {
        flash("浏览器不支持复制图片");
        return;
      }
      await navigator.clipboard.write([
        new ClipboardItem({ [blob.type || "image/png"]: blob }),
      ]);
      flash("已复制到剪贴板");
    } catch {
      flash("复制失败，请用下载");
    }
  }, [displaySrc, flash]);

  const onDownload = useCallback(() => {
    const a = document.createElement("a");
    a.href = displaySrc;
    a.download = fileName.replace(/[^\w\u4e00-\u9fff.-]+/g, "_") || "chat-image.jpg";
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
    flash("已开始下载");
  }, [displaySrc, fileName, flash]);

  const btnClass =
    "px-1.5 py-0.5 rounded text-[10px] bg-black/70 text-zinc-100 hover:bg-black/90 border border-white/10";

  return (
    <div
      className={`chat-message-image group relative inline-block max-w-full ${thumb ? "" : "align-top"}`}
      onContextMenu={(e) => e.stopPropagation()}
    >
      <img
        src={displaySrc}
        alt={alt}
        draggable
        className={`chat-message-image__img ${className}`}
      />
      <div
        className={`absolute left-1 bottom-1 flex flex-wrap gap-1 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity ${
          thumb ? "scale-90 origin-bottom-left" : ""
        }`}
      >
        <button type="button" className={btnClass} onClick={() => void onCopy()}>
          复制
        </button>
        <button type="button" className={btnClass} onClick={onDownload}>
          下载
        </button>
        <a
          href={displaySrc}
          target="_blank"
          rel="noopener noreferrer"
          className={btnClass}
          download={fileName}
        >
          打开
        </a>
      </div>
      {hint ? (
        <span className="absolute top-1 right-1 px-1.5 py-0.5 rounded text-[10px] bg-black/75 text-emerald-300 pointer-events-none">
          {hint}
        </span>
      ) : null}
    </div>
  );
}
