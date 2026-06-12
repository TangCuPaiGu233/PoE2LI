"use client";

import { apiUrl } from "@/lib/apiUrl";
import { useCallback, useEffect, useRef, useState } from "react";

export interface EntityTooltip {
  label: string;
  name_en: string;
  type: string;
  type_label?: string;
  rarity?: string | null;
  rarity_label?: string | null;
  description?: string;
  icon_url?: string | null;
  poe2db_url?: string | null;
}

const TYPE_BORDER: Record<string, string> = {
  item: "border-amber-500/55 bg-amber-950/20",
  skill: "border-emerald-500/55 bg-emerald-950/15",
  ascendancy: "border-purple-500/55 bg-purple-950/20",
};

const TYPE_BADGE: Record<string, string> = {
  item: "bg-amber-900/40 text-amber-200/80",
  skill: "bg-emerald-900/40 text-emerald-200/80",
  ascendancy: "bg-purple-900/40 text-purple-200/80",
};

interface PoeEntityChipProps {
  label: string;
  nameEn: string;
  entityType: string;
  initialIconUrl?: string | null;
}

export default function PoeEntityChip({ label, nameEn, entityType, initialIconUrl }: PoeEntityChipProps) {
  const [open, setOpen] = useState(false);
  const [tip, setTip] = useState<EntityTooltip | null>(null);
  const [loading, setLoading] = useState(false);
  const [iconVisible, setIconVisible] = useState(false);
  const fetched = useRef(false);
  const imgRef = useRef<HTMLImageElement>(null);
  const iconSrc = `${apiUrl()}/api/entities/icon-image?name=${encodeURIComponent(label || nameEn)}`;

  const border = TYPE_BORDER[entityType] ?? "border-zinc-600/50 bg-zinc-900/40";
  const badge = TYPE_BADGE[entityType] ?? "bg-zinc-800 text-zinc-300";

  const loadTip = useCallback(async () => {
    if (fetched.current) return;
    setLoading(true);
    try {
      const q = encodeURIComponent(label || nameEn);
      const res = await fetch(`${apiUrl()}/api/entities/tooltip?name=${q}&lang=cn`);
      if (res.ok) {
        const data = (await res.json()) as EntityTooltip;
        if (!data.icon_url && initialIconUrl) data.icon_url = initialIconUrl;
        setTip(data);
        fetched.current = true;
      } else if (initialIconUrl) {
        setTip({
          label,
          name_en: nameEn,
          type: entityType,
          icon_url: initialIconUrl,
        });
        fetched.current = true;
      }
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [label, nameEn, entityType, initialIconUrl]);

  useEffect(() => {
    setIconVisible(false);
    const img = imgRef.current;
    if (img?.complete && img.naturalWidth > 0) {
      setIconVisible(true);
    }
  }, [iconSrc]);

  return (
    <span
      className="entity-chip-wrap relative inline-block align-baseline mx-0.5"
      onMouseEnter={() => {
        setOpen(true);
        void loadTip();
      }}
      onMouseLeave={() => setOpen(false)}
      tabIndex={0}
    >
      <span
        className={`entity-chip inline-flex items-center gap-1 rounded border px-1 py-0.5 text-[0.92em] leading-tight text-zinc-100/90 ${border}`}
      >
        <span className="relative inline-flex h-6 w-6 shrink-0 items-center justify-center rounded bg-zinc-900/70 ring-1 ring-white/10">
          <img
          ref={imgRef}
          src={iconSrc}
          alt=""
          width={24}
          height={24}
          className={`h-6 w-6 object-contain transition-opacity ${iconVisible ? "opacity-100" : "opacity-0"}`}
          onLoad={() => setIconVisible(true)}
          onError={() => setIconVisible(false)}
        />
        </span>
        <span>{label}</span>
      </span>

      {open && (
        <span className="entity-popover pointer-events-none absolute bottom-full left-0 z-50 mb-2 block w-[min(18rem,80vw)] rounded-lg border border-zinc-700/80 bg-[#0d0f14] p-3 text-left shadow-2xl shadow-black/60">
          <span className="flex items-start gap-2.5">
            <span className="mt-0.5 inline-flex h-10 w-10 shrink-0 items-center justify-center rounded bg-zinc-900/70 ring-1 ring-white/10">
              <img src={iconSrc} alt="" className={`h-10 w-10 object-contain transition-opacity ${iconVisible ? "opacity-100" : "opacity-0"}`} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium text-zinc-100">{tip?.label ?? label}</span>
              <span className="block truncate text-xs text-zinc-500">{tip?.name_en ?? nameEn}</span>
              <span className={`mt-1 inline-block rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${badge}`}>
                {tip?.type_label ?? tip?.type ?? entityType}
                {tip?.rarity_label || tip?.rarity ? ` · ${tip?.rarity_label ?? tip?.rarity}` : ""}
              </span>
            </span>
          </span>
          <span className="mt-2 block text-xs leading-relaxed text-zinc-400">
            {loading && !tip ? "加载中…" : tip?.description || "暂无说明"}
          </span>
          {tip?.poe2db_url ? (
            <a
              href={tip.poe2db_url}
              target="_blank"
              rel="noreferrer"
              className="mt-2 inline-block text-xs text-amber-400/80 underline pointer-events-auto"
            >
              poe2db.tw
            </a>
          ) : null}
        </span>
      )}
    </span>
  );
}