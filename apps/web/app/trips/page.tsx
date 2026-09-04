"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, listResults } from "@/lib/api";
import type { Client, Paginated, Trip, Vendor } from "@/lib/types";
import { DateText, DetailLink, Empty, ErrorNotice, Loading, Money, PageHeader, Pagination, StatusBadge } from "@/components/UI";

export default function TripRegisterPage() {
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [vendor, setVendor] = useState("");
  const [client, setClient] = useState(""); const [branch, setBranch] = useState("");
  const [vehicleType, setVehicleType] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);
  const pageSize = 25;
  const trips = useQuery({ queryKey: ["trips", status, search, vendor, client, branch, vehicleType, dateFrom, dateTo, page], queryFn: () => api<Paginated<Trip>>(`/trips/?page=${page}&page_size=${pageSize}&status=${encodeURIComponent(status)}&search=${encodeURIComponent(search)}&vendor=${encodeURIComponent(vendor)}&client=${encodeURIComponent(client)}&branch=${encodeURIComponent(branch)}&vehicle_type=${encodeURIComponent(vehicleType)}&date_from=${dateFrom}&date_to=${dateTo}`) });
  const masters = useQuery({ queryKey: ["trip-filter-masters"], queryFn: async () => ({ vendors: listResults(await api<Paginated<Vendor>>("/vendors/?page_size=200")), clients: listResults(await api<Paginated<Client>>("/clients/?page_size=200")) }) });
  const rows = trips.data ? listResults(trips.data) : [];
  return <>
    <PageHeader title="Trip register" description="Spreadsheet-dense deployment tracking with financial status on every line."><Link className="button" href="/approvals/new">Create approval</Link><Link className="button primary" href="/trips/new">+ Create trip</Link></PageHeader>
    <div className="panel"><div className="panel-body"><div className="filters"><div className="field span-2"><label>Search trip, indent, vehicle, route or vendor</label><input className="input" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="Search register…" /></div><div className="field"><label>Status</label><select className="input" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}><option value="">All statuses</option><option>READY</option><option>ADVANCE_APPROVAL_PENDING</option><option>ADVANCE_APPROVED</option><option>ADVANCE_PAID</option><option>IN_TRANSIT</option><option>DELIVERED</option></select></div><div className="field"><label>Vendor</label><select className="input" value={vendor} onChange={(e) => { setVendor(e.target.value); setPage(1); }}><option value="">All vendors</option>{masters.data?.vendors.map((row) => <option key={row.id} value={row.id}>{row.display_name}</option>)}</select></div><div className="field"><label>Client</label><select className="input" value={client} onChange={(e) => { setClient(e.target.value); setPage(1); }}><option value="">All clients</option>{masters.data?.clients.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></div><div className="field"><label>Branch</label><input className="input" value={branch} onChange={(e) => { setBranch(e.target.value); setPage(1); }} /></div><div className="field"><label>Vehicle type</label><input className="input" value={vehicleType} onChange={(e) => { setVehicleType(e.target.value); setPage(1); }} placeholder="e.g. 32 FT" /></div><div className="field"><label>From date</label><input type="date" className="input" value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setPage(1); }} /></div><div className="field"><label>To date</label><input type="date" className="input" value={dateTo} onChange={(e) => { setDateTo(e.target.value); setPage(1); }} /></div><div className="field"><label>Import</label><Link className="button" href="/imports">Preview legacy Excel</Link></div></div></div>
      {trips.isPending ? <Loading /> : trips.error ? <ErrorNotice error={trips.error} /> : rows.length === 0 ? <Empty message="No trips match the current filters." /> : <div className="table-wrap"><table><thead><tr><th>Trip / indents</th><th>Deployment / created</th><th>Route</th><th>Transporter</th><th>Vehicle</th><th className="money">Freight (100%)</th><th className="money">Advance</th><th className="money">Freight balance</th><th className="money">TDS</th><th className="money">Net request</th><th>EDD</th><th>Status</th></tr></thead><tbody>{rows.map((trip) => <tr key={trip.id}><td><DetailLink href={`/trips/${trip.id}`}>{trip.trip_no}</DetailLink><div className="muted" style={{ fontSize: 11 }}>{trip.indent_no}{trip.indent_count > 1 ? ` +${trip.indent_count - 1} more` : ""}</div></td><td><DateText value={trip.deployment_date} /><div className="muted"><DateText value={trip.created_at} /></div></td><td>{trip.origin} → {trip.destination}</td><td>{trip.vendor_name}</td><td>{trip.vehicle_no}<div className="muted">{trip.vehicle_type_snapshot}</div></td><td className="money"><Money value={trip.vendor_freight_rate} /></td><td className="money"><Money value={trip.calculation?.freight_advance_gross} /><div className="muted">{trip.advance_percent}%</div></td><td className="money"><Money value={trip.calculation?.remaining_freight_balance} /></td><td className="money"><Money value={trip.calculation?.tds_this_payment} /></td><td className="money"><strong><Money value={trip.calculation?.net_requested} /></strong></td><td><DateText value={trip.expected_delivery_date} /></td><td><StatusBadge value={trip.status} /></td></tr>)}</tbody></table></div>}
      {trips.data && <Pagination count={trips.data.count} page={page} pageSize={pageSize} onPage={setPage} />}
    </div>
  </>;
}
