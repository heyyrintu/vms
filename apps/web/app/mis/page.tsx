"use client";

import { FormEvent, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, listResults } from "@/lib/api";
import type { Paginated, User, Vendor } from "@/lib/types";
import {
  DateText,
  DetailLink,
  Empty,
  ErrorNotice,
  Loading,
  Money,
  PageHeader,
  StatusBadge,
} from "@/components/UI";

type MISPayment = {
  id: number;
  payment_no: string;
  payment_date: string;
  utr: string;
  gross: string;
  tds: string;
  net: string;
};

type MISRow = {
  id: number;
  trip_no: string;
  indent_no: string;
  client: string;
  deployment_date: string;
  created_at: string;
  route: string;
  vendor_id: number;
  vendor: string;
  vehicle_no: string;
  driver: string;
  freight_100: string;
  advance_percent: string;
  approved_gross: string;
  cash_paid: string;
  tds_paid: string;
  gross_accounted: string;
  approved_outstanding: string;
  total_remaining: string;
  trip_status: string;
  payment_status: string;
  payments: MISPayment[];
};

type MISResponse = {
  count: number;
  page: number;
  page_size: number;
  summary: {
    record_count: number;
    freight_100: string;
    approved_gross: string;
    cash_paid: string;
    tds_paid: string;
    gross_accounted: string;
    approved_outstanding: string;
    total_remaining: string;
  };
  rows: MISRow[];
};

type PreviewRow = {
  row_no: number;
  valid: boolean;
  errors: string[];
  warnings: string[];
  normalized: {
    record_ref: string;
    trip_no: string;
    deployment_date: string;
    vendor_name: string;
    vehicle_registration: string;
    gross_approved: string;
    tds_paid: string;
    net_paid: string;
    payment_date: string;
    utr: string;
  };
};

type Preview = {
  job_id: number;
  status: string;
  row_count: number;
  valid_count: number;
  error_count: number;
  rows: PreviewRow[];
};

type ImportResult = {
  created_trip_ids: number[];
  reused_trip_ids: number[];
  approval_ids: number[];
  payment_ids: number[];
  skipped: unknown[];
};

type ImportHistory = {
  id: number;
  filename: string;
  status: string;
  row_count: number;
  valid_count: number;
  error_count: number;
  uploaded_by: string;
  created_at: string;
  confirmed_at?: string;
  result: Partial<ImportResult>;
};

const tripStatuses = [
  "READY",
  "ADVANCE_APPROVAL_PENDING",
  "ADVANCE_APPROVED",
  "ADVANCE_PARTIALLY_PAID",
  "ADVANCE_PAID",
  "DEPLOYED",
  "IN_TRANSIT",
  "DELIVERED",
  "SETTLEMENT_PENDING",
  "SETTLED",
  "CANCELLED",
];

