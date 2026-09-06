"use client";

import { FormEvent, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";
import { ErrorNotice, Loading, PageHeader, StatusBadge } from "@/components/UI";
import { AdminSettings } from "@/components/AdminSettings";
import { SecuritySettings } from "@/components/SecuritySettings";

type Settings = {
  id: number;
  name: string;
  currency: string;
  timezone: string;
  default_advance_percent: string;
  default_tds_rate: string;
  default_tds_policy: string;
  allow_self_approval: boolean;
  require_payment_proof: boolean;
};
type Matrix = Record<string, string[]>;

export default function SettingsPage() {
  const query = useQuery({ queryKey: ["settings"], queryFn: () => api<Settings>("/settings/") });
  const matrix = useQuery({ queryKey: ["permission-matrix"], queryFn: () => api<Matrix>("/permission-matrix/") });
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<User>("/auth/me/") });
  const [edits, setForm] = useState<Partial<Settings>>({});
  const [message, setMessage] = useState("");
  const [error, setError] = useState<unknown>();
  const save = async (event: FormEvent) => {
    event.preventDefault();
    setError(undefined);
    setMessage("");
    try {
      const updated = await api<Settings>("/settings/", { method: "PATCH", body: JSON.stringify(form) });
      setForm(updated);
      setMessage("Organization financial policy saved and will apply to new approval snapshots.");
    } catch (reason) {
      setError(reason);
    }
  };
  if (query.isPending) return <Loading />;
  if (query.error) return <ErrorNotice error={query.error} />;
  const admin = me.data?.role === "ADMIN";
  const form = { ...query.data!, ...edits };
  return (
    <>
      <PageHeader
        title="Settings & approval matrix"
        description="Organization defaults are resolved server-side and snapshotted on each submitted approval."
      />
      {message && <div className="notice">{message}</div>}
      {Boolean(error) && <ErrorNotice error={error} />}
      <form className="panel" onSubmit={save}>
        <div className="panel-head">
          <h2>Financial policy</h2>
          <StatusBadge value={admin ? "ADMIN EDITABLE" : "READ ONLY"} />
        </div>
        <div className="panel-body form-grid">
          <div className="field span-2">
            <label>Organization</label>
            <input
              className="input"
              disabled={!admin}
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </div>
          <div className="field">
            <label>Currency</label>
            <input
              className="input"
              disabled={!admin}
              value={form.currency}
              onChange={(e) => setForm({ ...form, currency: e.target.value })}
            />
          </div>
          <div className="field">
            <label>Business timezone</label>
            <input
              className="input"
              disabled={!admin}
              value={form.timezone}
              onChange={(e) => setForm({ ...form, timezone: e.target.value })}
            />
          </div>
          <div className="field">
            <label>Default advance %</label>
            <input
              type="number"
              min="0"
              max="100"
              step=".01"
              className="input"
              disabled={!admin}
              value={form.default_advance_percent}
              onChange={(e) => setForm({ ...form, default_advance_percent: e.target.value })}
            />
          </div>
          <div className="field">
            <label>Default TDS rate %</label>
            <input
              type="number"
              min="0"
              max="100"
              step=".01"
              className="input"
              disabled={!admin}
              value={form.default_tds_rate}
              onChange={(e) => setForm({ ...form, default_tds_rate: e.target.value })}
            />
          </div>
          <div className="field span-2">
            <label>Default TDS policy</label>
            <select
              className="input"
              disabled={!admin}
              value={form.default_tds_policy}
              onChange={(e) => setForm({ ...form, default_tds_policy: e.target.value })}
            >
              <option>PER_PAYMENT_TAXABLE_AMOUNT</option>
              <option>FULL_FREIGHT_AT_FIRST_ADVANCE</option>
              <option>CUMULATIVE_TRIP_LIABILITY</option>
              <option>MANUAL_WITH_APPROVAL</option>
            </select>
          </div>
          <label className="field" style={{ flexDirection: "row", alignItems: "center" }}>
            <input
              type="checkbox"
              className="checkbox"
              disabled={!admin}
              checked={form.allow_self_approval}
              onChange={(e) => setForm({ ...form, allow_self_approval: e.target.checked })}
            />{" "}
            Allow self-approval
          </label>
          <label className="field" style={{ flexDirection: "row", alignItems: "center" }}>
            <input
              type="checkbox"
              className="checkbox"
              disabled={!admin}
              checked={form.require_payment_proof}
              onChange={(e) => setForm({ ...form, require_payment_proof: e.target.checked })}
            />{" "}
            Require payment proof
          </label>
        </div>
        {admin && (
          <div className="panel-body" style={{ paddingTop: 0 }}>
            <button className="button primary">Save policy</button>
          </div>
        )}
      </form>
      <SecuritySettings mfaEnabled={Boolean(me.data?.mfa_enabled)} />
      {admin && <AdminSettings />}
      <section className="panel">
        <div className="panel-head">
          <h2>Server-side role capabilities</h2>
        </div>
        {matrix.isPending ? (
          <Loading />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Role</th>
                  <th>Authoritative capabilities</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(matrix.data ?? {}).map(([role, capabilities]) => (
                  <tr key={role}>
                    <td>
                      <StatusBadge value={role} />
                    </td>
                    <td>{capabilities.join(" · ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
