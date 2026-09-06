function errorMessages(data: unknown, field = ""): string[] {
  if (typeof data === "string") return data.trim() ? [field ? `${field.replaceAll("_", " ")}: ${data}` : data] : [];
  if (Array.isArray(data)) return data.flatMap((value) => errorMessages(value, field));
  if (data && typeof data === "object")
    return Object.entries(data).flatMap(([key, value]) =>
      errorMessages(
        value,
        ["detail", "non_field_errors", "__all__"].includes(key) ? field : field ? `${field}.${key}` : key,
      ),
    );
  return [];
}

export class ApiError extends Error {
  status: number;
  data: unknown;

  constructor(status: number, data: unknown) {
    super(errorMessages(data).join("; ") || `Request failed (${status})`);
    this.status = status;
    this.data = data;
  }
}

function cookie(name: string) {
  if (typeof document === "undefined") return "";
  return (
    document.cookie
      .split("; ")
      .find((entry) => entry.startsWith(`${name}=`))
      ?.split("=")[1] ?? ""
  );
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
  if (!(init.body instanceof FormData) && init.body && !headers.has("Content-Type"))
    headers.set("Content-Type", "application/json");
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

// Selectors need every page, unlike registers which display one page at a time.
export async function apiAll<T>(path: string): Promise<T[]> {
  const url = new URL(path, "http://local.invalid");
  url.searchParams.set("page_size", "200");
  const rows: T[] = [];
  for (let page = 1; ; page++) {
    url.searchParams.set("page", String(page));
    const data = await api<T[] | { results: T[]; next: string | null }>(`${url.pathname}${url.search}`);
    rows.push(...listResults(data));
    if (Array.isArray(data) || !data.next) return rows;
  }
}

export const money = (value: number | string | null | undefined) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(
    Number(value ?? 0),
  );

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
