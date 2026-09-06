"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, listResults } from "@/lib/api";
import type { Paginated, Vendor } from "@/lib/types";
import { DateText, Empty, ErrorNotice, Loading, Money, PageHeader, StatusBadge } from "@/components/UI";

export type VendorLedger = {
  vendor_name: string;
  total_freight_100: string;
  total_advance_amount: string;
  freight_balance_after_advance: string;
  total_vendor_liability: string;
  approved_gross: string;
  approved_remaining: string;
  tds: string;
  cash_paid: string;
  remaining_to_pay: string;
  entries: Array<{
    date: string;
    timestamp: string;
    trip_no: string;
    approval_no: string;
    payment_no: string;
    type: string;
    gross: string;
    tds: string;
    cash: string;
    utr: string;
    status: string;
  }>;
};

export function VendorFinancialCards({ ledger }: { ledger: VendorLedger }) {
  const cards = [
    ["Full freight (100%)", ledger.total_freight_100],
    ["Planned advance", ledger.total_advance_amount],
    ["Freight after advance", ledger.freight_balance_after_advance],
    ["Total vendor liability", ledger.total_vendor_liability],
    ["Cash paid", ledger.cash_paid],
    ["TDS deducted", ledger.tds],
    ["Remaining to pay", ledger.remaining_to_pay],
    ["Approved, still unpaid", ledger.approved_remaining],
  ];
  return (
    <div className="cards">
      {cards.map(([label, value]) => (
        <div className="card stat" key={label}>
          <div className="stat-label">{label}</div>
          <div className="stat-value">
            <Money value={value} />
          </div>
        </div>
      ))}
    </div>
  );
}

export function VendorLedgerTable({ ledger }: { ledger: VendorLedger }) {
  if (!ledger.entries.length) return <Empty message="No payment events for this vendor." />;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Date / timestamp</th>
            <th>Trip</th>
            <th>Approval / payment</th>
            <th>Event</th>
            <th className="money">Gross</th>
            <th className="money">TDS</th>
            <th className="money">Cash</th>
            <th>UTR</th>
          </tr>
        </thead>
        <tbody>
          {ledger.entries.map((entry, index) => (
            <tr key={`${entry.payment_no}-${index}`}>
              <td>
                <DateText value={entry.date} />
                <div className="muted">
                  <DateText value={entry.timestamp} />
                </div>
              </td>
              <td>{entry.trip_no}</td>
              <td>
                {entry.approval_no}
                <div className="muted">{entry.payment_no}</div>
              </td>
              <td>
                <StatusBadge value={entry.type} />
              </td>
              <td className="money">
                <Money value={entry.gross} />
              </td>
              <td className="money">
                <Money value={entry.tds} />
              </td>
              <td className="money">
                <Money value={entry.cash} />
              </td>
              <td>{entry.utr}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function VendorLedgerPage() {
  const vendors = useQuery({ queryKey: ["vendors"], queryFn: () => api<Paginated<Vendor>>("/vendors/") });
  const [vendorId, setVendorId] = useState("");
  const ledger = useQuery({
    queryKey: ["vendor-ledger", vendorId],
    queryFn: () => api<VendorLedger>(`/vendor-ledger/${vendorId}/`),
    enabled: Boolean(vendorId),
  });
  return (
    <>
      <PageHeader
        title="Vendor ledger"
        description="Full freight, advance, paid cash, TDS and true remaining liability from trip allocations."
      />
      <section className="panel">
        <div className="panel-body">
          <div className="field" style={{ maxWidth: 420 }}>
            <label>Transporter</label>
            <select className="input" value={vendorId} onChange={(event) => setVendorId(event.target.value)}>
              <option value="">Select vendor</option>
              {vendors.data &&
                listResults(vendors.data).map((vendor) => (
                  <option value={vendor.id} key={vendor.id}>
                    {vendor.vendor_code} — {vendor.display_name}
                  </option>
                ))}
            </select>
          </div>
        </div>
      </section>
      {!vendorId ? (
        <div className="panel">
          <Empty message="Select a transporter to view its ledger." />
        </div>
      ) : ledger.isPending ? (
        <Loading />
      ) : ledger.error ? (
        <ErrorNotice error={ledger.error} />
      ) : (
        <>
          <VendorFinancialCards ledger={ledger.data!} />
          <section className="panel">
            <div className="panel-head">
              <h2>Payment timeline</h2>
            </div>
            <VendorLedgerTable ledger={ledger.data!} />
          </section>
        </>
      )}
    </>
  );
}
