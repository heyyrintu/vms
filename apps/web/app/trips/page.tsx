"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, apiAll, listResults } from "@/lib/api";
import type { Client, Paginated, Trip, Vendor } from "@/lib/types";
import {
  DateText,
  DetailLink,
  Empty,
  ErrorNotice,
  Loading,
  Money,
  PageHeader,
  Pagination,
  StatusBadge,
} from "@/components/UI";

export default function TripRegisterPage() {
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [vendor, setVendor] = useState("");
  const [client, setClient] = useState("");
  const [branch, setBranch] = useState("");
  const [vehicleType, setVehicleType] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);
  const pageSize = 25;
  const choices = useQuery({
    queryKey: ["choices"],
    queryFn: () => api<{ trip_status: Array<{ value: string; label: string }> }>("/choices/"),
    staleTime: Infinity,
  });
  const trips = useQuery({
    queryKey: ["trips", status, search, vendor, client, branch, vehicleType, dateFrom, dateTo, page],
    queryFn: () =>
      api<Paginated<Trip>>(
        `/trips/?page=${page}&page_size=${pageSize}&status=${encodeURIComponent(status)}&search=${encodeURIComponent(search)}&vendor=${encodeURIComponent(vendor)}&client=${encodeURIComponent(client)}&branch=${encodeURIComponent(branch)}&vehicle_type=${encodeURIComponent(vehicleType)}&date_from=${dateFrom}&date_to=${dateTo}`,
      ),
  });
  const masters = useQuery({
    queryKey: ["trip-filter-masters"],
    queryFn: async () => ({
      vendors: await apiAll<Vendor>("/vendors/"),
      clients: listResults(await api<Paginated<Client>>("/clients/?page_size=200")),
    }),
  });
  const rows = trips.data ? listResults(trips.data) : [];
  return (
    <>
      <PageHeader
        title="Trip register"
        description="Spreadsheet-dense deployment tracking with financial status on every line."
      >
        <Link className="button" href="/approvals/new">
          Create approval
        </Link>
        <Link className="button primary" href="/trips/new">
          + Create trip
        </Link>
      </PageHeader>
      <div className="panel">
        <div className="panel-body">
          <div className="filters">
            <div className="field span-2">
              <label htmlFor="trip-filter-search">Search trip, indent, vehicle, route or vendor</label>
              <input
                id="trip-filter-search"
                className="input"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
                placeholder="Search register…"
              />
            </div>
            <div className="field">
              <label htmlFor="trip-filter-status">Status</label>
              <select
                id="trip-filter-status"
                aria-label="Trip status"
                className="input"
                value={status}
                onChange={(e) => {
                  setStatus(e.target.value);
                  setPage(1);
                }}
              >
                <option value="">All statuses</option>
                {choices.data?.trip_status.map((choice) => (
                  <option key={choice.value} value={choice.value}>
                    {choice.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="trip-filter-vendor">Vendor</label>
              <select
                id="trip-filter-vendor"
                className="input"
                value={vendor}
                onChange={(e) => {
                  setVendor(e.target.value);
                  setPage(1);
                }}
              >
                <option value="">All vendors</option>
                {masters.data?.vendors.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.display_name}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="trip-filter-client">Client</label>
              <select
                id="trip-filter-client"
                className="input"
                value={client}
                onChange={(e) => {
                  setClient(e.target.value);
                  setPage(1);
                }}
              >
                <option value="">All clients</option>
                {masters.data?.clients.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="trip-filter-branch">Branch</label>
              <input
                id="trip-filter-branch"
                className="input"
                value={branch}
                onChange={(e) => {
                  setBranch(e.target.value);
                  setPage(1);
                }}
              />
            </div>
            <div className="field">
              <label htmlFor="trip-filter-vehicle-type">Vehicle type</label>
              <input
                id="trip-filter-vehicle-type"
                className="input"
                value={vehicleType}
                onChange={(e) => {
                  setVehicleType(e.target.value);
                  setPage(1);
                }}
                placeholder="e.g. 32 FT"
              />
            </div>
            <div className="field">
              <label htmlFor="trip-filter-from">From date</label>
              <input
                id="trip-filter-from"
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
              <label htmlFor="trip-filter-to">To date</label>
              <input
                id="trip-filter-to"
                type="date"
                className="input"
                value={dateTo}
                onChange={(e) => {
                  setDateTo(e.target.value);
                  setPage(1);
                }}
              />
            </div>
            <div className="field">
              <label>Import</label>
              <Link className="button" href="/imports">
                Preview legacy Excel
              </Link>
            </div>
          </div>
        </div>
        {trips.isPending ? (
          <Loading />
        ) : trips.error ? (
          <ErrorNotice error={trips.error} />
        ) : rows.length === 0 ? (
          <Empty message="No trips match the current filters." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Trip / indents</th>
                  <th>Deployment / created</th>
                  <th>Route</th>
                  <th>Transporter</th>
                  <th>Vehicle</th>
                  <th className="money">Freight (100%)</th>
                  <th className="money">Advance</th>
                  <th className="money">Freight balance</th>
                  <th className="money">TDS</th>
                  <th className="money">Net request</th>
                  <th>EDD</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((trip) => (
                  <tr key={trip.id}>
                    <td>
                      <DetailLink href={`/trips/${trip.id}`}>{trip.trip_no}</DetailLink>
                      <div className="muted" style={{ fontSize: 11 }}>
                        {trip.indent_no}
                        {trip.indent_count > 1 ? ` +${trip.indent_count - 1} more` : ""}
                      </div>
                    </td>
                    <td>
                      <DateText value={trip.deployment_date} />
                      <div className="muted">
                        <DateText value={trip.created_at} />
                      </div>
                    </td>
                    <td>
                      {trip.origin} → {trip.destination}
                    </td>
                    <td>{trip.vendor_name}</td>
                    <td>
                      {trip.vehicle_no}
                      <div className="muted">{trip.vehicle_type_snapshot}</div>
                    </td>
                    <td className="money">
                      <Money value={trip.vendor_freight_rate} />
                    </td>
                    <td className="money">
                      <Money value={trip.calculation?.freight_advance_gross} />
                      <div className="muted">{trip.advance_percent}%</div>
                    </td>
                    <td className="money">
                      <Money value={trip.calculation?.remaining_freight_balance} />
                    </td>
                    <td className="money">
                      <Money value={trip.calculation?.tds_this_payment} />
                    </td>
                    <td className="money">
                      <strong>
                        <Money value={trip.calculation?.net_requested} />
                      </strong>
                    </td>
                    <td>
                      <DateText value={trip.expected_delivery_date} />
                    </td>
                    <td>
                      <StatusBadge value={trip.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {trips.data && <Pagination count={trips.data.count} page={page} pageSize={pageSize} onPage={setPage} />}
      </div>
    </>
  );
}
