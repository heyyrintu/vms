"use client";

import { useQuery } from "@tanstack/react-query";
import { api, listResults } from "@/lib/api";
import { useRegisterFilters } from "@/lib/useRegisterFilters";
import type { Paginated, Vendor } from "@/lib/types";
import { DateText, Empty, ErrorNotice, Loading, Money, PageHeader, Pagination, StatusBadge } from "@/components/UI";

type TDS = {
  id: number;
  deduction_date: string;
  vendor_name: string;
  trip_no: string;
  payment_no: string;
  taxable_base: string;
  rate: string;
  tds_amount: string;
  policy_snapshot: string;
  finance_reference: string;
  status: string;
};

export default function TDSRegisterPage() {
  const { filters, set, page, setPage, pageSize, query } = useRegisterFilters({
    vendor: "",
    date_from: "",
    date_to: "",
  });
  const vendors = useQuery({
    queryKey: ["vendors", "filter"],
    queryFn: () => api<Paginated<Vendor>>("/vendors/?page_size=200"),
  });
  const entries = useQuery({ queryKey: ["tds", query], queryFn: () => api<Paginated<TDS>>(`/tds/?${query}`) });
  const rows = entries.data ? listResults(entries.data) : [];
  return (
    <>
      <PageHeader
        title="TDS register"
        description="Transparent withholding by vendor, trip, payment, taxable base, rate and snapshotted policy."
      />
      <section className="panel">
        <div className="panel-body filters">
          <div className="field">
            <label htmlFor="tds-vendor">Transporter</label>
            <select
              id="tds-vendor"
              className="input"
              value={filters.vendor}
              onChange={(e) => set("vendor", e.target.value)}
            >
              <option value="">All transporters</option>
              {vendors.data &&
                listResults(vendors.data).map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.display_name}
                  </option>
                ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="tds-from">From date</label>
            <input
              id="tds-from"
              className="input"
              type="date"
              value={filters.date_from}
              onChange={(e) => set("date_from", e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="tds-to">To date</label>
            <input
              id="tds-to"
              className="input"
              type="date"
              value={filters.date_to}
              onChange={(e) => set("date_to", e.target.value)}
            />
          </div>
        </div>
      </section>
      <section className="panel">
        {entries.isPending ? (
          <Loading />
        ) : entries.error ? (
          <ErrorNotice error={entries.error} />
        ) : rows.length === 0 ? (
          <Empty message="No posted TDS entries." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Vendor</th>
                  <th>Trip</th>
                  <th>Payment</th>
                  <th>Policy snapshot</th>
                  <th className="money">Taxable base</th>
                  <th className="money">Rate</th>
                  <th className="money">TDS</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <DateText value={row.deduction_date} />
                    </td>
                    <td>{row.vendor_name}</td>
                    <td>{row.trip_no}</td>
                    <td>
                      {row.payment_no}
                      <div className="muted">{row.finance_reference}</div>
                    </td>
                    <td>{row.policy_snapshot.replaceAll("_", " ")}</td>
                    <td className="money">
                      <Money value={row.taxable_base} />
                    </td>
                    <td className="money">{row.rate}%</td>
                    <td className="money">
                      <strong>
                        <Money value={row.tds_amount} />
                      </strong>
                    </td>
                    <td>
                      <StatusBadge value={row.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {entries.data && <Pagination count={entries.data.count} page={page} pageSize={pageSize} onPage={setPage} />}
      </section>
    </>
  );
}
