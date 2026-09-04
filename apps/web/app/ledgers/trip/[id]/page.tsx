"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import type { Payment } from "@/lib/types";
import { DateText, Empty, ErrorNotice, Loading, Money, PageHeader, StatusBadge } from "@/components/UI";

type TripLedger = { trip_no: string; vendor: string; created_at: string; updated_at: string; freight_100: string; advance_percent: string; advance_amount: string; freight_balance_after_advance: string; total_vendor_liability: string; approved_gross: string; tds_deducted: string; cash_paid: string; remaining_approved: string; remaining_to_pay: string; client_billing?: string; events: Payment[] };

export default function TripLedgerPage() {
  const { id } = useParams<{ id: string }>();
  const ledger = useQuery({ queryKey: ["trip-ledger", id], queryFn: () => api<TripLedger>(`/trip-ledger/${id}/`) });
  if (ledger.isPending) return <Loading />;
  if (ledger.error) return <ErrorNotice error={ledger.error} />;
  const row = ledger.data!;
  return <><PageHeader title={`Trip ledger · ${row.trip_no}`} description={`${row.vendor} · Created ${new Date(row.created_at).toLocaleString("en-IN")} · Updated ${new Date(row.updated_at).toLocaleString("en-IN")}`} />
    <div className="cards">{[
      ["Full freight (100%)", row.freight_100], [`Advance (${row.advance_percent}%)`, row.advance_amount],
      ["Freight after advance", row.freight_balance_after_advance], ["Total vendor liability", row.total_vendor_liability],
      ["Approved gross", row.approved_gross], ["Cash paid", row.cash_paid], ["TDS deducted", row.tds_deducted], ["Remaining to pay", row.remaining_to_pay],
    ].map(([label, value]) => <div className="card stat" key={label}><div className="stat-label">{label}</div><div className="stat-value"><Money value={value} /></div></div>)}</div>
    <section className="panel"><div className="panel-head"><h2>Payment events</h2></div>{!row.events.length ? <Empty message="No payments have been posted for this trip." /> : <div className="table-wrap"><table><thead><tr><th>Payment</th><th>Date / timestamp</th><th>UTR</th><th className="money">Gross</th><th className="money">TDS</th><th className="money">Cash</th><th>Status</th></tr></thead><tbody>{row.events.map((payment) => <tr key={payment.id}><td>{payment.payment_no}</td><td><DateText value={payment.payment_date} /><div className="muted"><DateText value={payment.paid_at || payment.created_at} /></div></td><td>{payment.utr_reference}</td><td className="money"><Money value={payment.gross_allocated_amount} /></td><td className="money"><Money value={payment.tds_amount} /></td><td className="money"><Money value={payment.net_paid_amount} /></td><td><StatusBadge value={payment.status} /></td></tr>)}</tbody></table></div>}</section>
  </>;
}
