"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import type { DocumentRecord, Payment, PendingGroup } from "@/lib/types";
import { DateText, Empty, ErrorNotice, Loading, Money, PageHeader, StatusBadge } from "@/components/UI";

function Documents({ documents, empty }: { documents: DocumentRecord[]; empty: string }) {
  if (!documents.length) return <span className="muted">{empty}</span>;
  return <div className="actions">{documents.map((doc) => <a className="button small" href={doc.download_url} key={doc.id}>{doc.kind.replaceAll("_", " ")} · {doc.original_name}</a>)}</div>;
}

function VendorPaymentGroup({ group, refresh }: { group: PendingGroup; refresh: () => void }) {
  const router = useRouter();
  const [selected, setSelected] = useState<number[]>([]);
  const [allocations, setAllocations] = useState<Record<number, { tds: string; net: string }>>({});
  const [bankAccount, setBankAccount] = useState(String(group.bank_accounts.find((row) => row.active)?.id ?? ""));
  const [utr, setUtr] = useState("");
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [proof, setProof] = useState<File | null>(null);
  const [proofId, setProofId] = useState<number | undefined>();
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const chosen = group.items.filter((item) => selected.includes(item.approval_item_id));
  const totals = chosen.reduce(
    (sum, item) => {
      const allocation = allocations[item.approval_item_id] ?? { tds: item.remaining_tds, net: item.remaining_net };
      return { gross: sum.gross + Number(allocation.tds || 0) + Number(allocation.net || 0), tds: sum.tds + Number(allocation.tds || 0), net: sum.net + Number(allocation.net || 0) };
    },
    { gross: 0, tds: 0, net: 0 },
  );
  const allocationError = chosen.find((item) => {
    const allocation = allocations[item.approval_item_id];
    if (!allocation) return false;
    const tds = Number(allocation.tds); const net = Number(allocation.net); const gross = tds + net;
    return !Number.isFinite(tds) || !Number.isFinite(net) || gross <= 0 || tds < 0 || net < 0 || tds > Number(item.remaining_tds) || net > Number(item.remaining_net) || gross > Number(item.remaining_gross) + 0.005;
  });

  const toggleItem = (item: PendingGroup["items"][number], checked: boolean) => {
    setSelected((old) => checked ? [...old, item.approval_item_id] : old.filter((id) => id !== item.approval_item_id));
    if (checked) setAllocations((old) => ({ ...old, [item.approval_item_id]: { tds: item.remaining_tds, net: item.remaining_net } }));
  };

  const pay = async () => {
    setBusy(true);
    setError(undefined);
    try {
      let uploadedProof = proofId;
      if (proof && !uploadedProof) {
        const upload = new FormData();
        upload.append("file", proof);
        upload.append("kind", "PAYMENT_PROOF");
        upload.append("object_type", "approval");
        upload.append("object_id", String(chosen[0].approval_id));
        uploadedProof = (await api<{ id: number }>("/documents/", { method: "POST", body: upload })).id;
        setProofId(uploadedProof);
      }
      const payment = await api<Payment>("/payments/", {
        method: "POST",
        body: JSON.stringify({
          vendor: group.vendor_id,
          bank_account: Number(bankAccount),
          payment_date: date,
          utr_reference: utr,
          payment_mode: "BANK_TRANSFER",
          proof_document: uploadedProof,
          allocations: chosen.map((item) => ({
            approval_item_id: item.approval_item_id,
            gross_amount_allocated: (Number(allocations[item.approval_item_id]?.tds ?? item.remaining_tds) + Number(allocations[item.approval_item_id]?.net ?? item.remaining_net)).toFixed(2),
            tds_allocated: allocations[item.approval_item_id]?.tds ?? item.remaining_tds,
            net_cash_allocated: allocations[item.approval_item_id]?.net ?? item.remaining_net,
          })),
        }),
      });
      refresh();
      router.push(`/payments/${payment.id}`);
    } catch (reason) {
      setError(reason);
      setBusy(false);
    }
  };

  return <section className="panel">
    <div className="panel-head"><div><h2>{group.vendor_name}</h2><span className="muted">{group.vendor_code} · {group.vendor_legal_name} · Cash <Money value={group.total_net} /> · TDS <Money value={group.items.reduce((sum, item) => sum + Number(item.remaining_tds), 0)} /> pending</span></div><span className="badge blue">{group.items.length} approved lines</span></div>
    {Boolean(error) && <div className="panel-body"><ErrorNotice error={error} /></div>}
    <div className="panel-body split">
      <div><h3>Vendor verification</h3><p className="muted">{group.vendor_email || "No email"} · {group.vendor_phone || "No phone"}</p><Documents documents={group.vendor_documents} empty="No clean vendor Aadhaar/PAN documents uploaded." /></div>
      <div><h3>Bank verification</h3>{group.bank_accounts.length === 0 ? <div className="notice error">No bank account is available. Add and verify a vendor account before paying.</div> : <div className="table-wrap"><table><thead><tr><th>Bank / holder</th><th>Account</th><th>IFSC</th><th>Cancelled cheque</th></tr></thead><tbody>{group.bank_accounts.map((account) => <tr key={account.id}><td><strong>{account.bank_name}</strong><div className="muted">{account.account_holder}</div></td><td>{account.masked_account_number}</td><td>{account.ifsc_code}</td><td>{account.cancelled_cheque_documents?.length ? <Documents documents={account.cancelled_cheque_documents} empty="" /> : <StatusBadge value="MISSING" />}</td></tr>)}</tbody></table></div>}</div>
    </div>
    <div className="table-wrap"><table><thead><tr><th></th><th>Trip / approval</th><th>Trip details</th><th>Driver verification</th><th className="money">Freight (100%)</th><th className="money">Advance</th><th className="money">Freight balance</th><th className="money">Due / TDS / cash</th></tr></thead><tbody>{group.items.map((item) => <tr key={item.approval_item_id}>
      <td><input type="checkbox" className="checkbox" checked={selected.includes(item.approval_item_id)} onChange={(event) => toggleItem(item, event.target.checked)} /></td>
      <td><strong>{item.trip_no}</strong><div>{item.approval_no}</div><div className="muted">Approved <DateText value={item.approved_at} /></div></td>
      <td>{item.route}<div className="muted">{item.client_name} · {item.vehicle_no} ({item.vehicle_type})</div><div className="muted">Deploy <DateText value={item.deployment_date} /> · Created <DateText value={item.trip_created_at} /></div><Documents documents={item.trip_documents} empty="No trip docs" /></td>
      <td><strong>{item.driver_name}</strong><div className="muted">{item.driver_phone}</div><Documents documents={item.driver_documents} empty="No driver Aadhaar/DL/PAN" /></td>
      <td className="money"><Money value={item.freight_100} /></td>
      <td className="money"><Money value={item.advance_amount} /><div className="muted">{item.advance_percent}%</div></td>
      <td className="money"><Money value={item.freight_balance_after_advance} /></td>
      <td className="money"><strong><Money value={item.remaining_gross} /></strong><div className="muted">TDS <Money value={item.remaining_tds} /> · Cash <Money value={item.remaining_net} /></div></td>
    </tr>)}</tbody></table></div>
    {selected.length > 0 && <div className="panel-body" style={{ background: "#fff8f5", borderTop: "1px solid var(--line)" }}>
      <h3>Allocate this payment</h3><p className="muted">Enter the cash and TDS being recorded now. The unpaid balance stays in this queue for the next payment.</p>
      <div className="table-wrap"><table><thead><tr><th>Trip</th><th className="money">Maximum due</th><th className="money">TDS now</th><th className="money">Cash now</th><th className="money">Gross now</th></tr></thead><tbody>{chosen.map((item) => { const allocation = allocations[item.approval_item_id] ?? { tds: item.remaining_tds, net: item.remaining_net }; return <tr key={item.approval_item_id}><td><strong>{item.trip_no}</strong><div className="muted">{item.approval_no}</div></td><td className="money"><Money value={item.remaining_gross} /></td><td><input aria-label={`TDS for ${item.trip_no}`} className="input" type="number" min="0" max={item.remaining_tds} step="0.01" value={allocation.tds} onChange={(e) => setAllocations((old) => ({ ...old, [item.approval_item_id]: { ...allocation, tds: e.target.value } }))} /></td><td><input aria-label={`Cash for ${item.trip_no}`} className="input" type="number" min="0" max={item.remaining_net} step="0.01" value={allocation.net} onChange={(e) => setAllocations((old) => ({ ...old, [item.approval_item_id]: { ...allocation, net: e.target.value } }))} /></td><td className="money"><Money value={Number(allocation.tds || 0) + Number(allocation.net || 0)} /></td></tr>; })}</tbody></table></div>
      {allocationError && <div className="notice error">Allocation for {allocationError.trip_no} must be positive and cannot exceed its remaining gross, TDS, or cash balances.</div>}
      <div className="form-grid">
      <div className="field"><label>Payment date</label><input className="input" type="date" value={date} onChange={(event) => setDate(event.target.value)} /></div>
      <div className="field"><label>Pay to verified bank</label><select required className="input" value={bankAccount} onChange={(event) => setBankAccount(event.target.value)}><option value="">Select bank account</option>{group.bank_accounts.filter((row) => row.active).map((row) => <option value={row.id} key={row.id}>{row.bank_name} · {row.masked_account_number} · {row.ifsc_code}</option>)}</select></div>
      <div className="field span-2"><label>UTR / bank reference</label><input className="input" required value={utr} onChange={(event) => setUtr(event.target.value)} placeholder="Enter confirmed reference" /></div>
      <div className="field span-2"><label>Payment proof</label><input className="input" type="file" accept=".pdf,.png,.jpg,.jpeg" onChange={(event) => { setProof(event.target.files?.[0] ?? null); setProofId(undefined); }} /></div>
    </div><div className="actions" style={{ justifyContent: "flex-end", marginTop: 12 }}><span className="muted">Gross <Money value={totals.gross} /> · TDS <Money value={totals.tds} /> · Net cash <Money value={totals.net} /></span><button className="button primary" disabled={!utr.trim() || !bankAccount || busy || Boolean(allocationError) || totals.gross <= 0} onClick={pay}>{busy ? "Recording…" : "Record paid transaction"}</button></div></div>}
  </section>;
}

export default function FinanceQueuePage() {
  const queue = useQuery({ queryKey: ["finance-pending"], queryFn: () => api<PendingGroup[]>("/finance/pending/") });
  return <><PageHeader title="Finance review & pending payments" description="Approved payment requests with full trip, KYC, bank and liability evidence in one place." /><div className="notice">Review vendor/driver identity documents, the masked bank account and cancelled cheque, then select approved lines to pay. Full account numbers are never shown.</div>{queue.isPending ? <Loading /> : queue.error ? <ErrorNotice error={queue.error} /> : queue.data!.length === 0 ? <div className="panel"><Empty message="No approved unpaid items are waiting for finance." /></div> : queue.data!.map((group) => <VendorPaymentGroup group={group} key={group.vendor_id} refresh={() => queue.refetch()} />)}</>;
}
