"use client";

import { useDeferredValue, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api } from "@/lib/api";

type Result = { type: string; id: number; label: string; detail: string };

export function GlobalSearch() {
  const [term, setTerm] = useState("");
  const deferred = useDeferredValue(term.trim());
  const search = useQuery({
    queryKey: ["global-search", deferred],
    queryFn: () => api<{ results: Result[] }>(`/search/?q=${encodeURIComponent(deferred)}`),
    enabled: deferred.length >= 2,
    staleTime: 10_000,
  });
  const href = (row: Result) =>
    row.type === "approval"
      ? `/approvals/${row.id}`
      : row.type === "payment"
        ? `/payments/${row.id}`
        : row.type === "vendor"
          ? `/vendors/${row.id}`
          : row.type === "trip"
            ? `/trips/${row.id}`
            : "/fleet";
  return (
    <div className="global-search">
      <input
        aria-label="Global search"
        className="input"
        value={term}
        onChange={(event) => setTerm(event.target.value)}
        placeholder="Search trip, vendor, UTR, approval…"
      />
      {deferred.length >= 2 && (
        <div className="search-results">
          {search.isPending ? (
            <div className="muted">Searching…</div>
          ) : search.data?.results.length ? (
            search.data.results.map((row) => (
              <Link href={href(row)} key={`${row.type}-${row.id}`} onClick={() => setTerm("")}>
                <strong>{row.label}</strong>
                <small>
                  {row.type} · {row.detail}
                </small>
              </Link>
            ))
          ) : (
            <div className="muted">No matching records</div>
          )}
        </div>
      )}
    </div>
  );
}
