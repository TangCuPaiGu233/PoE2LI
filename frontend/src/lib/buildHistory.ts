const STORAGE_KEY = "poe2li_build_history_v1";
const MAX_ENTRIES = 30;

export interface LocalBuildHistoryEntry {
  id: number;
  status: string;
  build: {
    className?: string;
    ascendClassName?: string;
    level?: string;
  };
  savedAt: string;
}

function readRaw(): LocalBuildHistoryEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeRaw(entries: LocalBuildHistoryEntry[]) {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(0, MAX_ENTRIES)));
}

export function getLocalBuildHistory(): LocalBuildHistoryEntry[] {
  return readRaw();
}

export function addLocalBuildHistory(entry: LocalBuildHistoryEntry) {
  const rest = readRaw().filter((e) => e.id !== entry.id);
  writeRaw([entry, ...rest]);
}

export function removeLocalBuildHistory(id: number) {
  writeRaw(readRaw().filter((e) => e.id !== id));
}

export function toHistorySummary(entry: LocalBuildHistoryEntry) {
  return {
    id: entry.id,
    status: entry.status,
    build: entry.build,
    created_at: entry.savedAt,
  };
}
