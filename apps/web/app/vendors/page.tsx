"use client";

import { FormEvent, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, listResults } from "@/lib/api";
import type { Paginated, Vendor } from "@/lib/types";
import { DetailLink, Empty, ErrorNotice, Loading, PageHeader, Pagination, StatusBadge } from "@/components/UI";

const emptyForm = {
  vendor_code: "", legal_name: "", display_name: "", email: "", primary_contact_name: "",
  primary_phone: "", status: "ACTIVE", bank_name: "", account_holder: "", account_number: "", ifsc_code: "",
};

async function uploadDocument(file: File, kind: string, objectType: string, objectId: number) {
  const body = new FormData();
  body.append("file", file); body.append("kind", kind); body.append("object_type", objectType); body.append("object_id", String(objectId));
  return api("/documents/", { method: "POST", body });
}

export default function VendorListPage() {
  const [search, setSearch] = useState(""); const [status, setStatus] = useState(""); const [page, setPage] = useState(1); const pageSize = 25;
  const vendors = useQuery({ queryKey: ["vendors", search, status, page], queryFn: () => api<Paginated<Vendor>>(`/vendors/?page=${page}&page_size=${pageSize}&search=${encodeURIComponent(search)}&status=${status}`) });
  const [adding, setAdding] = useState(false); const [busy, setBusy] = useState(false); const [error, setError] = useState<unknown>();
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState(emptyForm); const [aadhaar, setAadhaar] = useState<File | null>(null); const [pan, setPan] = useState<File | null>(null); const [cancelledCheque, setCancelledCheque] = useState<File | null>(null); const [fileKey, setFileKey] = useState(0);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!editingId && !cancelledCheque) return setError(new Error("Cancelled cheque proof is required"));
    setBusy(true); setError(undefined);
    try {
      const { bank_name, account_holder, account_number, ifsc_code, ...vendorFields } = form;
      const vendor = await api<Vendor>(editingId ? `/vendors/${editingId}/` : "/vendors/", { method: editingId ? "PATCH" : "POST", body: JSON.stringify(vendorFields) });
      if (!editingId) {
        if (aadhaar) await uploadDocument(aadhaar, "AADHAAR", "vendor", vendor.id);
        if (pan) await uploadDocument(pan, "PAN", "vendor", vendor.id);
        const bank = await api<{ id: number }>("/vendor-bank-accounts/", { method: "POST", body: JSON.stringify({ vendor: vendor.id, bank_name, account_holder, account_number, ifsc_code }) });
        await uploadDocument(cancelledCheque!, "CANCELLED_CHEQUE", "vendor_bank_account", bank.id);
      }
      setAdding(false); setEditingId(null); setForm(emptyForm); setAadhaar(null); setPan(null); setCancelledCheque(null); setFileKey((value) => value + 1); await vendors.refetch();
    } catch (reason) { setError(reason); } finally { setBusy(false); }
  };
  const editVendor = (vendor: Vendor) => { setEditingId(vendor.id); setAdding(true); setForm({ ...emptyForm, vendor_code: vendor.vendor_code, legal_name: vendor.legal_name, display_name: vendor.display_name, email: vendor.email || "", primary_phone: vendor.primary_phone || "", status: vendor.status }); window.scrollTo({ top: 0, behavior: "smooth" }); };
  const toggleVendor = async (vendor: Vendor) => { try { await api(`/vendors/${vendor.id}/`, { method: "PATCH", body: JSON.stringify({ status: vendor.status === "ACTIVE" ? "INACTIVE" : "ACTIVE" }) }); await vendors.refetch(); } catch (reason) { setError(reason); } };

  const rows = vendors.data ? listResults(vendors.data) : [];
  return <>
    <PageHeader title="Transporters & vendors" description="Master data, verified identity documents and protected bank details."><button className="button primary" onClick={() => { setEditingId(null); setForm(emptyForm); setAdding((value) => !value); }}>+ New vendor</button></PageHeader>
    {adding && <section className="panel"><div className="panel-head"><h2>{editingId ? "Edit transporter" : "Create transporter"}</h2></div><form className="panel-body" onSubmit={submit}>
      {Boolean(error) && <ErrorNotice error={error} />}
      <div className="form-grid">
        <div className="field"><label>Vendor code</label><input required className="input" value={form.vendor_code} onChange={(e) => setForm({ ...form, vendor_code: e.target.value })} /></div>
        <div className="field"><label>Display name</label><input required className="input" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} /></div>
        <div className="field span-2"><label>Legal name</label><input required className="input" value={form.legal_name} onChange={(e) => setForm({ ...form, legal_name: e.target.value })} /></div>
        <div className="field"><label>Contact</label><input className="input" value={form.primary_contact_name} onChange={(e) => setForm({ ...form, primary_contact_name: e.target.value })} /></div>
        <div className="field"><label>Phone</label><input className="input" value={form.primary_phone} onChange={(e) => setForm({ ...form, primary_phone: e.target.value })} /></div>
        <div className="field"><label>Email</label><input type="email" className="input" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
        <div className="field"><label>Status</label><select className="input" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}><option>ACTIVE</option><option>HOLD</option><option>INACTIVE</option></select></div>
      </div>
      {!editingId && <><h3 style={{ marginTop: 24 }}>Identity verification (optional)</h3>
      <div className="form-grid two" key={`kyc-${fileKey}`}><div className="field"><label htmlFor="vendor-aadhaar">Aadhaar document</label><input id="vendor-aadhaar" type="file" className="input" accept=".pdf,image/jpeg,image/png" onChange={(e) => setAadhaar(e.target.files?.[0] ?? null)} /></div><div className="field"><label htmlFor="vendor-pan">PAN document</label><input id="vendor-pan" type="file" className="input" accept=".pdf,image/jpeg,image/png" onChange={(e) => setPan(e.target.files?.[0] ?? null)} /></div></div>
      <h3 style={{ marginTop: 24 }}>Bank details</h3>
      <div className="form-grid two">
        <div className="field"><label>Bank name</label><input required className="input" value={form.bank_name} onChange={(e) => setForm({ ...form, bank_name: e.target.value })} /></div>
        <div className="field"><label>Account holder</label><input required className="input" value={form.account_holder} onChange={(e) => setForm({ ...form, account_holder: e.target.value })} /></div>
        <div className="field"><label htmlFor="vendor-account-number">Account number</label><input id="vendor-account-number" required inputMode="numeric" minLength={6} maxLength={34} className="input" value={form.account_number} onChange={(e) => setForm({ ...form, account_number: e.target.value })} /></div>
        <div className="field"><label htmlFor="vendor-ifsc">IFSC code</label><input id="vendor-ifsc" required minLength={11} maxLength={11} className="input" placeholder="HDFC0001234" value={form.ifsc_code} onChange={(e) => setForm({ ...form, ifsc_code: e.target.value.toUpperCase() })} /></div>
        <div className="field span-2" key={`cheque-${fileKey}`}><label htmlFor="vendor-cancelled-cheque">Cancelled cheque proof</label><input id="vendor-cancelled-cheque" required type="file" className="input" accept=".pdf,image/jpeg,image/png" onChange={(e) => setCancelledCheque(e.target.files?.[0] ?? null)} /></div>
      </div>
      <div className="muted" style={{ marginTop: 10 }}>Account numbers are encrypted; only the last four digits are shown after saving. Files are signature-checked and malware-scanned when configured.</div></>}
      <div className="actions" style={{ justifyContent: "flex-end", marginTop: 13 }}><button type="button" className="button" onClick={() => { setAdding(false); setEditingId(null); setForm(emptyForm); }}>Cancel</button><button disabled={busy} className="button primary">{busy ? "Saving…" : editingId ? "Save changes" : "Create vendor"}</button></div>
    </form></section>}
    <section className="panel"><div className="panel-body"><div className="filters"><div className="field span-2"><label>Search vendor, code, phone or email</label><input className="input" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} /></div><div className="field"><label>Status</label><select className="input" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}><option value="">All</option><option>ACTIVE</option><option>HOLD</option><option>INACTIVE</option></select></div></div></div>{vendors.isPending ? <Loading /> : vendors.error ? <ErrorNotice error={vendors.error} /> : rows.length === 0 ? <Empty /> : <div className="table-wrap"><table><thead><tr><th>Code</th><th>Transporter</th><th>Primary contact</th><th>Email</th><th>Vehicles</th><th>Status / actions</th></tr></thead><tbody>{rows.map((vendor) => <tr key={vendor.id}><td>{vendor.vendor_code}</td><td><DetailLink href={`/vendors/${vendor.id}`}>{vendor.display_name}</DetailLink><div className="muted">{vendor.legal_name}</div></td><td>{vendor.primary_phone || "—"}</td><td>{vendor.email || "—"}</td><td>{vendor.vehicles_count}</td><td><StatusBadge value={vendor.status} /><div className="actions"><button className="button small" onClick={() => editVendor(vendor)}>Edit</button><button className="button small" onClick={() => toggleVendor(vendor)}>{vendor.status === "ACTIVE" ? "Deactivate" : "Activate"}</button></div></td></tr>)}</tbody></table></div>}{vendors.data && <Pagination count={vendors.data.count} page={page} pageSize={pageSize} onPage={setPage} />}</section>
  </>;
}
