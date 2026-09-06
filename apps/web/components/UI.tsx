import Link from "next/link";
import { dateText, money } from "@/lib/api";

export function PageHeader({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {children && <div className="actions">{children}</div>}
    </div>
  );
}

export function StatusBadge({ value }: { value: string }) {
  const normalized = value.toUpperCase();
  const tone =
    normalized.includes("APPROVED") || normalized.includes("PAID") || normalized === "ACTIVE"
      ? "green"
      : normalized.includes("PENDING") || normalized.includes("DRAFT") || normalized.includes("PROCESSING")
        ? "amber"
        : normalized.includes("REJECT") ||
            normalized.includes("FAIL") ||
            normalized.includes("REVERSE") ||
            normalized.includes("CANCEL")
          ? "red"
          : "blue";
  return <span className={`badge ${tone}`}>{value.replaceAll("_", " ")}</span>;
}

export function Money({ value }: { value: string | number | null | undefined }) {
  return <span className="money">{money(value)}</span>;
}
export function DateText({ value }: { value?: string | null }) {
  return <>{dateText(value)}</>;
}
export function Empty({ message = "No records found." }: { message?: string }) {
  return <div className="empty">{message}</div>;
}
export function Loading() {
  return <div className="empty">Loading current data…</div>;
}
export function ErrorNotice({ error }: { error: unknown }) {
  return <div className="notice error">{error instanceof Error ? error.message : "Something went wrong."}</div>;
}
export function DetailLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} style={{ color: "var(--forest)", fontWeight: 750 }}>
      {children}
    </Link>
  );
}

export function Pagination({
  count,
  page,
  pageSize = 25,
  onPage,
}: {
  count: number;
  page: number;
  pageSize?: number;
  onPage: (page: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(count / pageSize));
  if (count <= pageSize) return null;
  return (
    <div className="pagination">
      <span>
        {count.toLocaleString("en-IN")} records · Page {page} of {pages}
      </span>
      <button className="button small" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        Previous
      </button>
      <button className="button small" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Next
      </button>
    </div>
  );
}
