"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, listResults, money } from "@/lib/api";
import type { Client, Driver, Indent, Paginated, Trip, Vehicle, Vendor } from "@/lib/types";
import { DateText, Empty, ErrorNotice, Loading, PageHeader, StatusBadge } from "@/components/UI";

const today = new Date().toISOString().slice(0, 10);

export default function NewTripPage() {
  const router = useRouter();
  const masters = useQuery({ queryKey: ["trip-masters-with-indents"], queryFn: async () => ({
    clients: listResults(await api<Paginated<Client>>("/clients/")),
    vendors: listResults(await api<Paginated<Vendor>>("/vendors/")),
    vehicles: listResults(await api<Paginated<Vehicle>>("/vehicles/")),
    drivers: listResults(await api<Paginated<Driver>>("/drivers/")),
    indents: listResults(await api<Paginated<Indent>>("/indents/?status=OPEN")),
  }) });
  const [form, setForm] = useState({ client: "", origin: "Sonipat", destination: "", deployment_date: today, expected_delivery_date: "", vendor: "", vehicle: "", driver: "", vendor_freight_rate: "", unloading: "0", advance_percent: "90", uom_ltrs: "LTR", quantity: "", total_load: "", branch: "Sonipat", vehicle_type: "" });
  const [selectedIndentIds, setSelectedIndentIds] = useState<number[]>([]);
  const [indentSearch, setIndentSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const change = (key: string, value: string) => setForm((old) => ({ ...old, [key]: value, ...(key === "vendor" ? { vehicle: "", driver: "" } : {}), ...(key === "client" ? {} : {}) }));

  useEffect(() => {
    if (!masters.data || selectedIndentIds.length) return;
    const requested = Number(new URLSearchParams(window.location.search).get("indent"));
    const match = masters.data.indents.find((row) => row.id === requested);
    if (match) {
      const timer = window.setTimeout(() => {
        setSelectedIndentIds([match.id]);
        setForm((old) => ({ ...old, client: String(match.client), origin: match.origin, destination: match.destination, deployment_date: match.indent_date, expected_delivery_date: match.expected_delivery_date || "", quantity: match.default_quantity || "", total_load: match.quantity_ltrs || "", branch: match.branch || old.branch, vehicle_type: match.required_vehicle_type || "" }));
      }, 0);
      return () => window.clearTimeout(timer);
    }
  }, [masters.data, selectedIndentIds.length]);

  const clientId = form.client || String(masters.data?.clients[0]?.id ?? "");
  const availableIndents = useMemo(() => (masters.data?.indents ?? [])
    .filter((row) => String(row.client) === clientId && `${row.indent_no} ${row.challan_no} ${row.ship_to_party_name} ${row.origin} ${row.destination} ${row.item}`.toLowerCase().includes(indentSearch.toLowerCase()))
    .sort((a, b) => Number(selectedIndentIds.includes(b.id)) - Number(selectedIndentIds.includes(a.id)) || a.trip_count - b.trip_count),
  [masters.data, clientId, indentSearch, selectedIndentIds]);
  const selectedIndents = (masters.data?.indents ?? []).filter((row) => selectedIndentIds.includes(row.id));
  const vendorVehicles = useMemo(() => masters.data?.vehicles.filter((row) => String(row.vendor) === form.vendor) ?? [], [masters.data, form.vendor]);
  const vendorDrivers = useMemo(() => masters.data?.drivers.filter((row) => !row.vendor || String(row.vendor) === form.vendor) ?? [], [masters.data, form.vendor]);
  const freight = Number(form.vendor_freight_rate || 0); const unloading = Number(form.unloading || 0); const advance = freight * Number(form.advance_percent || 0) / 100; const tds = advance * .01; const gross = advance + unloading;

  const toggleIndent = (indent: Indent) => {
    const selected = selectedIndentIds.includes(indent.id);
    const next = selected ? selectedIndentIds.filter((id) => id !== indent.id) : [...selectedIndentIds, indent.id];
    setSelectedIndentIds(next);
    if (!selected && selectedIndentIds.length === 0) {
      setForm((old) => ({ ...old, client: String(indent.client), origin: indent.origin, destination: indent.destination, deployment_date: indent.indent_date, expected_delivery_date: indent.expected_delivery_date || "", quantity: indent.default_quantity || "", total_load: indent.quantity_ltrs || "", branch: indent.branch || old.branch, vehicle_type: indent.required_vehicle_type || "" }));
    }
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(undefined);
    try {
      if (!selectedIndentIds.length) throw new Error("Select at least one indent for this trip");
      const trip = await api<Trip>("/trips/", { method: "POST", body: JSON.stringify({ indent: selectedIndentIds[0], indent_ids: selectedIndentIds, client: Number(clientId), origin: form.origin, destination: form.destination, deployment_date: form.deployment_date, expected_delivery_date: form.expected_delivery_date || null, vendor: Number(form.vendor), vehicle: Number(form.vehicle), driver: Number(form.driver), vendor_freight_rate: form.vendor_freight_rate, advance_percent: form.advance_percent, uom_ltrs: form.uom_ltrs, quantity: form.quantity || null, total_load: form.total_load || null, branch: form.branch }) });
      if (Number(form.unloading) > 0) await api(`/trips/${trip.id}/charges/`, { method: "POST", body: JSON.stringify({ charge_type: "UNLOADING", description: "Unloading advance", amount: form.unloading, direction: "ADD", advance_eligible: true, tds_eligible: false, source: "INITIAL" }) });
      router.push(`/trips/${trip.id}`);
    } catch (reason) { setError(reason); } finally { setBusy(false); }
  };
  if (masters.isPending) return <Loading />;
  if (masters.error) return <ErrorNotice error={masters.error} />;
  const mixedRoutes = new Set(selectedIndents.map((row) => `${row.origin}|${row.destination}`.toLowerCase())).size > 1;
  return <>
    <PageHeader title="Create vehicle trip" description="Combine one or more client indents into a single vehicle deployment and payment-traceable trip." />
    {Boolean(error) && <ErrorNotice error={error} />}
    <form onSubmit={submit}>
      <section className="panel indent-picker">
        <div className="panel-head"><h2>Select indents</h2><span className="indent-picker-count"><strong>{selectedIndentIds.length}</strong> selected · {availableIndents.length} available</span></div>
        <div className="indent-picker-toolbar">
          <div className="field"><label>Client</label><select className="input" required value={clientId} onChange={(e) => { change("client", e.target.value); setSelectedIndentIds([]); }}>{masters.data!.clients.map((client) => <option value={client.id} key={client.id}>{client.code} — {client.name}</option>)}</select></div>
          <div className="field indent-picker-search"><label>Find indent</label><input aria-label="Find by challan, party or route" className="input" value={indentSearch} onChange={(e) => setIndentSearch(e.target.value)} placeholder="Challan, indent, party, item or route…" /></div>
          <Link className="button small indent-picker-add" href="/indents">+ New indent</Link>
        </div>
        {availableIndents.length === 0 ? <div className="indent-picker-empty"><Empty message="No open indents match this client and search." /></div> : <div className="table-wrap indent-picker-results"><table className="indent-picker-table"><thead><tr><th aria-label="Select"></th><th>Indent / challan</th><th>Party</th><th>Route</th><th>Load</th><th>Usage</th></tr></thead><tbody>{availableIndents.map((row) => {
          const selected = selectedIndentIds.includes(row.id);
          return <tr key={row.id} className={selected ? "selected" : undefined} onClick={() => toggleIndent(row)}>
            <td><input aria-label={`Select ${row.challan_no || row.indent_no}`} className="checkbox" type="checkbox" checked={selected} onClick={(event) => event.stopPropagation()} onChange={() => toggleIndent(row)} /></td>
            <td><strong>{row.challan_no || row.indent_no}</strong><small><DateText value={row.challan_datetime || row.indent_date} /></small></td>
            <td><span>{row.ship_to_party_name || "—"}</span>{row.ship_to_party_code && <small>{row.ship_to_party_code}</small>}</td>
            <td><span>{row.origin} → {row.destination}</span></td>
            <td><span>{row.item || "—"}</span>{row.quantity_ltrs && <small>{row.quantity_ltrs} LTR</small>}</td>
            <td title={row.trip_count ? "This indent can still be split across multiple vehicle trips." : "Not assigned to any trip."}>{row.trip_count ? <StatusBadge value={`LINKED · ${row.trip_count}`} /> : <StatusBadge value="UNASSIGNED" />}</td>
          </tr>;
        })}</tbody></table></div>}
        {mixedRoutes && <div className="notice">Selected indents have different routes. Confirm the actual vehicle route below before creating the trip.</div>}
      </section>
      <section className="panel"><div className="panel-head"><h2>Trip route & schedule</h2><span className="eyebrow">Suggested from first indent</span></div><div className="panel-body form-grid"><div className="field"><label>Deployment date</label><input type="date" className="input" required value={form.deployment_date} onChange={(e) => change("deployment_date", e.target.value)} /></div><div className="field"><label>EDD</label><input type="date" className="input" value={form.expected_delivery_date} onChange={(e) => change("expected_delivery_date", e.target.value)} /></div><div className="field"><label>From</label><input className="input" required value={form.origin} onChange={(e) => change("origin", e.target.value)} /></div><div className="field"><label>To</label><input className="input" required value={form.destination} onChange={(e) => change("destination", e.target.value)} /></div><div className="field"><label>Branch</label><input className="input" value={form.branch} onChange={(e) => change("branch", e.target.value)} /></div><div className="field"><label>Vehicle type</label><input className="input" value={form.vehicle_type} onChange={(e) => change("vehicle_type", e.target.value)} placeholder="e.g. 32 FT MXL" /></div></div></section>
      <section className="panel"><div className="panel-head"><h2>Deployment</h2></div><div className="panel-body form-grid"><div className="field"><label>Transporter</label><select className="input" required value={form.vendor} onChange={(e) => change("vendor", e.target.value)}><option value="">Select vendor</option>{masters.data!.vendors.filter((row) => row.status === "ACTIVE").map((row) => <option value={row.id} key={row.id}>{row.display_name}</option>)}</select></div><div className="field"><label>Vehicle no.</label><select className="input" required value={form.vehicle} onChange={(e) => change("vehicle", e.target.value)}><option value="">Select vehicle</option>{vendorVehicles.map((row) => <option value={row.id} key={row.id}>{row.registration_no} · {row.vehicle_type}</option>)}</select></div><div className="field"><label>Driver</label><select className="input" required value={form.driver} onChange={(e) => change("driver", e.target.value)}><option value="">Select driver</option>{vendorDrivers.map((row) => <option value={row.id} key={row.id}>{row.name} · {row.phone}</option>)}</select></div><div className="field"><label>UOM</label><input className="input" value={form.uom_ltrs} onChange={(e) => change("uom_ltrs", e.target.value)} /></div><div className="field"><label>Quantity</label><input type="number" step=".001" className="input" value={form.quantity} onChange={(e) => change("quantity", e.target.value)} /></div><div className="field"><label>Total load</label><input type="number" step=".001" className="input" value={form.total_load} onChange={(e) => change("total_load", e.target.value)} /></div></div></section>
      <section className="panel"><div className="panel-head"><h2>Advance calculation</h2><span className="eyebrow">Preview · server recalculates</span></div><div className="panel-body form-grid"><div className="field"><label>Vehicle freight rate</label><input type="number" min="0" step=".01" className="input" required value={form.vendor_freight_rate} onChange={(e) => change("vendor_freight_rate", e.target.value)} /></div><div className="field"><label>Advance percent</label><input type="number" min="0" max="100" step=".01" className="input" required value={form.advance_percent} onChange={(e) => change("advance_percent", e.target.value)} /></div><div className="field"><label>Unloading advance</label><input type="number" min="0" step=".01" className="input" value={form.unloading} onChange={(e) => change("unloading", e.target.value)} /></div></div><div className="totals"><div className="total"><span>Freight advance</span><strong>{money(advance)}</strong></div><div className="total"><span>Gross request</span><strong>{money(gross)}</strong></div><div className="total"><span>TDS preview (1%)</span><strong>{money(tds)}</strong></div><div className="total"><span>Net request</span><strong>{money(gross - tds)}</strong></div></div></section>
      <div className="actions" style={{ justifyContent: "flex-end" }}><button type="button" className="button" onClick={() => router.back()}>Cancel</button><button className="button primary" disabled={busy || !selectedIndentIds.length}>{busy ? "Creating trip…" : `Create trip with ${selectedIndentIds.length || 0} indent(s)`}</button></div>
    </form>
  </>;
}
