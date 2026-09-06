"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useMemo, useState } from "react";
import { api, apiAll } from "@/lib/api";
import type { Approval, Trip } from "@/lib/types";
import { DateText, Empty, ErrorNotice, Loading, Money, PageHeader } from "@/components/UI";

export default function ApprovalBuilderPage() {
  const router = useRouter();
  const [selected, setSelected] = useState<number[]>([]);
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const [edits, setEdits] = useState<Record<number, { vendor_freight_rate: string; advance_percent: string }>>({});
  const trips = useQuery({ queryKey: ["eligible-trips"], queryFn: () => apiAll<Trip>("/trips/?status=READY") });
  const allRows = useMemo(() => trips.data ?? [], [trips.data]);
  const rows = useMemo(() => allRows.filter((row) => !row.active_approval), [allRows]);
  const locked = allRows.filter((row) => row.active_approval);
  const chosen = useMemo(() => rows.filter((row) => selected.includes(row.id)), [rows, selected]);
  const totals = chosen.reduce(
    (sum, row) => ({
      gross: sum.gross + Number(row.calculation.gross_requested),
      tds: sum.tds + Number(row.calculation.tds_this_payment),
      net: sum.net + Number(row.calculation.net_requested),
    }),
    { gross: 0, tds: 0, net: 0 },
  );
  const applyEdits = async () => {
    for (const trip of chosen) {
      const values = edits[trip.id];
      if (!values) continue;
      const changes = Object.fromEntries(
        Object.entries(values).filter(
          ([key, value]) => value.trim() === "" || Number(value) !== Number(trip[key as keyof typeof values]),
        ),
      );
      if (Object.keys(changes).length)
        await api(`/trips/${trip.id}/`, { method: "PATCH", body: JSON.stringify(changes) });
    }
  };
  const refreshPreview = async () => {
    setBusy(true);
    setError(undefined);
    try {
      await applyEdits();
      setEdits({});
      await trips.refetch();
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(false);
    }
  };
  const submit = async () => {
    setBusy(true);
    setError(undefined);
    try {
      await applyEdits();
      const batch = await api<Approval>("/approval-batches/", {
        method: "POST",
        body: JSON.stringify({ trip_ids: chosen.map((trip) => trip.id), submit: true }),
      });
      router.push(`/approvals/${batch.id}`);
    } catch (reason) {
      setError(reason);
      setBusy(false);
      await trips.refetch();
    }
  };
  return (
    <>
      <PageHeader
        title="Payment approval builder"
        description="Select eligible trips—even across vendors. Review or adjust the permitted financial inputs before the server locks each approval snapshot."
      />
      {locked.length > 0 && (
        <div className="notice">
          <strong>Trips already in an approval</strong>
          {locked.map((trip) => (
            <div key={trip.id}>
              {trip.trip_no}:{" "}
              {trip.active_approval?.id ? (
                <Link href={`/approvals/${trip.active_approval.id}`}>
                  Open {trip.active_approval.approval_no} ({trip.active_approval.status})
                </Link>
              ) : (
                <span>{trip.active_approval?.approval_no} — contact its requester</span>
              )}
            </div>
          ))}
          <div>Open an existing draft to review and submit it; these trips cannot be added to another approval.</div>
        </div>
      )}
      <div className="notice">
        A batch may contain multiple vendors. Finance will still receive separate vendor groups. Edited freight and
        advance values are server-validated and recalculated before submission.
      </div>
      {Boolean(error) && <ErrorNotice error={error} />}
      <section className="panel">
        <div className="panel-head">
          <h2>Eligible trip lines</h2>
          <span>{selected.length} selected</span>
        </div>
        {trips.isPending ? (
          <Loading />
        ) : trips.error ? (
          <ErrorNotice error={trips.error} />
        ) : rows.length === 0 ? (
          <Empty message="No READY trips are available for approval." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th></th>
                  <th>Trip</th>
                  <th>Route</th>
                  <th>Vendor</th>
                  <th>Vehicle</th>
                  <th className="money">Freight (editable)</th>
                  <th>Advance %</th>
                  <th className="money">Gross request</th>
                  <th className="money">TDS</th>
                  <th className="money">Net</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((trip) => {
                  const values = edits[trip.id] ?? {
                    vendor_freight_rate: trip.vendor_freight_rate,
                    advance_percent: trip.advance_percent,
                  };
                  const active = selected.includes(trip.id);
                  return (
                    <tr key={trip.id}>
                      <td>
                        <input
                          className="checkbox"
                          type="checkbox"
                          disabled={busy}
                          checked={active}
                          onChange={(e) => {
                            setSelected((old) =>
                              e.target.checked ? [...old, trip.id] : old.filter((id) => id !== trip.id),
                            );
                          }}
                        />
                      </td>
                      <td>
                        <strong>{trip.trip_no}</strong>
                        <div className="muted">
                          <DateText value={trip.deployment_date} />
                        </div>
                      </td>
                      <td>
                        {trip.origin} → {trip.destination}
                      </td>
                      <td>{trip.vendor_name}</td>
                      <td>{trip.vehicle_no}</td>
                      <td>
                        {active ? (
                          <input
                            aria-label={`Freight for ${trip.trip_no}`}
                            className="input"
                            disabled={busy}
                            type="number"
                            min="0"
                            step="0.01"
                            value={values.vendor_freight_rate}
                            onChange={(e) =>
                              setEdits((old) => ({
                                ...old,
                                [trip.id]: { ...values, vendor_freight_rate: e.target.value },
                              }))
                            }
                          />
                        ) : (
                          <Money value={trip.vendor_freight_rate} />
                        )}
                      </td>
                      <td>
                        {active ? (
                          <input
                            aria-label={`Advance percent for ${trip.trip_no}`}
                            className="input"
                            disabled={busy}
                            type="number"
                            min="0"
                            max="100"
                            step="0.01"
                            value={values.advance_percent}
                            onChange={(e) =>
                              setEdits((old) => ({ ...old, [trip.id]: { ...values, advance_percent: e.target.value } }))
                            }
                          />
                        ) : (
                          `${trip.advance_percent}%`
                        )}
                      </td>
                      <td className="money">
                        <Money value={trip.calculation.gross_requested} />
                      </td>
                      <td className="money">
                        <Money value={trip.calculation.tds_this_payment} />
                      </td>
                      <td className="money">
                        <strong>
                          <Money value={trip.calculation.net_requested} />
                        </strong>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <div className="totals">
          <div className="total">
            <span>Selected lines</span>
            <strong>{selected.length}</strong>
          </div>
          <div className="total">
            <span>Current gross preview</span>
            <strong>
              <Money value={totals.gross} />
            </strong>
          </div>
          <div className="total">
            <span>TDS</span>
            <strong>
              <Money value={totals.tds} />
            </strong>
          </div>
          <div className="total">
            <span>Net</span>
            <strong>
              <Money value={totals.net} />
            </strong>
          </div>
        </div>
      </section>
      <div className="actions" style={{ justifyContent: "flex-end" }}>
        <button className="button" disabled={!chosen.length || busy} onClick={refreshPreview}>
          Apply edits & refresh preview
        </button>
        <button className="button primary" disabled={!chosen.length || busy} onClick={submit}>
          {busy ? "Submitting…" : "Create & submit approval"}
        </button>
      </div>
    </>
  );
}
