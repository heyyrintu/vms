"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Indent, Trip } from "@/lib/types";
import { DateText, Empty, ErrorNotice, Loading, StatusBadge } from "@/components/UI";

export function TripIndentsPanel({ trip, onChanged }: { trip: Trip; onChanged: () => Promise<unknown> | void }) {
  const suggestions = useQuery({
    queryKey: ["trip-indent-suggestions", trip.id],
    queryFn: () => api<Indent[]>(`/trips/${trip.id}/indent-suggestions/`),
  });
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<unknown>();
  const assigned = trip.indent_details ?? [];
  const update = async (ids: number[], busy: number) => {
    setBusyId(busy);
    setError(undefined);
    try {
      await api(`/trips/${trip.id}/`, { method: "PATCH", body: JSON.stringify({ indent_ids: ids }) });
      await onChanged();
      await suggestions.refetch();
    } catch (reason) {
      setError(reason);
    } finally {
      setBusyId(null);
    }
  };
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Indents on this trip</h2>
        <span className="eyebrow">{trip.indent_count} linked</span>
      </div>
      {Boolean(error) && (
        <div className="panel-body">
          <ErrorNotice error={error} />
        </div>
      )}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Role</th>
              <th>Challan / timestamp</th>
              <th>Ship-to party</th>
              <th>Route</th>
              <th>Item</th>
              <th className="money">Qty LTR</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {assigned.map((row, index) => (
              <tr key={row.id}>
                <td>
                  <StatusBadge value={index === 0 ? "PRIMARY" : "ADDITIONAL"} />
                </td>
                <td>
                  <strong>{row.challan_no || row.indent_no}</strong>
                  <div className="muted">
                    <DateText value={row.challan_datetime || row.indent_date} />
                  </div>
                </td>
                <td>
                  {row.ship_to_party_name || "—"}
                  <div className="muted">{row.ship_to_party_code}</div>
                </td>
                <td>
                  {row.origin} → {row.destination}
                </td>
                <td>{row.item || "—"}</td>
                <td className="money">{row.quantity_ltrs || "—"}</td>
                <td>
                  {assigned.length > 1 && (
                    <button
                      className="button small"
                      disabled={busyId === row.id}
                      onClick={() =>
                        update(
                          assigned.filter((item) => item.id !== row.id).map((item) => item.id),
                          row.id,
                        )
                      }
                    >
                      Remove
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="panel-head" style={{ borderTop: "1px solid var(--border)" }}>
        <div>
          <h2>Suggested additional indents</h2>
          <div className="muted">Ranked by client, route, date and vehicle type.</div>
        </div>
      </div>
      {suggestions.isPending ? (
        <Loading />
      ) : suggestions.error ? (
        <ErrorNotice error={suggestions.error} />
      ) : !suggestions.data?.length ? (
        <Empty message="No other open indents are available for this client." />
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Challan</th>
                <th>Party / route</th>
                <th>Why suggested</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {suggestions.data.slice(0, 8).map((row) => (
                <tr key={row.id}>
                  <td>
                    <strong>{row.challan_no || row.indent_no}</strong>
                    <div className="muted">
                      <DateText value={row.challan_datetime || row.indent_date} />
                    </div>
                  </td>
                  <td>
                    {row.ship_to_party_name || "—"}
                    <div className="muted">
                      {row.origin} → {row.destination}
                    </div>
                  </td>
                  <td>{row.match_reasons?.length ? row.match_reasons.join(", ") : "Same client"}</td>
                  <td>
                    <button
                      className="button small primary"
                      disabled={busyId === row.id}
                      onClick={() => update([...assigned.map((item) => item.id), row.id], row.id)}
                    >
                      + Add to trip
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
