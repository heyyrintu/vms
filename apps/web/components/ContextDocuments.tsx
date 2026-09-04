"use client";

import { FormEvent, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, listResults } from "@/lib/api";
import type { Paginated } from "@/lib/types";
import { DateText, Empty, ErrorNotice, StatusBadge } from "@/components/UI";

type Document = { id: number; kind: string; original_name: string; scan_status: string; download_url: string; created_at: string };

export function ContextDocuments({ objectType, objectId }: { objectType: "approval" | "payment"; objectId: string }) {
  const query = useQuery({ queryKey: ["documents", objectType, objectId], queryFn: () => api<Paginated<Document>>(`/documents/?object_type=${objectType}&object_id=${objectId}`) });
  const [file, setFile] = useState<File | null>(null); const [error, setError] = useState<unknown>();
  const upload = async (event: FormEvent) => { event.preventDefault(); if (!file) return; const body = new FormData(); body.append("file", file); body.append("kind", objectType === "payment" ? "PAYMENT_PROOF" : "OTHER"); body.append("object_type", objectType); body.append("object_id", objectId); try { await api("/documents/", { method: "POST", body }); setFile(null); await query.refetch(); } catch (reason) { setError(reason); } };
  const rows = query.data ? listResults(query.data) : [];
  return <section className="panel"><div className="panel-head"><h2>Attachments</h2><span className="eyebrow">Scanned</span></div>{Boolean(error) && <div className="panel-body"><ErrorNotice error={error} /></div>}{rows.length === 0 ? <Empty message="No attachments." /> : <div className="panel-body timeline">{rows.map((row) => <div className="timeline-item" key={row.id}><a href={row.download_url}><strong>{row.original_name}</strong></a><small><DateText value={row.created_at} /> · <StatusBadge value={row.scan_status} /></small></div>)}</div>}<form className="panel-body" onSubmit={upload}><div className="field"><label>PDF, PNG or JPEG</label><input required className="input" type="file" accept=".pdf,.png,.jpg,.jpeg" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></div><button className="button small" style={{ marginTop: 8 }}>Upload</button></form></section>;
}
