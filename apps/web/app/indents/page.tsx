"use client";

import { FormEvent, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api, listResults } from "@/lib/api";
import type { Client, Indent, Paginated } from "@/lib/types";
import { DateText, Empty, ErrorNotice, Loading, PageHeader, Pagination, StatusBadge } from "@/components/UI";

const nowLocal = () => {
  const current = new Date();
  return new Date(current.getTime() - current.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};

type ImportRow = { row_no: number; valid: boolean; errors: string[]; warnings: string[]; normalized: Partial<Indent> };
type Preview = {
  job_id: number;
  row_count: number;
  valid_count: number;
  error_count: number;
  duplicate_count: number;
  rows: ImportRow[];
};

const blankForm = {
  client: "",
  origin: "Sonipat",
  challan_no: "",
  challan_datetime: nowLocal(),
  ship_to_party_code: "",
  ship_to_party_name: "",
  ship_to_address: "",
  destination: "",
  destination_state: "",
  pin_code: "",
  item: "",
  default_quantity: "",
  quantity_ltrs: "",
  reporting_datetime: "",
  expected_delivery_date: "",
  branch: "Sonipat",
  cost_center: "",
  required_vehicle_type: "",
  notes: "",
  status: "OPEN",
};

export default function IndentsPage() {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [assigned, setAssigned] = useState("");
  const [clientFilter, setClientFilter] = useState("");
  const [branch, setBranch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);
  const pageSize = 25;
  const indents = useQuery({
    queryKey: ["indents", search, status, assigned, clientFilter, branch, dateFrom, dateTo, page],
    queryFn: () =>
      api<Paginated<Indent>>(
        `/indents/?page=${page}&page_size=${pageSize}&search=${encodeURIComponent(search)}&status=${status}&assigned=${assigned}&client=${clientFilter}&branch=${encodeURIComponent(branch)}&date_from=${dateFrom}&date_to=${dateTo}`,
      ),
  });
  const clients = useQuery({ queryKey: ["clients"], queryFn: () => api<Paginated<Client>>("/clients/?page_size=200") });
  const clientRows = clients.data ? listResults(clients.data) : [];
  const defaultClient = String(clientRows[0]?.id ?? "");
  const [open, setOpen] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [error, setError] = useState<unknown>();
  const [form, setForm] = useState(blankForm);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [importClient, setImportClient] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [allowPartial, setAllowPartial] = useState(false);
  const [importResult, setImportResult] = useState<{ created_indent_ids: number[]; skipped: unknown[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const rows = useMemo(() => (indents.data ? listResults(indents.data) : []), [indents.data]);

  const change = (key: string, value: string) => setForm((current) => ({ ...current, [key]: value }));
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      await api(editingId ? `/indents/${editingId}/` : "/indents/", {
        method: editingId ? "PATCH" : "POST",
        body: JSON.stringify({
          ...form,
          client: Number(form.client || defaultClient),
          indent_no: form.challan_no,
          indent_date: form.challan_datetime.slice(0, 10),
          challan_datetime: form.challan_datetime,
          reporting_datetime: form.reporting_datetime || null,
          expected_delivery_date: form.expected_delivery_date || null,
          default_quantity: form.default_quantity || null,
          quantity_ltrs: form.quantity_ltrs || null,
          quantity: form.default_quantity || null,
          total_load: form.quantity_ltrs || null,
          uom_ltrs: "LTR",
        }),
      });
      setForm({ ...blankForm, client: form.client || defaultClient, challan_datetime: nowLocal() });
      setEditingId(null);
      setOpen(false);
      await indents.refetch();
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(false);
    }
  };
  const editIndent = (row: Indent) => {
    setEditingId(row.id);
    setOpen(true);
    setForm({
      client: String(row.client),
      origin: row.origin,
      challan_no: row.challan_no || row.indent_no,
      challan_datetime: (row.challan_datetime || `${row.indent_date}T00:00`).slice(0, 16),
      ship_to_party_code: row.ship_to_party_code || "",
      ship_to_party_name: row.ship_to_party_name || "",
      ship_to_address: row.ship_to_address || "",
      destination: row.destination,
      destination_state: row.destination_state || "",
      pin_code: row.pin_code || "",
      item: row.item || "",
      default_quantity: row.default_quantity || "",
      quantity_ltrs: row.quantity_ltrs || "",
      reporting_datetime: row.reporting_datetime?.slice(0, 16) || "",
      expected_delivery_date: row.expected_delivery_date || "",
      branch: row.branch || "",
      cost_center: row.cost_center || "",
      required_vehicle_type: row.required_vehicle_type || "",
      notes: row.notes || "",
      status: row.status,
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  const previewUpload = async (event: FormEvent) => {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(undefined);
    setImportResult(null);
    const body = new FormData();
    body.append("file", file);
    body.append("client", importClient || defaultClient);
    try {
      setPreview(await api<Preview>("/imports/indents/preview/", { method: "POST", body }));
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(false);
    }
  };
  const confirmUpload = async () => {
    if (!preview) return;
    setBusy(true);
    setError(undefined);
    try {
      const response = await api<{ result: { created_indent_ids: number[]; skipped: unknown[] } }>(
        `/imports/indents/${preview.job_id}/confirm/`,
        { method: "POST", body: JSON.stringify({ allow_partial: allowPartial }) },
      );
      setImportResult(response.result);
      await indents.refetch();
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(false);
    }
  };
  const summary = useMemo(
    () => ({
      open: rows.filter((row) => row.status === "OPEN").length,
      unassigned: rows.filter((row) => row.trip_count === 0).length,
      linked: rows.filter((row) => row.trip_count > 0).length,
    }),
    [rows],
  );

  return (
    <>
      <PageHeader
        title="Indent register"
        description="Register client challans, import Excel records, and track every indent through one or more vehicle trips."
      >
        <button className="button" onClick={() => setShowImport((value) => !value)}>
          Upload Excel
        </button>
        <button className="button primary" onClick={() => setOpen((value) => !value)}>
          + Register indent
        </button>
      </PageHeader>
      <div className="summary-strip">
        <div>
          <span>Visible records</span>
          <strong>{rows.length}</strong>
        </div>
        <div>
          <span>Open</span>
          <strong>{summary.open}</strong>
        </div>
        <div>
          <span>Awaiting trip</span>
          <strong>{summary.unassigned}</strong>
        </div>
        <div>
          <span>Linked to trips</span>
          <strong>{summary.linked}</strong>
        </div>
      </div>
      {Boolean(error) && <ErrorNotice error={error} />}
      {open && (
        <form className="panel" onSubmit={submit}>
          <div className="panel-head">
            <h2>{editingId ? "Edit indent" : "Register indent"}</h2>
            <span className="eyebrow">Challan and consignee details</span>
          </div>
          <div className="panel-body form-grid">
            <div className="field">
              <label>Client</label>
              <select
                required
                className="input"
                value={form.client || defaultClient}
                onChange={(e) => change("client", e.target.value)}
              >
                {clientRows.map((row) => (
                  <option value={row.id} key={row.id}>
                    {row.code} — {row.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>From</label>
              <input
                required
                className="input"
                value={form.origin}
                onChange={(e) => change("origin", e.target.value)}
              />
            </div>
            <div className="field">
              <label>Challan no.</label>
              <input
                aria-label="Challan no."
                required
                className="input"
                value={form.challan_no}
                onChange={(e) => change("challan_no", e.target.value)}
              />
            </div>
            <div className="field">
              <label>Challan date & time</label>
              <input
                aria-label="Challan date & time"
                required
                type="datetime-local"
                className="input"
                value={form.challan_datetime}
                onChange={(e) => change("challan_datetime", e.target.value)}
              />
            </div>
            <div className="field">
              <label>Ship-to party code</label>
              <input
                aria-label="Ship-to party code"
                required
                className="input"
                value={form.ship_to_party_code}
                onChange={(e) => change("ship_to_party_code", e.target.value)}
              />
            </div>
            <div className="field span-2">
              <label>Ship-to party name</label>
              <input
                required
                className="input"
                value={form.ship_to_party_name}
                onChange={(e) => change("ship_to_party_name", e.target.value)}
              />
            </div>
            <div className="field span-2">
              <label>Address</label>
              <textarea
                required
                className="input"
                value={form.ship_to_address}
                onChange={(e) => change("ship_to_address", e.target.value)}
              />
            </div>
            <div className="field">
              <label>To location</label>
              <input
                required
                className="input"
                value={form.destination}
                onChange={(e) => change("destination", e.target.value)}
              />
            </div>
            <div className="field">
              <label>To state</label>
              <input
                required
                className="input"
                value={form.destination_state}
                onChange={(e) => change("destination_state", e.target.value)}
              />
            </div>
            <div className="field">
              <label>PIN code</label>
              <input
                required
                inputMode="numeric"
                pattern="[0-9]+"
                className="input"
                value={form.pin_code}
                onChange={(e) => change("pin_code", e.target.value)}
              />
            </div>
            <div className="field">
              <label>Item</label>
              <input
                required
                className="input"
                value={form.item}
                onChange={(e) => change("item", e.target.value)}
                placeholder="e.g. 20 LTR"
              />
            </div>
            <div className="field">
              <label>Default quantity</label>
              <input
                required
                type="number"
                min="0"
                step=".001"
                className="input"
                value={form.default_quantity}
                onChange={(e) => change("default_quantity", e.target.value)}
              />
            </div>
            <div className="field">
              <label>Quantity (LTR)</label>
              <input
                aria-label="Quantity (LTR)"
                required
                type="number"
                min="0"
                step=".001"
                className="input"
                value={form.quantity_ltrs}
                onChange={(e) => change("quantity_ltrs", e.target.value)}
              />
            </div>
            <div className="field">
              <label>Reporting date & time</label>
              <input
                type="datetime-local"
                className="input"
                value={form.reporting_datetime}
                onChange={(e) => change("reporting_datetime", e.target.value)}
              />
            </div>
            <div className="field">
              <label>Expected delivery date</label>
              <input
                type="date"
                className="input"
                value={form.expected_delivery_date}
                onChange={(e) => change("expected_delivery_date", e.target.value)}
              />
            </div>
            <div className="field">
              <label>Branch</label>
              <input className="input" value={form.branch} onChange={(e) => change("branch", e.target.value)} />
            </div>
            <div className="field">
              <label>Cost center</label>
              <input
                className="input"
                value={form.cost_center}
                onChange={(e) => change("cost_center", e.target.value)}
              />
            </div>
            <div className="field">
              <label>Required vehicle type</label>
              <input
                className="input"
                value={form.required_vehicle_type}
                onChange={(e) => change("required_vehicle_type", e.target.value)}
              />
            </div>
            <div className="field span-2">
              <label>Notes</label>
              <textarea className="input" value={form.notes} onChange={(e) => change("notes", e.target.value)} />
            </div>
          </div>
          {editingId && (
            <div className="field">
              <label>Status</label>
              <select className="input" value={form.status} onChange={(e) => change("status", e.target.value)}>
                <option>OPEN</option>
                <option>DRAFT</option>
                <option>FULFILLED</option>
                <option>CANCELLED</option>
              </select>
            </div>
          )}
          <div className="panel-body actions" style={{ justifyContent: "flex-end" }}>
            <button
              type="button"
              className="button"
              onClick={() => {
                setOpen(false);
                setEditingId(null);
                setForm(blankForm);
              }}
            >
              Cancel
            </button>
            <button className="button primary" disabled={busy}>
              {busy ? "Saving…" : editingId ? "Save changes" : "Register indent"}
            </button>
          </div>
        </form>
      )}
      {showImport && (
        <section className="panel">
          <div className="panel-head">
            <h2>Excel indent upload</h2>
            <a className="button small" href="/api/imports/indents/template/">
              Download sample format
            </a>
          </div>
          <form className="panel-body form-grid" onSubmit={previewUpload}>
            <div className="field">
              <label>Client</label>
              <select
                required
                className="input"
                value={importClient || defaultClient}
                onChange={(e) => setImportClient(e.target.value)}
              >
                {clientRows.map((row) => (
                  <option value={row.id} key={row.id}>
                    {row.code} — {row.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="field span-2">
              <label>Completed indent workbook (.xlsx)</label>
              <input
                required
                type="file"
                accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                className="input"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </div>
            <div className="field">
              <label>&nbsp;</label>
              <button className="button primary" disabled={!file || busy}>
                {busy ? "Validating…" : "Preview upload"}
              </button>
            </div>
          </form>
          {preview && (
            <>
              <div className="summary-strip" style={{ margin: 0, borderLeft: 0, borderRight: 0 }}>
                <div>
                  <span>Rows</span>
                  <strong>{preview.row_count}</strong>
                </div>
                <div>
                  <span>Valid</span>
                  <strong>{preview.valid_count}</strong>
                </div>
                <div>
                  <span>Errors</span>
                  <strong>{preview.error_count}</strong>
                </div>
                <div>
                  <span>Existing challans</span>
                  <strong>{preview.duplicate_count}</strong>
                </div>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Row</th>
                      <th>Status</th>
                      <th>Challan / timestamp</th>
                      <th>Party / destination</th>
                      <th>Item</th>
                      <th className="money">Def qty</th>
                      <th className="money">Qty LTR</th>
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
                        <td>
                          <strong>{row.normalized.challan_no}</strong>
                          <div className="muted">
                            <DateText value={row.normalized.challan_datetime} />
                          </div>
                        </td>
                        <td>
                          {row.normalized.ship_to_party_name}
                          <div className="muted">
                            {row.normalized.destination}, {row.normalized.destination_state}
                          </div>
                        </td>
                        <td>{row.normalized.item}</td>
                        <td className="money">{row.normalized.default_quantity}</td>
                        <td className="money">{row.normalized.quantity_ltrs}</td>
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
              <div className="panel-body actions">
                <label className="field" style={{ flexDirection: "row", alignItems: "center" }}>
                  <input
                    type="checkbox"
                    className="checkbox"
                    checked={allowPartial}
                    onChange={(e) => setAllowPartial(e.target.checked)}
                  />{" "}
                  Import valid rows and skip error rows
                </label>
                <button
                  type="button"
                  className="button primary"
                  disabled={busy || Boolean(importResult)}
                  onClick={confirmUpload}
                >
                  {busy ? "Importing…" : "Confirm indent import"}
                </button>
              </div>
            </>
          )}
          {importResult && (
            <div className="notice">
              <strong>Import completed.</strong> Created {importResult.created_indent_ids.length} indent(s); skipped{" "}
              {importResult.skipped.length} row(s).
            </div>
          )}
        </section>
      )}
      <section className="panel">
        <div className="panel-body">
          <div className="filters">
            <div className="field span-2">
              <label>Search challan, party, route, PIN or item</label>
              <input
                className="input"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
                placeholder="Search indent records…"
              />
            </div>
            <div className="field">
              <label>Client</label>
              <select
                className="input"
                value={clientFilter}
                onChange={(e) => {
                  setClientFilter(e.target.value);
                  setPage(1);
                }}
              >
                <option value="">All clients</option>
                {clientRows.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Status</label>
              <select
                className="input"
                value={status}
                onChange={(e) => {
                  setStatus(e.target.value);
                  setPage(1);
                }}
              >
                <option value="">All</option>
                <option>OPEN</option>
                <option>DRAFT</option>
                <option>FULFILLED</option>
                <option>CANCELLED</option>
              </select>
            </div>
            <div className="field">
              <label>Trip assignment</label>
              <select
                className="input"
                value={assigned}
                onChange={(e) => {
                  setAssigned(e.target.value);
                  setPage(1);
                }}
              >
                <option value="">All</option>
                <option value="false">Awaiting trip</option>
                <option value="true">Assigned</option>
              </select>
            </div>
            <div className="field">
              <label>Branch</label>
              <input
                className="input"
                value={branch}
                onChange={(e) => {
                  setBranch(e.target.value);
                  setPage(1);
                }}
              />
            </div>
            <div className="field">
              <label>From</label>
              <input
                type="date"
                className="input"
                value={dateFrom}
                onChange={(e) => {
                  setDateFrom(e.target.value);
                  setPage(1);
                }}
              />
            </div>
            <div className="field">
              <label>To</label>
              <input
                type="date"
                className="input"
                value={dateTo}
                onChange={(e) => {
                  setDateTo(e.target.value);
                  setPage(1);
                }}
              />
            </div>
          </div>
        </div>
        {indents.isPending ? (
          <Loading />
        ) : indents.error ? (
          <ErrorNotice error={indents.error} />
        ) : rows.length === 0 ? (
          <Empty message="No indent records match the filters." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>From</th>
                  <th>Challan / timestamp</th>
                  <th>Ship-to code / party</th>
                  <th>Address</th>
                  <th>Destination</th>
                  <th>Item</th>
                  <th className="money">Def qty</th>
                  <th className="money">Qty LTR</th>
                  <th>Trip & payment tracking</th>
                  <th>Status / action</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td>{row.origin}</td>
                    <td>
                      <strong>{row.challan_no || row.indent_no}</strong>
                      <div className="muted">
                        <DateText value={row.challan_datetime || row.indent_date} />
                      </div>
                    </td>
                    <td>
                      {row.ship_to_party_code || "—"}
                      <div className="muted">{row.ship_to_party_name || "—"}</div>
                    </td>
                    <td style={{ minWidth: 220 }}>{row.ship_to_address || "—"}</td>
                    <td>
                      {row.destination}
                      <div className="muted">
                        {row.destination_state} {row.pin_code}
                      </div>
                    </td>
                    <td>{row.item || "—"}</td>
                    <td className="money">{row.default_quantity || "—"}</td>
                    <td className="money">{row.quantity_ltrs || "—"}</td>
                    <td>
                      {row.trip_count === 0 ? (
                        <>
                          <StatusBadge value="AWAITING TRIP" />
                          <div>
                            <Link className="button small" href={`/trips/new?indent=${row.id}`}>
                              Create trip
                            </Link>
                          </div>
                        </>
                      ) : (
                        <>
                          {row.trip_summaries.map((trip) => (
                            <div key={trip.id} style={{ marginBottom: 6 }}>
                              <Link href={`/trips/${trip.id}`}>
                                <strong>{trip.trip_no}</strong>
                              </Link>
                              <div className="muted">Payment: {trip.payment_state}</div>
                            </div>
                          ))}
                        </>
                      )}
                    </td>
                    <td>
                      <StatusBadge value={row.status} />
                      <div>
                        <button className="button small" onClick={() => editIndent(row)}>
                          Edit
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {indents.data && <Pagination count={indents.data.count} page={page} pageSize={pageSize} onPage={setPage} />}
      </section>
    </>
  );
}
