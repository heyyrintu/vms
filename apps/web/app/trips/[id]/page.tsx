"use client";

import { FormEvent, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, listResults } from "@/lib/api";
import type { Paginated, Trip } from "@/lib/types";
import { TripIndentsPanel } from "@/components/TripIndentsPanel";
import { CommentsPanel } from "@/components/CommentsPanel";
import { DateText, Empty, ErrorNotice, Loading, Money, PageHeader, StatusBadge } from "@/components/UI";
import { type ViewableDocument, useDocumentViewer } from "@/components/DocumentViewer";

type TripLedger = {
  trip_no: string;
  vendor: string;
  freight_100: string;
  advance_amount: string;
  freight_balance_after_advance: string;
  total_vendor_liability: string;
  approved_gross: string;
  tds_deducted: string;
  cash_paid: string;
  remaining_approved: string;
  remaining_to_pay: string;
  client_billing?: string;
  final_vendor_cost?: string;
  remaining_cash_payable?: string;
  billing_status: string;
  gross_profit?: string;
  margin_percent?: string;
  events: unknown[];
};
type Document = ViewableDocument & { size: number; created_at: string };
type Settlement = {
  id: number;
  final_freight: string;
  additive_charges: string;
  vendor_deductions: string;
  total_vendor_gross_cost: string;
  total_tds_required: string;
  total_tds_deducted: string;
  total_net_vendor_payable: string;
  total_cash_paid: string;
  remaining_cash_payable: string;
  settlement_status: string;
  settlement_approval?: number;
  missing_documents: string[];
};
type Billing = {
  id: number;
  billing_amount: string;
  invoice_no: string;
  invoice_date?: string;
  payment_status: string;
  received_amount: string;
  internal_trip_costs: string;
  gross_profit: string;
  margin_percent: string;
};
type Audit = {
  id: number;
  action: string;
  actor_name: string;
  before: unknown;
  after: unknown;
  created_at: string;
};

