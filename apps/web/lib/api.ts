export class ApiError extends Error {
  status: number;
  data: unknown;

  constructor(status: number, data: unknown) {
    super(typeof data === "object" && data && "detail" in data ? String((data as { detail: unknown }).detail) : `Request failed (${status})`);
    this.status = status;
    this.data = data;
  }
}

function cookie(name: string) {
  if (typeof document === "undefined") return "";
  return document.cookie.split("; ").find((entry) => entry.startsWith(`${name}=`))?.split("=")[1] ?? "";
}

async function csrfToken() {
  let token = decodeURIComponent(cookie("csrftoken"));
  if (!token) {
    const response = await fetch("/api/auth/csrf/", { credentials: "include" });
    const data = (await response.json()) as { csrfToken: string };
    token = data.csrfToken;
  }
  return token;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData) && init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) headers.set("X-CSRFToken", await csrfToken());
  const response = await fetch(path.startsWith("/api/") ? path : `/api${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, data);
  return data as T;
}

export function listResults<T>(value: T[] | { results: T[] }): T[] {
  return Array.isArray(value) ? value : value.results;
}

export const money = (value: number | string | null | undefined) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(Number(value ?? 0));

export const dateText = (value?: string | null) => {
  if (!value) return "—";
  const hasTime = /T\d{2}:\d{2}|\s\d{2}:\d{2}/.test(value);
  return new Intl.DateTimeFormat(
    "en-IN",
    hasTime
      ? { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }
      : { day: "2-digit", month: "short", year: "numeric" },
  ).format(new Date(value));
};
