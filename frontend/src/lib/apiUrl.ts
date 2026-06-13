/** Backend API base URL (browser + SSR). Empty string = same-origin /api via Next rewrite. */
export function apiUrl(): string {
  const env = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (env) {
    return env.replace(/\/$/, "");
  }
  if (typeof window !== "undefined") {
    // Same host as the page — Next.js rewrites /api/* to the backend container.
    return "";
  }
  return process.env.API_PROXY_TARGET?.replace(/\/$/, "") || "http://127.0.0.1:8000";
}