export default function MISPage() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState({ q: "", date_from: "", date_to: "", vendor: "", status: "", payment_status: "" });
  const [applied, setApplied] = useState(filters);
  const [page, setPage] = useState(1);
  const [showUpload, setShowUpload] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [createMissing, setCreateMissing] = useState(true);
  const [allowPartial, setAllowPartial] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uploadError, setUploadError] = useState<unknown>();

  const me = useQuery({ queryKey: ["me"], queryFn: () => api<User>("/auth/me/") });
  const vendors = useQuery({ queryKey: ["vendors", "mis-filter"], queryFn: () => api<Paginated<Vendor>>("/vendors/?page_size=200") });
  const params = useMemo(() => {
    const value = new URLSearchParams({ page: String(page), page_size: "50" });
    Object.entries(applied).forEach(([key, item]) => item && value.set(key, item));
    return value.toString();
  }, [applied, page]);
  const register = useQuery({
    queryKey: ["mis-records", params],
    queryFn: () => api<MISResponse>(`/mis/records/?${params}`),
  });
  const history = useQuery({
    queryKey: ["mis-import-history"],
    queryFn: () => api<ImportHistory[]>("/mis/imports/"),
    enabled: showUpload,
  });
  const exportParams = useMemo(() => {
    const value = new URLSearchParams({ format: "xlsx" });
    Object.entries(applied).forEach(([key, item]) => item && value.set(key, item));
    return value.toString();
  }, [applied]);

  const applyFilters = (event: FormEvent) => {
    event.preventDefault();
    setPage(1);
    setApplied(filters);
  };
  const clearFilters = () => {
    const empty = { q: "", date_from: "", date_to: "", vendor: "", status: "", payment_status: "" };
    setFilters(empty);
    setApplied(empty);
    setPage(1);
  };
  const previewUpload = async (event: FormEvent) => {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setUploadError(undefined);
    setImportResult(null);
    const body = new FormData();
    body.append("file", file);
    try {
      setPreview(await api<Preview>("/mis/import/preview/", { method: "POST", body }));
    } catch (error) {
      setUploadError(error);
    } finally {
      setBusy(false);
    }
  };
  const confirmUpload = async () => {
    if (!preview) return;
    setBusy(true);
    setUploadError(undefined);
    try {
      const response = await api<{ result: ImportResult }>(`/mis/import/${preview.job_id}/confirm/`, {
        method: "POST",
        body: JSON.stringify({ create_missing: createMissing, allow_partial: allowPartial }),
      });
      setImportResult(response.result);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["mis-records"] }),
        queryClient.invalidateQueries({ queryKey: ["mis-import-history"] }),
        queryClient.invalidateQueries({ queryKey: ["trips"] }),
        queryClient.invalidateQueries({ queryKey: ["payments"] }),
      ]);
    } catch (error) {
      setUploadError(error);
    } finally {
      setBusy(false);
    }
  };

  const summary = register.data?.summary;
  const pageCount = register.data ? Math.max(1, Math.ceil(register.data.count / register.data.page_size)) : 1;
  const admin = me.data?.role === "ADMIN";

  return <>
    <PageHeader
      title="MIS & historical records"
      description="One searchable record of past trips, approvals, TDS, cash payments, UTRs and balances."
    >
      <a className="button" href={`/api/mis/records/?${exportParams}`}>Export current view</a>
      <a className="button" href="/api/mis/template/">Download upload template</a>
      {admin && <button className="button primary" onClick={() => setShowUpload((value) => !value)}>{showUpload ? "Close upload" : "+ Upload records"}</button>}
    </PageHeader>

    {summary && <div className="mis-summary-grid">
      <div className="card stat"><div className="stat-label">Records</div><div className="stat-value">{summary.record_count}</div><div className="stat-note">Matching the active filters</div></div>
      <div className="card stat"><div className="stat-label">100% vendor amount</div><div className="stat-value"><Money value={summary.freight_100} /></div><div className="stat-note">Original freight liability</div></div>
      <div className="card stat"><div className="stat-label">Cash paid</div><div className="stat-value"><Money value={summary.cash_paid} /></div><div className="stat-note">Bank payments posted</div></div>
      <div className="card stat"><div className="stat-label">TDS deducted</div><div className="stat-value"><Money value={summary.tds_paid} /></div><div className="stat-note">Posted withholding</div></div>
      <div className="card stat"><div className="stat-label">Approved outstanding</div><div className="stat-value"><Money value={summary.approved_outstanding} /></div><div className="stat-note">Approved but not accounted</div></div>
      <div className="card stat"><div className="stat-label">Total remaining</div><div className="stat-value"><Money value={summary.total_remaining} /></div><div className="stat-note">Against final/100% vendor liability</div></div>
    </div>}

    {showUpload && admin && <section className="panel">
      <div className="panel-head"><h2>Post historical records</h2><span className="eyebrow">Admin controlled · audited</span></div>
      <div className="panel-body">
        <div className="notice">Use the downloaded template. The system previews every row before it creates trips, approved ledger items, grouped payments, allocations and TDS entries. Historical imports do not send old email or WhatsApp notifications.</div>
        <form onSubmit={previewUpload} className="form-grid">
          <div className="field span-2"><label htmlFor="mis-history-file">MIS history workbook (.xlsx, maximum 15 MB)</label><input id="mis-history-file" className="input" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(event) => { setFile(event.target.files?.[0] ?? null); setPreview(null); setImportResult(null); }} /></div>
          <div className="field"><label>&nbsp;</label><button className="button primary" disabled={!file || busy}>{busy ? "Checking records…" : "Preview upload"}</button></div>
        </form>
        {uploadError ? <ErrorNotice error={uploadError} /> : null}
        {importResult && <div className="notice"><strong>Import posted.</strong> Created {importResult.created_trip_ids.length} trip(s), reused {importResult.reused_trip_ids.length}, created {importResult.payment_ids.length} payment(s), and skipped {importResult.skipped.length} row(s).</div>}
      </div>
      {preview && <>
        <div className="summary-strip" style={{ margin: "0 18px 18px" }}><div><span>Import job</span><strong>#{preview.job_id}</strong></div><div><span>Total rows</span><strong>{preview.row_count}</strong></div><div><span>Valid</span><strong>{preview.valid_count}</strong></div><div><span>Errors</span><strong>{preview.error_count}</strong></div></div>
        <div className="table-wrap"><table><thead><tr><th>Row / ref</th><th>Trip / date</th><th>Transporter / vehicle</th><th className="money">Approved</th><th className="money">TDS paid</th><th className="money">Net paid</th><th>Payment reference</th><th>Validation</th></tr></thead><tbody>{preview.rows.slice(0, 200).map((row) => <tr key={row.row_no}><td>{row.row_no}<div className="muted">{row.normalized.record_ref || "—"}</div></td><td>{row.normalized.trip_no || "New trip"}<div className="muted"><DateText value={row.normalized.deployment_date} /></div></td><td>{row.normalized.vendor_name}<div className="muted">{row.normalized.vehicle_registration}</div></td><td className="money"><Money value={row.normalized.gross_approved} /></td><td className="money"><Money value={row.normalized.tds_paid} /></td><td className="money"><Money value={row.normalized.net_paid} /></td><td>{row.normalized.utr || "—"}<div className="muted"><DateText value={row.normalized.payment_date} /></div></td><td><StatusBadge value={row.valid ? "VALID" : "ERROR"} />{row.errors.map((message) => <div className="validation-error" key={message}>{message}</div>)}{row.warnings.map((message) => <div className="validation-warning" key={message}>{message}</div>)}</td></tr>)}</tbody></table></div>
        <div className="panel-body import-confirm-bar">
          <label><input type="checkbox" className="checkbox" checked={createMissing} onChange={(event) => setCreateMissing(event.target.checked)} /> Create missing transporters, vehicles and drivers</label>
          <label><input type="checkbox" className="checkbox" checked={allowPartial} onChange={(event) => setAllowPartial(event.target.checked)} /> Import valid rows only</label>
          <button className="button primary" disabled={busy || Boolean(importResult) || (preview.error_count > 0 && !allowPartial)} onClick={confirmUpload}>{busy ? "Posting history…" : "Confirm and post records"}</button>
        </div>
      </>}
      {history.data && history.data.length > 0 && <div className="panel-body" style={{ borderTop: "1px solid var(--line)" }}><h2 style={{ fontSize: 14 }}>Recent MIS imports</h2><div className="table-wrap"><table><thead><tr><th>Job</th><th>File</th><th>Uploaded</th><th>Rows</th><th>Result</th><th>Status</th></tr></thead><tbody>{history.data.map((job) => <tr key={job.id}><td>#{job.id}</td><td>{job.filename}<div className="muted">{job.uploaded_by}</div></td><td><DateText value={job.confirmed_at || job.created_at} /></td><td>{job.row_count}<div className="muted">{job.valid_count} valid · {job.error_count} errors</div></td><td>{job.result.created_trip_ids?.length ?? 0} trips · {job.result.payment_ids?.length ?? 0} payments</td><td><StatusBadge value={job.status} /></td></tr>)}</tbody></table></div></div>}
    </section>}

    <form className="panel" onSubmit={applyFilters}>
      <div className="panel-head"><h2>Search and reconcile</h2><button className="button small" type="button" onClick={clearFilters}>Clear filters</button></div>
      <div className="panel-body filters mis-filters">
        <div className="field span-2"><label>Trip, indent, route, vendor, vehicle or UTR</label><input className="input" placeholder="Search historical records…" value={filters.q} onChange={(event) => setFilters({ ...filters, q: event.target.value })} /></div>
        <div className="field"><label>From date</label><input className="input" type="date" value={filters.date_from} onChange={(event) => setFilters({ ...filters, date_from: event.target.value })} /></div>
        <div className="field"><label>To date</label><input className="input" type="date" value={filters.date_to} onChange={(event) => setFilters({ ...filters, date_to: event.target.value })} /></div>
        <div className="field"><label>Transporter</label><select className="input" value={filters.vendor} onChange={(event) => setFilters({ ...filters, vendor: event.target.value })}><option value="">All transporters</option>{vendors.data && listResults(vendors.data).map((vendor) => <option value={vendor.id} key={vendor.id}>{vendor.display_name}</option>)}</select></div>
        <div className="field"><label>Trip status</label><select className="input" value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })}><option value="">All trip statuses</option>{tripStatuses.map((status) => <option key={status}>{status}</option>)}</select></div>
        <div className="field"><label>Payment status</label><select className="input" value={filters.payment_status} onChange={(event) => setFilters({ ...filters, payment_status: event.target.value })}><option value="">All payment statuses</option><option>UNPAID</option><option>PARTIAL</option><option>PAID</option></select></div>
        <div className="field"><label>&nbsp;</label><button className="button primary">Apply filters</button></div>
      </div>
    </form>

    <section className="panel">
      <div className="panel-head"><h2>Trip and payment history</h2><span className="eyebrow">{register.data?.count ?? 0} matching records</span></div>
      {register.isPending ? <Loading /> : register.error ? <ErrorNotice error={register.error} /> : !register.data?.rows.length ? <Empty message="No MIS records match the active filters." /> : <div className="table-wrap"><table><thead><tr><th>Trip / indent</th><th>Deployment / created</th><th>Route</th><th>Transporter</th><th>Vehicle / driver</th><th className="money">100% amount</th><th className="money">Approved</th><th className="money">Cash paid</th><th className="money">TDS</th><th className="money">Approved balance</th><th className="money">Total remaining</th><th>Payments / UTR</th><th>Status</th></tr></thead><tbody>{register.data.rows.map((row) => <tr key={row.id}><td><DetailLink href={`/trips/${row.id}`}>{row.trip_no}</DetailLink><div className="muted">{row.indent_no}</div></td><td><DateText value={row.deployment_date} /><div className="muted"><DateText value={row.created_at} /></div></td><td>{row.route}</td><td>{row.vendor}</td><td>{row.vehicle_no}<div className="muted">{row.driver}</div></td><td className="money"><Money value={row.freight_100} /><div className="muted">Advance {row.advance_percent}%</div></td><td className="money"><Money value={row.approved_gross} /></td><td className="money"><strong><Money value={row.cash_paid} /></strong></td><td className="money"><Money value={row.tds_paid} /></td><td className="money"><Money value={row.approved_outstanding} /></td><td className="money"><strong><Money value={row.total_remaining} /></strong></td><td>{row.payments.length ? row.payments.map((payment) => <div className="payment-ref" key={payment.id}><DetailLink href={`/payments/${payment.id}`}>{payment.payment_no}</DetailLink><span>{payment.utr}</span><small><DateText value={payment.payment_date} /> · <Money value={payment.net} /></small></div>) : "—"}</td><td><StatusBadge value={row.payment_status} /><div style={{ marginTop: 5 }}><StatusBadge value={row.trip_status} /></div></td></tr>)}</tbody></table></div>}
      {register.data && register.data.count > register.data.page_size && <div className="pagination"><button className="button small" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>Previous</button><span>Page {page} of {pageCount}</span><button className="button small" disabled={page >= pageCount} onClick={() => setPage((value) => value + 1)}>Next</button></div>}
    </section>
  </>;
}
