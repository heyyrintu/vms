"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api, listResults } from "@/lib/api";
import type { Paginated, Payment, Trip } from "@/lib/types";
import { DateText, DetailLink, Empty, ErrorNotice, Loading, Money, PageHeader, StatusBadge } from "@/components/UI";

type Dashboard = {
  trips_today: number;
  vehicles_deployed: number;
  awaiting_vehicle: number;
  pending_approvals: string;
  approved_not_paid: string;
  paid_today: string;
  total_cash_paid: string;
  total_tds_deducted: string;
  total_gross_accounted: string;
  total_freight_100: string;
  total_advance_amount: string;
  freight_balance_after_advance: string;
  total_remaining_to_pay: string;
  advance_cash_paid_unsettled: string;
  remaining_vendor_payable: string;
  tds_month_to_date: string;
  trips_pending_settlement: number;
  pod_pending: number;
  billing_pending: number;
  gross_margin: string;
};

export default function DashboardPage() {
  const dashboard = useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dashboard>("/dashboard/") });
  const trips = useQuery({
    queryKey: ["trips", "dashboard"],
    queryFn: () => api<Paginated<Trip>>("/trips/?page_size=6"),
  });
  const payments = useQuery({
    queryKey: ["payments", "dashboard"],
    queryFn: () => api<Paginated<Payment>>("/payments/?page_size=5"),
  });
  if (dashboard.isPending) return <Loading />;
  if (dashboard.error) return <ErrorNotice error={dashboard.error} />;
  const d = dashboard.data!;
  const cards = [
    ["Full freight (100%)", <Money key="freight" value={d.total_freight_100} />, "Agreed value of active trips"],
    ["Planned advance", <Money key="planned-advance" value={d.total_advance_amount} />, "Configured trip advances"],
    [
      "Freight balance",
      <Money key="freight-balance" value={d.freight_balance_after_advance} />,
      "100% freight less planned advance",
    ],
    ["Total cash paid", <Money key="total-paid" value={d.total_cash_paid} />, "Lifetime posted vendor cash"],
    ["Total TDS", <Money key="total-tds" value={d.total_tds_deducted} />, "Lifetime posted withholding"],
    [
      "Remaining to pay",
      <Money key="remaining-pay" value={d.total_remaining_to_pay} />,
      "Trip liability less cash and TDS",
    ],
    ["Trips today", d.trips_today, "Scheduled deployments"],
    ["Vehicles deployed", d.vehicles_deployed, "Unique vehicles today"],
    ["Awaiting vehicle", d.awaiting_vehicle, "Unassigned trips"],
    ["Pending approvals", <Money key="pending" value={d.pending_approvals} />, "Net awaiting decision"],
    ["Approved, not paid", <Money key="unpaid" value={d.approved_not_paid} />, "Finance queue exposure"],
    ["Paid today", <Money key="paid" value={d.paid_today} />, "Net cash processed"],
    ["TDS month-to-date", <Money key="tds" value={d.tds_month_to_date} />, "Posted withholding"],
    ["Pending settlement", d.trips_pending_settlement, "Delivered/open trips"],
    ["POD pending", d.pod_pending, "Document follow-up"],
    ["Billing pending", d.billing_pending, "Client invoices not received"],
    ["Gross margin", <Money key="margin" value={d.gross_margin} />, "Billed less vendor/internal cost"],
  ];
  return (
    <>
      <PageHeader
        title="Operations overview"
        description="Live deployment, approval and vendor payment position across all trips."
      >
        <Link className="button" href="/approvals/new">
          Build approval
        </Link>
        <Link className="button primary" href="/trips/new">
          + New trip
        </Link>
      </PageHeader>
      <div className="cards">
        {cards.map(([label, value, note]) => (
          <div className="card stat" key={String(label)}>
            <div className="stat-label">{label}</div>
            <div className="stat-value">{value}</div>
            <div className="stat-note">{note}</div>
          </div>
        ))}
      </div>
      <div className="split">
        <section className="panel">
          <div className="panel-head">
            <h2>Recent trips</h2>
            <Link href="/trips" className="button small">
              View register
            </Link>
          </div>
          {trips.isPending ? (
            <Loading />
          ) : trips.error ? (
            <ErrorNotice error={trips.error} />
          ) : listResults(trips.data!).length === 0 ? (
            <Empty />
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Trip</th>
                    <th>Route</th>
                    <th>Vendor</th>
                    <th>Deployment / created</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {listResults(trips.data!)
                    .slice(0, 6)
                    .map((trip) => (
                      <tr key={trip.id}>
                        <td>
                          <DetailLink href={`/trips/${trip.id}`}>{trip.trip_no}</DetailLink>
                        </td>
                        <td>
                          {trip.origin} → {trip.destination}
                        </td>
                        <td>{trip.vendor_name}</td>
                        <td>
                          <DateText value={trip.deployment_date} />
                          <div className="muted">
                            <DateText value={trip.created_at} />
                          </div>
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
        </section>
        <section className="panel">
          <div className="panel-head">
            <h2>Recent payments</h2>
            <Link href="/payments" className="button small">
              Open register
            </Link>
          </div>
          {payments.isPending ? (
            <Loading />
          ) : payments.error ? (
            <ErrorNotice error={payments.error} />
          ) : listResults(payments.data!).length === 0 ? (
            <Empty />
          ) : (
            <div>
              {listResults(payments.data!)
                .slice(0, 5)
                .map((payment) => (
                  <div
                    key={payment.id}
                    style={{
                      padding: "13px 16px",
                      borderBottom: "1px solid var(--line)",
                      display: "flex",
                      justifyContent: "space-between",
                    }}
                  >
                    <div>
                      <DetailLink href={`/payments/${payment.id}`}>{payment.payment_no}</DetailLink>
                      <div className="muted" style={{ fontSize: 11 }}>
                        {payment.vendor_name} · {payment.utr_reference} ·{" "}
                        <DateText value={payment.paid_at || payment.created_at} />
                      </div>
                    </div>
                    <strong>
                      <Money value={payment.net_paid_amount} />
                    </strong>
                  </div>
                ))}
            </div>
          )}
        </section>
      </div>
    </>
  );
}
