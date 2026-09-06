"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, listResults } from "@/lib/api";
import type { DocumentRecord, Paginated } from "@/lib/types";

// Loads a driver's KYC documents only when asked, so the fleet page never fetches every document.
export function DriverDocuments({ driverId }: { driverId: number }) {
  const [open, setOpen] = useState(false);
  const documents = useQuery({
    queryKey: ["documents", "driver", driverId],
    queryFn: async () => listResults(await api<Paginated<DocumentRecord>>(`/documents/?object_type=driver&object_id=${driverId}`)),
    enabled: open,
  });
  if (!open) return <button type="button" className="button small" onClick={() => setOpen(true)}>Show KYC</button>;
  if (documents.isPending) return <span className="muted">Loading…</span>;
  if (documents.error) return <span className="muted">Could not load documents</span>;
  if (!documents.data?.length) return <span className="muted">Not uploaded</span>;
  return (
    <>
      {documents.data.map((document) => (
        <a key={document.id} className="chip" href={document.download_url}>{document.kind.replaceAll("_", " ")}</a>
      ))}
    </>
  );
}