export default function TripDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const trip = useQuery({
    queryKey: ["trip", id],
    queryFn: () => api<Trip>(`/trips/${id}/`),
  });
  const ledger = useQuery({
    queryKey: ["trip-ledger", id],
    queryFn: () => api<TripLedger>(`/trip-ledger/${id}/`),
  });
  const documents = useQuery({
    queryKey: ["documents", "trip", id],
    queryFn: () => api<Paginated<Document>>(`/documents/?object_type=trip&object_id=${id}`),
  });
  const settlements = useQuery({
    queryKey: ["settlement", id],
    queryFn: () => api<Paginated<Settlement>>(`/settlements/?trip=${id}`),
  });
  const billings = useQuery({
    queryKey: ["billing", id],
    queryFn: () => api<Paginated<Billing>>(`/billings/?trip=${id}`),
  });
  const audit = useQuery({
    queryKey: ["audit", "trip", id],
    queryFn: () => api<Paginated<Audit>>(`/audit/?object_type=operations.Trip&object_id=${id}`),
    retry: false,
  });
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState("POD");
  const { open: openDocument, viewer } = useDocumentViewer();
  const [settlementForm, setSettlementForm] = useState({
    final_freight: "",
    additive_charges: "0",
    vendor_deductions: "0",
  });
  const [billingForm, setBillingForm] = useState({
    billing_amount: "",
    invoice_no: "",
    invoice_date: "",
    payment_status: "INVOICED",
    received_amount: "0",
    internal_trip_costs: "0",
    notes: "",
  });
  const refresh = async () => {
    await Promise.all([
      trip.refetch(),
      ledger.refetch(),
      documents.refetch(),
      settlements.refetch(),
      billings.refetch(),
      audit.refetch(),
    ]);
  };
  const run = async (callback: () => Promise<unknown>) => {
    setBusy(true);
    setError(undefined);
    try {
      await callback();
      await refresh();
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(false);
    }
  };
  const upload = async (event: FormEvent) => {
    event.preventDefault();
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    body.append("kind", kind);
    body.append("object_type", "trip");
    body.append("object_id", id);
    await run(() => api("/documents/", { method: "POST", body }));
    setFile(null);
  };
  const saveSettlement = async (event: FormEvent) => {
    event.preventDefault();
    const current = settlements.data && listResults(settlements.data)[0];
    await run(() =>
      api(current ? `/settlements/${current.id}/` : "/settlements/", {
        method: current ? "PATCH" : "POST",
        body: JSON.stringify({
          trip: Number(id),
          final_freight: settlementForm.final_freight || trip.data!.vendor_freight_rate,
          additive_charges: settlementForm.additive_charges,
          vendor_deductions: settlementForm.vendor_deductions,
        }),
      }),
    );
  };
  const saveBilling = async (event: FormEvent) => {
    event.preventDefault();
    const current = billings.data && listResults(billings.data)[0];
    await run(() =>
      api(current ? `/billings/${current.id}/` : "/billings/", {
        method: current ? "PATCH" : "POST",
        body: JSON.stringify({
          ...billingForm,
          trip: Number(id),
          billing_amount: billingForm.billing_amount || trip.data!.client_billing_amount || "0",
          invoice_date: billingForm.invoice_date || null,
        }),
      }),
    );
  };
  if (trip.isPending) return <Loading />;
  if (trip.error) return <ErrorNotice error={trip.error} />;
  const t = trip.data!;
  const c = t.calculation;
  const settlement = settlements.data && listResults(settlements.data)[0];
  const billing = billings.data && listResults(billings.data)[0];
  const docs = documents.data ? listResults(documents.data) : [];
  return (
    <>
      <PageHeader title={t.trip_no} description={`${t.origin} → ${t.destination} · ${t.vendor_name}`}>
        <Link className="button" href="/approvals/new">
          Add to approval
        </Link>
        <StatusBadge value={t.status} />
      </PageHeader>
      {Boolean(error) && <ErrorNotice error={error} />}
      <div className="summary-strip">
        <div>
          <span>Client indent</span>
          <strong>{t.indent_no}</strong>
        </div>
        <div>
          <span>Deployment / EDD</span>
          <strong>
            <DateText value={t.deployment_date} /> · <DateText value={t.expected_delivery_date} />
          </strong>
        </div>
        <div>
          <span>Vehicle</span>
          <strong>{t.vehicle_no}</strong>
          <div className="muted">{t.vehicle_type_snapshot}</div>
        </div>
        <div>
          <span>Driver</span>
          <strong>{t.driver_name}</strong>
        </div>
      </div>
      <TripIndentsPanel trip={t} onChanged={() => trip.refetch()} />
      <div className="split">
        <div>
          <section className="panel">
            <div className="panel-head">
              <h2>Cost & advance breakdown</h2>
              <span className="eyebrow">{c.tds_policy?.replaceAll("_", " ")}</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Component</th>
                    <th>Basis</th>
                    <th className="money">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>Agreed freight</td>
                    <td>Vendor vehicle rate</td>
                    <td className="money">
                      <Money value={c.freight_rate} />
                    </td>
                  </tr>
                  <tr>
                    <td>Freight advance</td>
                    <td>{c.advance_percent}% of freight</td>
                    <td className="money">
                      <Money value={c.freight_advance_gross} />
                    </td>
                  </tr>
                  <tr>
                    <td>Eligible charges</td>
                    <td>{t.charges.length} charge line(s)</td>
                    <td className="money">
                      <Money value={c.advance_eligible_charges} />
                    </td>
                  </tr>
                  <tr>
                    <td>Gross requested</td>
                    <td>Advance + eligible charges − deductions</td>
                    <td className="money">
                      <strong>
                        <Money value={c.gross_requested} />
                      </strong>
                    </td>
                  </tr>
                  <tr>
                    <td>TDS withholding</td>
                    <td>
                      {c.tds_rate}% on <Money value={c.tds_base} />
                    </td>
                    <td className="money">
                      − <Money value={c.tds_this_payment} />
                    </td>
                  </tr>
                  <tr>
                    <td>Net requested</td>
                    <td>Cash payable after withholding</td>
                    <td className="money">
                      <strong>
                        <Money value={c.net_requested} />
                      </strong>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
          <section className="panel">
            <div className="panel-head">
              <h2>Payment, settlement & margin</h2>
              <Link className="button small" href={`/ledgers/trip/${id}`}>
                Full ledger
              </Link>
            </div>
            {ledger.isPending ? (
              <Loading />
            ) : ledger.error ? (
              <ErrorNotice error={ledger.error} />
            ) : (
              <div className="summary-strip" style={{ border: 0, margin: 0 }}>
                <div>
                  <span>Approved gross</span>
                  <strong>
                    <Money value={ledger.data!.approved_gross} />
                  </strong>
                </div>
                <div>
                  <span>Cash / TDS</span>
                  <strong>
                    <Money value={ledger.data!.cash_paid} /> / <Money value={ledger.data!.tds_deducted} />
                  </strong>
                </div>
                <div>
                  <span>Final vendor cost</span>
                  <strong>
                    <Money value={ledger.data!.final_vendor_cost} />
                  </strong>
                </div>
                <div>
                  <span>Gross profit</span>
                  <strong>
                    <Money value={ledger.data!.gross_profit} />
                  </strong>
                  <div className="muted">{ledger.data!.margin_percent || "0"}% margin</div>
                </div>
              </div>
            )}
          </section>
          <section className="panel">
            <div className="panel-head">
              <h2>Documents</h2>
              <span className="eyebrow">Private downloads</span>
            </div>
            {docs.length === 0 ? (
              <Empty message="No trip documents uploaded." />
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Kind</th>
                      <th>File</th>
                      <th>Scan</th>
                      <th>Uploaded</th>
                    </tr>
                  </thead>
                  <tbody>
                    {docs.map((doc, index) => (
                      <tr key={doc.id}>
                        <td>{doc.kind}</td>
                        <td>
                          <button type="button" className="button small" onClick={() => openDocument(docs, index)}>
                            {doc.original_name}
                          </button>
                        </td>
                        <td>
                          <StatusBadge value={doc.scan_status} />
                        </td>
                        <td>
                          <DateText value={doc.created_at} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <form className="panel-body form-grid" onSubmit={upload}>
              <div className="field">
                <label>Document type</label>
                <select className="input" value={kind} onChange={(e) => setKind(e.target.value)}>
                  {["POD", "LR", "VENDOR_INVOICE", "PAYMENT_PROOF", "OTHER"].map((value) => (
                    <option key={value}>{value}</option>
                  ))}
                </select>
              </div>
              <div className="field span-2">
                <label>PDF, PNG or JPEG</label>
                <input
                  required
                  className="input"
                  type="file"
                  accept=".pdf,.png,.jpg,.jpeg"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                />
              </div>
              <div className="field">
                <label>&nbsp;</label>
                <button className="button" disabled={busy}>
                  Upload & scan
                </button>
              </div>
            </form>
          </section>
          <CommentsPanel objectType="trip" objectId={id} title="Activity discussion" />
          {audit.data && (
            <section className="panel">
              <div className="panel-head">
                <h2>Audit history</h2>
              </div>
              <div className="timeline panel-body">
                {listResults(audit.data).map((entry) => (
                  <div className="timeline-item" key={entry.id}>
                    <strong>
                      {entry.action} · {entry.actor_name}
                    </strong>
                    <small>
                      <DateText value={entry.created_at} />
                    </small>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
        <aside>
          <section className="panel">
            <div className="panel-head">
              <h2>Trip controls</h2>
            </div>
            <div className="panel-body">
              <div className="field">
                <label>Trip status</label>
                <StatusBadge value={t.status} />
              </div>
              <div className="field" style={{ marginTop: 18 }}>
                <label>POD</label>
                <StatusBadge value={t.pod_status} />
              </div>
              <div className="field" style={{ marginTop: 18 }}>
                <label>Settlement</label>
                <StatusBadge value={t.settlement_status} />
              </div>
              {!["DELIVERED", "SETTLEMENT_PENDING", "SETTLEMENT_APPROVAL_PENDING", "SETTLED"].includes(t.status) && (
                <button
                  className="button primary"
                  disabled={busy}
                  style={{ marginTop: 18 }}
                  onClick={() => run(() => api(`/trips/${id}/deliver/`, { method: "POST" }))}
                >
                  Mark delivered
                </button>
              )}
            </div>
          </section>
          {["DELIVERED", "SETTLEMENT_PENDING", "SETTLEMENT_APPROVAL_PENDING"].includes(t.status) && (
            <form className="panel" onSubmit={saveSettlement}>
              <div className="panel-head">
                <h2>Final settlement</h2>
                {settlement && <StatusBadge value={settlement.settlement_status} />}
              </div>
              <div className="panel-body">
                <div className="field">
                  <label>Final freight</label>
                  <input
                    type="number"
                    min="0"
                    className="input"
                    placeholder={settlement?.final_freight || t.vendor_freight_rate}
                    value={settlementForm.final_freight}
                    onChange={(e) =>
                      setSettlementForm({
                        ...settlementForm,
                        final_freight: e.target.value,
                      })
                    }
                  />
                </div>
                <div className="field">
                  <label>Additive charges</label>
                  <input
                    type="number"
                    min="0"
                    className="input"
                    value={settlementForm.additive_charges}
                    onChange={(e) =>
                      setSettlementForm({
                        ...settlementForm,
                        additive_charges: e.target.value,
                      })
                    }
                  />
                </div>
                <div className="field">
                  <label>Vendor deductions</label>
                  <input
                    type="number"
                    min="0"
                    className="input"
                    value={settlementForm.vendor_deductions}
                    onChange={(e) =>
                      setSettlementForm({
                        ...settlementForm,
                        vendor_deductions: e.target.value,
                      })
                    }
                  />
                </div>
                {settlement && (
                  <div className="notice" style={{ marginTop: 12 }}>
                    Final cost <Money value={settlement.total_vendor_gross_cost} />
                    <br />
                    Remaining cash <Money value={settlement.remaining_cash_payable} />
                    <br />
                    Missing: {settlement.missing_documents.join(", ") || "none"}
                  </div>
                )}
                <button className="button" disabled={busy}>
                  Calculate settlement
                </button>
                {settlement?.settlement_status === "DRAFT" && (
                  <button
                    type="button"
                    className="button primary"
                    onClick={() =>
                      run(() =>
                        api(`/settlements/${settlement.id}/submit/`, {
                          method: "POST",
                        }),
                      )
                    }
                  >
                    Submit settlement
                  </button>
                )}
                {settlement?.settlement_status === "APPROVED" && (
                  <button
                    type="button"
                    className="button primary"
                    onClick={() =>
                      run(() =>
                        api(`/settlements/${settlement.id}/finalize/`, {
                          method: "POST",
                        }),
                      )
                    }
                  >
                    Close trip
                  </button>
                )}
              </div>
            </form>
          )}{" "}
          {["DELIVERED", "SETTLEMENT_PENDING", "SETTLEMENT_APPROVAL_PENDING", "SETTLED"].includes(t.status) && (
            <form className="panel" onSubmit={saveBilling}>
              <div className="panel-head">
                <h2>Client billing</h2>
                {billing && <StatusBadge value={billing.payment_status} />}
              </div>
              <div className="panel-body">
                <div className="field">
                  <label>Billing amount</label>
                  <input
                    required
                    type="number"
                    min="0"
                    className="input"
                    placeholder={billing?.billing_amount}
                    value={billingForm.billing_amount}
                    onChange={(e) =>
                      setBillingForm({
                        ...billingForm,
                        billing_amount: e.target.value,
                      })
                    }
                  />
                </div>
                <div className="field">
                  <label>Invoice no.</label>
                  <input
                    className="input"
                    placeholder={billing?.invoice_no}
                    value={billingForm.invoice_no}
                    onChange={(e) =>
                      setBillingForm({
                        ...billingForm,
                        invoice_no: e.target.value,
                      })
                    }
                  />
                </div>
                <div className="field">
                  <label>Invoice date</label>
                  <input
                    type="date"
                    className="input"
                    value={billingForm.invoice_date}
                    onChange={(e) =>
                      setBillingForm({
                        ...billingForm,
                        invoice_date: e.target.value,
                      })
                    }
                  />
                </div>
                <div className="field">
                  <label>Status</label>
                  <select
                    className="input"
                    value={billingForm.payment_status}
                    onChange={(e) =>
                      setBillingForm({
                        ...billingForm,
                        payment_status: e.target.value,
                      })
                    }
                  >
                    {["DRAFT", "INVOICED", "PARTIALLY_RECEIVED", "RECEIVED"].map((value) => (
                      <option key={value}>{value}</option>
                    ))}
                  </select>
                </div>
                {billing && (
                  <div className="notice">
                    Profit <Money value={billing.gross_profit} /> · {billing.margin_percent}% margin
                  </div>
                )}
                <button className="button" disabled={busy}>
                  Save billing
                </button>
              </div>
            </form>
          )}
        </aside>
      </div>
      {viewer}
    </>
  );
}
