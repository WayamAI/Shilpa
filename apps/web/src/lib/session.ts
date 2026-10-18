/**
 * Local dev session. The cookie holds the signed-in dev user's email; the API
 * receives it as a `dev:<email>` bearer token. In Azure this becomes Entra ID
 * and the cookie goes away. Shared by proxy.ts (server) and the client.
 */
export const SESSION_COOKIE = "shilpa-session";

export const DEV_USERS = [
  { email: "dev@wayam.local", name: "Dev Engineer", role: "Org admin" },
  { email: "viewer@wayam.local", name: "Read-only Viewer", role: "Project viewer" },
  { email: "other@example.com", name: "Other Tenant User", role: "Org admin (second tenant)" },
] as const;

export function readSession(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.split("; ").find((c) => c.startsWith(`${SESSION_COOKIE}=`));
  return match ? decodeURIComponent(match.split("=")[1]) : null;
}

export function writeSession(email: string) {
  document.cookie = `${SESSION_COOKIE}=${encodeURIComponent(email)}; path=/; max-age=86400; samesite=lax`;
}

export function clearSession() {
  document.cookie = `${SESSION_COOKIE}=; path=/; max-age=0; samesite=lax`;
}
