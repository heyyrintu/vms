"use client";

import { useQuery } from "@tanstack/react-query";
import { api, listResults } from "@/lib/api";
import type { Paginated } from "@/lib/types";
import { DateText, Empty, ErrorNotice, Loading, Money, PageHeader, StatusBadge } from "@/components/UI";

type TDS = { id: number; deduction_date: string; vendor_name: string; trip_no: string; payment_no: string; taxable_base: string; rate: string; tds_amount: string; policy_snapshot: string; finance_reference: string; status: string };

export default function TDSRegisterPage() {
  const query = useQuery({ queryKey: ["tds"], queryFn: () => api<Paginated<TDS>>("/tds/") }); const rows = query.data ? listResults(query.data) : [];
  return <><PageHeader title="TDS register" description="Transparent withholding by vendor, trip, payment, taxable base, rate and snapshotted policy." /><section className="panel">{query.isPending ? <Loading /> : query.error ? <ErrorNotice error={query.error} /> : rows.length === 0 ? <Empty message="No posted TDS entries." /> : <div className="table-wrap"><table><thead><tr><th>Date</th><th>Vendor</th><th>Trip</th><th>Payment</th><th>Policy snapshot</th><th className="money">Taxable base</th><th className="money">Rate</th><th className="money">TDS</th><th>Status</th></tr></thead><tbody>{rows.map((row) => <tr key={row.id}><td><DateText value={row.deduction_date} /></td><td>{row.vendor_name}</td><td>{row.trip_no}</td><td>{row.payment_no}<div className="muted">{row.finance_reference}</div></td><td>{row.policy_snapshot.replaceAll("_", " ")}</td><td className="money"><Money value={row.taxable_base} /></td><td className="money">{row.rate}%</td><td className="money"><strong><Money value={row.tds_amount} /></strong></td><td><StatusBadge value={row.status} /></td></tr>)}</tbody></table></div>}</section></>;
}

