"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import type { Payment, User } from "@/lib/types";
import { DateText, ErrorNotice, Loading, Money, PageHeader, StatusBadge } from "@/components/UI";
import { ContextDocuments } from "@/components/ContextDocuments";

export default function PaymentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const client = useQueryClient();
  const [reason, setReason] = useState("");
  const payment = useQuery({ queryKey: ["payment", id], queryFn: () => api<Payment>(`/payments/${id}/`) });
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<User>("/auth/me/") });
  const reverse = useMutation({
    mutationFn: () => api<Payment>(`/payments/${id}/reverse/`, { method: "POST", body: JSON.stringify({ reason }) }),
    onSuccess: (data) => {
      client.setQueryData(["payment", id], data);
      client.invalidateQueries({ queryKey: ["payments"] });
    },
  });
  if (payment.isPending) return <Loading />;
  if (payment.error) return <ErrorNotice error={payment.error} />;
  const p = payment.data!;
  return (
    <>
      <PageHeader title={p.payment_no} description={`${p.vendor_name} · ${p.payment_mode} · ${p.utr_reference}`}>
        <StatusBadge value={p.status} />
      </PageHeader>
      {reverse.error && <ErrorNotice error={reverse.error} />}
      <div className="summary-strip">
        <div>
          <span>Payment date / timestamp</span>
          <strong>
            <DateText value={p.payment_date} />
          </strong>
          <div className="muted">
            <DateText value={p.paid_at || p.created_at} />
          </div>
        </div>
        <div>
          <span>Gross allocated</span>
          <strong>
            <Money value={p.gross_allocated_amount} />
          </strong>
        </div>
        <div>
          <span>TDS withheld</span>
          <strong>
            <Money value={p.tds_amount} />
          </strong>
        </div>
        <div>
          <span>Net cash paid</span>
          <strong>
            <Money value={p.net_paid_amount} />
          </strong>
        </div>
      </div>
      <section className="panel">
        <div className="panel-head">
          <h2>Trip allocations</h2>
          <span className="eyebrow">Reconciled to transaction</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Trip</th>
                <th>Approval</th>
                <th className="money">Gross</th>
                <th className="money">TDS</th>
                <th className="money">Net cash</th>
              </tr>
            </thead>
            <tbody>
              {p.allocations.map((row) => (
                <tr key={row.id}>
                  <td>{row.trip_no}</td>
                  <td>{row.approval_no}</td>
                  <td className="money">
                    <Money value={row.gross_amount_allocated} />
                  </td>
                  <td className="money">
                    <Money value={row.tds_allocated} />
                  </td>
                  <td className="money">
                    <strong>
                      <Money value={row.net_cash_allocated} />
                    </strong>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="totals">
          <div className="total">
            <span>Gross</span>
            <strong>
              <Money value={p.gross_allocated_amount} />
            </strong>
          </div>
          <div className="total">
            <span>TDS</span>
            <strong>
              <Money value={p.tds_amount} />
            </strong>
          </div>
          <div className="total">
            <span>Net</span>
            <strong>
              <Money value={p.net_paid_amount} />
            </strong>
          </div>
        </div>
      </section>
      <ContextDocuments objectType="payment" objectId={id} />
      {p.remarks && <div className="notice">Finance remarks: {p.remarks}</div>}
      {p.status === "PAID" && ["FINANCE", "ADMIN"].includes(me.data?.role ?? "") && (
        <section className="panel">
          <div className="panel-head">
            <h2>Controlled reversal</h2>
          </div>
          <div className="panel-body">
            <p className="muted">
              Paid transactions cannot be edited or deleted. Reverse the complete transaction and create a corrected
              replacement.
            </p>
            <div className="field">
              <label>Mandatory reversal reason</label>
              <textarea className="input" value={reason} onChange={(e) => setReason(e.target.value)} />
            </div>
            <button
              className="button danger"
              disabled={!reason.trim() || reverse.isPending}
              onClick={() => reverse.mutate()}
              style={{ marginTop: 10 }}
            >
              Reverse transaction
            </button>
          </div>
        </section>
      )}
    </>
  );
}
