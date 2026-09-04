"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import type { Approval, User } from "@/lib/types";
import { CommentsPanel } from "@/components/CommentsPanel";
import { ContextDocuments } from "@/components/ContextDocuments";
import { DateText, ErrorNotice, Loading, Money, PageHeader, StatusBadge } from "@/components/UI";

export default function ApprovalDetailPage() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<number[]>([]);
  const [reason, setReason] = useState("");
  const batch = useQuery({ queryKey: ["approval", id], queryFn: () => api<Approval>(`/approval-batches/${id}/`) });
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<User>("/auth/me/") });
  const decision = useMutation({
    mutationFn: (value: string) => api<Approval>(`/approval-batches/${id}/decide/`, { method: "POST", body: JSON.stringify({ decision: value, item_ids: selected.length ? selected : undefined, comment: reason }) }),
    onSuccess: (data) => { queryClient.setQueryData(["approval", id], data); setSelected([]); setReason(""); queryClient.invalidateQueries({ queryKey: ["approvals"] }); },
  });
  if (batch.isPending) return <Loading />;
  if (batch.error) return <ErrorNotice error={batch.error} />;
  const b = batch.data!;
  const stage = b.stage_decisions.find((value) => value.sequence === b.current_stage);
  const canDecide = me.data?.role === stage?.role || me.data?.role === "ADMIN";
  return <>
    <PageHeader title={b.approval_no} description={`${b.client_name} · ${b.purpose.replaceAll("_", " ")} · Revision ${b.revision_no}`}><StatusBadge value={b.status} /></PageHeader>
    {decision.error && <ErrorNotice error={decision.error} />}
    <div className="summary-strip"><div><span>Trip lines</span><strong>{b.items.length}</strong></div><div><span>Gross request</span><strong><Money value={b.gross_requested} /></strong></div><div><span>TDS withholding</span><strong><Money value={b.tds_requested} /></strong></div><div><span>Net cash request</span><strong><Money value={b.net_requested} /></strong></div></div>
    <section className="panel"><div className="panel-head"><h2>{b.approval_rule_snapshot.rule_name || "Approval stages"}</h2><span className="eyebrow">Current stage {b.current_stage}</span></div><div className="table-wrap"><table><thead><tr><th>Sequence</th><th>Stage</th><th>Role</th><th>Decision</th></tr></thead><tbody>{b.stage_decisions.map((row) => <tr key={row.id}><td>{row.sequence}</td><td>{row.label}</td><td>{row.role}</td><td><StatusBadge value={row.status} /> {row.decided_by_name}</td></tr>)}</tbody></table></div>{b.revision_diff.length > 0 && <div className="panel-body notice"><strong>Revision changes</strong>{b.revision_diff.map((row, index) => <div key={index}>{row.field}: {row.old || "—"} → {row.new}</div>)}</div>}</section>
    <div className="split"><div>
      <section className="panel"><div className="panel-head"><h2>Trip lines</h2><span className="muted">Select lines for a partial final-stage decision</span></div><div className="table-wrap"><table><thead><tr><th></th><th>Trip</th><th>Vendor / route</th><th className="money">Gross</th><th className="money">TDS</th><th className="money">Net</th><th>Status</th></tr></thead><tbody>{b.items.map((item) => <tr key={item.id}><td><input className="checkbox" type="checkbox" disabled={item.item_status !== "PENDING"} checked={selected.includes(item.id)} onChange={(e) => setSelected((old) => e.target.checked ? [...old, item.id] : old.filter((value) => value !== item.id))} /></td><td><strong>{item.trip_no}</strong></td><td>{item.vendor_name}<div className="muted">{item.route}</div></td><td className="money"><Money value={item.gross_requested} /></td><td className="money"><Money value={item.tds_this_request} /></td><td className="money"><strong><Money value={item.net_requested} /></strong></td><td><StatusBadge value={item.item_status} /></td></tr>)}</tbody></table></div></section>
      {canDecide && ["PENDING", "PARTIALLY_APPROVED"].includes(b.status) && <section className="panel"><div className="panel-head"><h2>{stage?.label || "Approval decision"}</h2></div><div className="panel-body"><div className="field"><label>Reason / approver note (required for reject or send back)</label><textarea className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Record the decision context…" /></div><div className="actions" style={{ marginTop: 12 }}><button className="button primary" onClick={() => decision.mutate("APPROVE")} disabled={decision.isPending}>Approve {selected.length ? "selected" : "stage"}</button><button className="button" onClick={() => decision.mutate("SEND_BACK")} disabled={!reason.trim() || decision.isPending}>Send back</button><button className="button danger" onClick={() => decision.mutate("REJECT")} disabled={!reason.trim() || decision.isPending}>Reject</button></div></div></section>}
    </div><aside>
      <ContextDocuments objectType="approval" objectId={id} />
      <section className="panel"><div className="panel-head"><h2>Approval activity</h2></div><div className="timeline panel-body">{b.actions.map((action) => <div className="timeline-item" key={action.id}><strong>{action.action.replaceAll("_", " ")} · {action.actor_name}</strong><small><DateText value={action.created_at} /></small>{action.comment && <p>{action.comment}</p>}</div>)}</div></section>
      <CommentsPanel objectType="approval" objectId={id} title="Comments, replies & files" />
    </aside></div>
  </>;
}
