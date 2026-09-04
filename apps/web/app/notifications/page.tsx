"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, listResults } from "@/lib/api";
import type { Paginated } from "@/lib/types";
import { DateText, Empty, ErrorNotice, Loading, PageHeader, StatusBadge } from "@/components/UI";

type Message = { id: number; subject: string; body_summary: string; event_key: string; status: string; created_at: string };
type Preference = { id: number; event_key: string; channel: string; enabled: boolean };
const events = ["APPROVAL_REQUESTED", "FINANCE_READY", "APPROVAL_COMPLETED", "CHANGES_REQUESTED", "PAYMENT_COMPLETED", "SETTLEMENT_PENDING"];
const channels = ["IN_APP", "EMAIL", "WHATSAPP"];

export default function NotificationsPage() {
  const messages = useQuery({ queryKey: ["notifications"], queryFn: () => api<Paginated<Message>>("/messages/?channel=IN_APP") });
  const preferences = useQuery({ queryKey: ["notification-preferences"], queryFn: () => api<Paginated<Preference>>("/notification-preferences/?page_size=200") });
  const [error, setError] = useState<unknown>();
  const rows = messages.data ? listResults(messages.data) : [];
  const markRead = async (id: number) => { await api(`/messages/${id}/read/`, { method: "POST" }); await messages.refetch(); };
  const enabled = (event: string, channel: string) => preferences.data ? listResults(preferences.data).find((row) => row.event_key === event && row.channel === channel)?.enabled ?? true : true;
  const toggle = async (event: string, channel: string) => { setError(undefined); const current = preferences.data ? listResults(preferences.data).find((row) => row.event_key === event && row.channel === channel) : undefined; try { if (current) await api(`/notification-preferences/${current.id}/`, { method: "PATCH", body: JSON.stringify({ enabled: !current.enabled }) }); else await api("/notification-preferences/", { method: "POST", body: JSON.stringify({ event_key: event, channel, enabled: false }) }); await preferences.refetch(); } catch (reason) { setError(reason); } };
  return <><PageHeader title="Notifications" description="Approval assignments, mentions, finance-ready items, payment outcomes and settlement reminders." />{Boolean(error) && <ErrorNotice error={error} />}<section className="panel"><div className="panel-head"><h2>Delivery preferences</h2><span className="muted">Changes apply only to your account</span></div><div className="table-wrap"><table><thead><tr><th>Event</th>{channels.map((channel) => <th key={channel}>{channel.replaceAll("_", " ")}</th>)}</tr></thead><tbody>{events.map((event) => <tr key={event}><td><strong>{event.replaceAll("_", " ")}</strong></td>{channels.map((channel) => <td key={channel}><label className="actions"><input type="checkbox" className="checkbox" checked={enabled(event, channel)} onChange={() => toggle(event, channel)} /> Enabled</label></td>)}</tr>)}</tbody></table></div></section>{messages.isPending ? <Loading /> : messages.error ? <ErrorNotice error={messages.error} /> : rows.length === 0 ? <div className="panel"><Empty message="Your notification inbox is clear." /></div> : <section className="panel"><div className="timeline panel-body">{rows.map((message) => <div className="timeline-item" key={message.id}><div className="actions" style={{ justifyContent: "space-between" }}><strong>{message.subject}</strong><StatusBadge value={message.status} /></div><small><DateText value={message.created_at} /> · {message.event_key.replaceAll("_", " ")}</small><p>{message.body_summary}</p>{message.status !== "READ" && <button className="button small" onClick={() => markRead(message.id)}>Mark read</button>}</div>)}</div></section>}</>;
}
