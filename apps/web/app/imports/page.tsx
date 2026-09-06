"use client";

import { FormEvent, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, listResults } from "@/lib/api";
import type { Client, Paginated } from "@/lib/types";
import { ErrorNotice, Money, PageHeader, StatusBadge } from "@/components/UI";

type PreviewRow = {
  row_no: number;
  valid: boolean;
  errors: string[];
  warnings: string[];
  normalized: {
    origin: string;
    destination: string;
    deployment_date: string;
    vendor: string;
    vehicle_registration: string;
    vendor_freight_rate: string;
    unloading: string;
    calculated_advance: string;
    calculated_total: string;
    expected_delivery_date: string;
  };
};
type Preview = {
  job_id: number;
  row_count: number;
  valid_count: number;
  error_count: number;
  columns: string[];
  rows: PreviewRow[];
};

export default function ExcelImportPage() {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const clients = useQuery({ queryKey: ["clients"], queryFn: () => api<Paginated<Client>>("/clients/") });
  const [client, setClient] = useState("");
  const [createMissing, setCreateMissing] = useState(true);
  const [allowPartial, setAllowPartial] = useState(false);
  const [result, setResult] = useState<{ created_trip_ids: number[]; skipped: unknown[] } | null>(null);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(undefined);
    const body = new FormData();
    body.append("file", file);
    try {
      setPreview(await api<Preview>("/imports/excel/preview/", { method: "POST", body }));
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(false);
    }
  };
  const confirm = async () => {
    if (!preview) return;
    setBusy(true);
    setError(undefined);
    try {
      const response = await api<{ result: { created_trip_ids: number[]; skipped: unknown[] } }>(
        `/imports/excel/${preview.job_id}/confirm/`,
        {
          method: "POST",
          body: JSON.stringify({
            client: Number(client || (clients.data && listResults(clients.data)[0]?.id)),
            create_missing: createMissing,
            allow_partial: allowPartial,
          }),
        },
      );
      setResult(response.result);
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <PageHeader
        title="Legacy Excel import"
        description="Validate and normalize the exact 17-column payment sheet, then atomically create reviewed trips."
      >
        <a className="button" href="/api/imports/excel/export/">
          Download transition export
        </a>
      </PageHeader>
      <div className="notice">
        Preview handles Excel serial dates, formula/cached-value differences, normalized vehicle registrations and
        duplicate warnings. No row is silently merged.
      </div>
      <form className="panel" onSubmit={submit}>
        <div className="panel-head">
          <h2>Upload workbook</h2>
          <span className="eyebrow">.xlsx · max 10 MB</span>
        </div>
        <div className="panel-body">
          <div className="field">
            <label>Legacy payment approval sheet</label>
            <input
              className="input"
              type="file"
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              required
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>
          <button className="button primary" disabled={!file || busy} style={{ marginTop: 12 }}>
            {busy ? "Inspecting workbook…" : "Generate normalized preview"}
          </button>
        </div>
      </form>
      {Boolean(error) && <ErrorNotice error={error} />}
      {result && (
        <div className="notice">
          <strong>Import completed.</strong> Created {result.created_trip_ids.length} trip(s); skipped{" "}
          {result.skipped.length} row(s).
        </div>
      )}
      {preview && (
        <>
          <div className="summary-strip">
            <div>
              <span>Import job</span>
              <strong>#{preview.job_id}</strong>
            </div>
            <div>
              <span>Total rows</span>
              <strong>{preview.row_count}</strong>
            </div>
            <div>
              <span>Valid rows</span>
              <strong>{preview.valid_count}</strong>
            </div>
            <div>
              <span>Error rows</span>
              <strong>{preview.error_count}</strong>
            </div>
          </div>
          <section className="panel">
            <div className="panel-head">
              <h2>Normalized preview</h2>
              <span className="muted">Review required before confirmation</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Row</th>
                    <th>Status</th>
                    <th>Date</th>
                    <th>Route</th>
                    <th>Transporter</th>
                    <th>Vehicle</th>
                    <th className="money">Rate</th>
                    <th className="money">90% advance</th>
                    <th className="money">Unloading</th>
                    <th className="money">Gross</th>
                    <th>Issues</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.map((row) => (
                    <tr key={row.row_no}>
                      <td>{row.row_no}</td>
                      <td>
                        <StatusBadge value={row.valid ? "VALID" : "ERROR"} />
                      </td>
                      <td>{row.normalized.deployment_date}</td>
                      <td>
                        {row.normalized.origin} → {row.normalized.destination}
                      </td>
                      <td>{row.normalized.vendor}</td>
                      <td>{row.normalized.vehicle_registration}</td>
                      <td className="money">
                        <Money value={row.normalized.vendor_freight_rate} />
                      </td>
                      <td className="money">
                        <Money value={row.normalized.calculated_advance} />
                      </td>
                      <td className="money">
                        <Money value={row.normalized.unloading} />
                      </td>
                      <td className="money">
                        <Money value={row.normalized.calculated_total} />
                      </td>
                      <td>
                        {row.errors.map((item) => (
                          <div style={{ color: "var(--red)" }} key={item}>
                            {item}
                          </div>
                        ))}
                        {row.warnings.map((item) => (
                          <div style={{ color: "#89581b" }} key={item}>
                            {item}
                          </div>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="panel-body form-grid">
              <div className="field span-2">
                <label>Client</label>
                <select className="input" value={client} onChange={(e) => setClient(e.target.value)}>
                  {clients.data &&
                    listResults(clients.data).map((row) => (
                      <option value={row.id} key={row.id}>
                        {row.code} — {row.name}
                      </option>
                    ))}
                </select>
              </div>
              <label className="field" style={{ flexDirection: "row", alignItems: "center" }}>
                <input
                  type="checkbox"
                  className="checkbox"
                  checked={createMissing}
                  onChange={(e) => setCreateMissing(e.target.checked)}
                />{" "}
                Create missing vendors, vehicles and drivers
              </label>
              <label className="field" style={{ flexDirection: "row", alignItems: "center" }}>
                <input
                  type="checkbox"
                  className="checkbox"
                  checked={allowPartial}
                  onChange={(e) => setAllowPartial(e.target.checked)}
                />{" "}
                Import valid rows only
              </label>
              <button className="button primary" disabled={busy || Boolean(result)} onClick={confirm}>
                {busy ? "Importing…" : "Confirm atomic import"}
              </button>
            </div>
          </section>
        </>
      )}
    </>
  );
}
