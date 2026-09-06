"use client";

import { useMemo, useState } from "react";

// Shared filter + pagination state for register pages. `query` is the API query string.
export function useRegisterFilters<T extends Record<string, string>>(initial: T, pageSize = 25) {
  const [filters, setFilters] = useState<T>(initial);
  const [page, setPage] = useState(1);
  const set = (key: keyof T, value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setPage(1);
  };
  const query = useMemo(() => {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    Object.entries(filters).forEach(([key, value]) => value && params.set(key, value));
    return params.toString();
  }, [filters, page, pageSize]);
  return { filters, set, page, setPage, pageSize, query };
}
