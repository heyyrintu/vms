"use client";

import { FormEvent, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ErrorNotice, StatusBadge } from "@/components/UI";
import { api, listResults } from "@/lib/api";
import type { Client, Paginated, User } from "@/lib/types";

type Rule = {
  id: number;
  name: string;
  purpose: string;
  min_amount: string;
  max_amount?: string;
  active: boolean;
  stages: Array<{ sequence: number; role: string; label: string }>;
};

type Template = {
  id: number;
  event_key: string;
  channel: string;
  subject_template: string;
  body_template: string;
  enabled: boolean;
};

const roles = ["OPERATIONS", "APPROVER", "FINANCE", "MANAGEMENT", "TRANSPORTER", "ADMIN"];
const templateEvents = [
  "APPROVAL_REQUESTED",
  "FINANCE_READY",
  "APPROVAL_COMPLETED",
  "CHANGES_REQUESTED",
  "PAYMENT_COMPLETED",
  "SETTLEMENT_PENDING",
];

export function AdminSettings() {
  const users = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => api<Paginated<User & { is_active: boolean; mfa_enabled: boolean }>>("/users/?page_size=200"),
  });
  const rules = useQuery({
    queryKey: ["approval-rules"],
    queryFn: () => api<Paginated<Rule>>("/approval-rules/?page_size=200"),
  });
  const templates = useQuery({
    queryKey: ["notification-templates"],
    queryFn: () => api<Paginated<Template>>("/notification-templates/?page_size=200"),
  });
  const clients = useQuery({
    queryKey: ["admin-clients"],
    queryFn: () => api<Paginated<Client>>("/clients/?page_size=200"),
  });
  const [user, setUser] = useState({
    username: "",
    email: "",
    whatsapp_phone: "",
    first_name: "",
    role: "OPERATIONS",
    password: "",
  });
  const [rule, setRule] = useState({
    name: "",
    min_amount: "0",
    max_amount: "",
    roles: "APPROVER",
  });
  const [editingRuleId, setEditingRuleId] = useState<number | null>(null);
  const [template, setTemplate] = useState({
    event_key: "APPROVAL_REQUESTED",
    channel: "IN_APP",
    subject_template: "",
    body_template: "Approval {reference} requires attention. Open securely: {action_url}",
    enabled: true,
  });
  const [editingTemplateId, setEditingTemplateId] = useState<number | null>(null);
  const [error, setError] = useState<unknown>();
  const [client, setClient] = useState({ code: "", name: "", default_branch: "Sonipat", active: true });

  const toggleRecord = async (path: string, field: string, value: boolean, refresh: () => Promise<unknown>) => {
    setError(undefined);
    try {
      await api(path, { method: "PATCH", body: JSON.stringify({ [field]: !value }) });
      await refresh();
    } catch (reason) {
      setError(reason);
    }
  };
  const createClient = async (event: FormEvent) => {
    event.preventDefault();
    setError(undefined);
    try {
      await api("/clients/", { method: "POST", body: JSON.stringify(client) });
      setClient({ ...client, code: "", name: "" });
      await clients.refetch();
    } catch (reason) {
      setError(reason);
    }
  };

  const createUser = async (event: FormEvent) => {
    event.preventDefault();
    setError(undefined);
    try {
      await api("/users/", { method: "POST", body: JSON.stringify(user) });
      setUser({ ...user, username: "", email: "", whatsapp_phone: "", first_name: "", password: "" });
      await users.refetch();
    } catch (reason) {
      setError(reason);
    }
  };

  const updateUserContacts = async (event: FormEvent<HTMLFormElement>, userId: number) => {
    event.preventDefault();
    setError(undefined);
    const values = new FormData(event.currentTarget);
    try {
      await api(`/users/${userId}/`, {
        method: "PATCH",
        body: JSON.stringify({
          email: values.get("email"),
          whatsapp_phone: values.get("whatsapp_phone"),
          role: values.get("role"),
        }),
      });
      await users.refetch();
    } catch (reason) {
      setError(reason);
    }
  };

  const createRule = async (event: FormEvent) => {
    event.preventDefault();
    setError(undefined);
    const stageRoles = rule.roles
      .split(",")
      .map((value) => value.trim().toUpperCase())
      .filter(Boolean);
    try {
      await api(editingRuleId ? `/approval-rules/${editingRuleId}/` : "/approval-rules/", {
        method: editingRuleId ? "PATCH" : "POST",
        body: JSON.stringify({
          name: rule.name,
          purpose: "ADVANCE",
          min_amount: rule.min_amount,
          max_amount: rule.max_amount || null,
          active: true,
          stages: stageRoles.map((role, index) => ({
            sequence: index + 1,
            role,
            label: `${role.replaceAll("_", " ")} approval`,
          })),
        }),
      });
      setRule({ ...rule, name: "" });
      setEditingRuleId(null);
      await rules.refetch();
    } catch (reason) {
      setError(reason);
    }
  };

  const createTemplate = async (event: FormEvent) => {
    event.preventDefault();
    setError(undefined);
    try {
      await api(editingTemplateId ? `/notification-templates/${editingTemplateId}/` : "/notification-templates/", {
        method: editingTemplateId ? "PATCH" : "POST",
        body: JSON.stringify(template),
      });
      setEditingTemplateId(null);
      await templates.refetch();
    } catch (reason) {
      setError(reason);
    }
  };

  return (
    <>
      {Boolean(error) && <ErrorNotice error={error} />}
      <section className="panel">
        <div className="panel-head">
          <h2>User and role management</h2>
          <span className="eyebrow">Administrator</span>
        </div>
        <form className="panel-body form-grid" onSubmit={createUser}>
          <div className="field">
            <label>Username</label>
            <input
              required
              className="input"
              value={user.username}
              onChange={(event) => setUser({ ...user, username: event.target.value })}
            />
          </div>
          <div className="field">
            <label>Name</label>
            <input
              className="input"
              value={user.first_name}
              onChange={(event) => setUser({ ...user, first_name: event.target.value })}
            />
          </div>
          <div className="field">
            <label>Email</label>
            <input
              type="email"
              className="input"
              value={user.email}
              onChange={(event) => setUser({ ...user, email: event.target.value })}
            />
          </div>
          <div className="field">
            <label>WhatsApp number</label>
            <input
              className="input"
              inputMode="tel"
              placeholder="919876543210"
              value={user.whatsapp_phone}
              onChange={(event) => setUser({ ...user, whatsapp_phone: event.target.value })}
            />
          </div>
          <div className="field">
            <label>Role</label>
            <select
              className="input"
              value={user.role}
              onChange={(event) => setUser({ ...user, role: event.target.value })}
            >
              {roles.map((role) => (
                <option key={role}>{role}</option>
              ))}
            </select>
          </div>
          <div className="field span-2">
            <label>Temporary password</label>
            <input
              required
              minLength={12}
              type="password"
              className="input"
              value={user.password}
              onChange={(event) => setUser({ ...user, password: event.target.value })}
            />
          </div>
          <div className="field">
            <label>&nbsp;</label>
            <button className="button primary">Create user</button>
          </div>
        </form>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>User</th>
                <th>Email, WhatsApp and role</th>
                <th>MFA</th>
                <th>Status / action</th>
              </tr>
            </thead>
            <tbody>
              {users.data &&
                listResults(users.data).map((row) => (
                  <tr key={row.id}>
                    <td>
                      {row.first_name || row.username}
                      <div className="muted">{row.username}</div>
                    </td>
                    <td>
                      <form className="actions" onSubmit={(event) => updateUserContacts(event, row.id)}>
                        <input
                          aria-label={`${row.username} email`}
                          name="email"
                          type="email"
                          className="input"
                          defaultValue={row.email}
                          placeholder="Email"
                        />
                        <input
                          aria-label={`${row.username} WhatsApp number`}
                          name="whatsapp_phone"
                          className="input"
                          inputMode="tel"
                          defaultValue={row.whatsapp_phone}
                          placeholder="WhatsApp with country code"
                        />
                        <select
                          aria-label={`${row.username} role`}
                          name="role"
                          className="input"
                          defaultValue={row.role}
                        >
                          {roles.map((role) => (
                            <option key={role}>{role}</option>
                          ))}
                        </select>
                        <button className="button small">Save</button>
                      </form>
                    </td>
                    <td>{row.mfa_enabled ? "Enabled" : "Not enabled"}</td>
                    <td>
                      <StatusBadge value={row.is_active ? "ACTIVE" : "INACTIVE"} />
                      <button
                        className="button small"
                        onClick={() =>
                          toggleRecord(`/users/${row.id}/`, "is_active", Boolean(row.is_active), () => users.refetch())
                        }
                      >
                        {row.is_active ? "Deactivate" : "Activate"}
                      </button>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="panel">
        <div className="panel-head">
          <h2>Client master</h2>
          <span className="eyebrow">Branches and indent ownership</span>
        </div>
        <form className="panel-body form-grid" onSubmit={createClient}>
          <div className="field">
            <label>Client code</label>
            <input
              required
              className="input"
              value={client.code}
              onChange={(e) => setClient({ ...client, code: e.target.value })}
            />
          </div>
          <div className="field span-2">
            <label>Client name</label>
            <input
              required
              className="input"
              value={client.name}
              onChange={(e) => setClient({ ...client, name: e.target.value })}
            />
          </div>
          <div className="field">
            <label>Default branch</label>
            <input
              required
              className="input"
              value={client.default_branch}
              onChange={(e) => setClient({ ...client, default_branch: e.target.value })}
            />
          </div>
          <button className="button primary">Add client</button>
        </form>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Code</th>
                <th>Client / default branch</th>
                <th>Status / action</th>
              </tr>
            </thead>
            <tbody>
              {clients.data &&
                listResults(clients.data).map((row) => (
                  <tr key={row.id}>
                    <td>
                      <strong>{row.code}</strong>
                    </td>
                    <td>
                      <form
                        className="actions"
                        onSubmit={async (event) => {
                          event.preventDefault();
                          const values = new FormData(event.currentTarget);
                          try {
                            await api(`/clients/${row.id}/`, {
                              method: "PATCH",
                              body: JSON.stringify({
                                name: values.get("name"),
                                default_branch: values.get("default_branch"),
                              }),
                            });
                            await clients.refetch();
                          } catch (reason) {
                            setError(reason);
                          }
                        }}
                      >
                        <input
                          aria-label={`${row.code} client name`}
                          className="input"
                          name="name"
                          defaultValue={row.name}
                        />
                        <input
                          aria-label={`${row.code} default branch`}
                          className="input"
                          name="default_branch"
                          defaultValue={row.default_branch}
                        />
                        <button className="button small">Save</button>
                      </form>
                    </td>
                    <td>
                      <StatusBadge value={row.active ? "ACTIVE" : "INACTIVE"} />
                      <button
                        className="button small"
                        onClick={() =>
                          toggleRecord(`/clients/${row.id}/`, "active", row.active, () => clients.refetch())
                        }
                      >
                        {row.active ? "Deactivate" : "Activate"}
                      </button>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="panel">
        <div className="panel-head">
          <h2>Sequential approval rules</h2>
          <span className="eyebrow">Amount-driven</span>
        </div>
        <form className="panel-body form-grid" onSubmit={createRule}>
          <div className="field">
            <label>Rule name</label>
            <input
              required
              className="input"
              value={rule.name}
              onChange={(event) => setRule({ ...rule, name: event.target.value })}
            />
          </div>
          <div className="field">
            <label>Minimum gross</label>
            <input
              type="number"
              min="0"
              className="input"
              value={rule.min_amount}
              onChange={(event) => setRule({ ...rule, min_amount: event.target.value })}
            />
          </div>
          <div className="field">
            <label>Maximum gross (blank = unlimited)</label>
            <input
              type="number"
              min="0"
              className="input"
              value={rule.max_amount}
              onChange={(event) => setRule({ ...rule, max_amount: event.target.value })}
            />
          </div>
          <div className="field">
            <label>Sequential roles (comma-separated)</label>
            <input
              required
              className="input"
              value={rule.roles}
              onChange={(event) => setRule({ ...rule, roles: event.target.value })}
            />
          </div>
          <div className="actions">
            {editingRuleId && (
              <button
                type="button"
                className="button"
                onClick={() => {
                  setEditingRuleId(null);
                  setRule({ name: "", min_amount: "0", max_amount: "", roles: "APPROVER" });
                }}
              >
                Cancel
              </button>
            )}
            <button className="button primary">{editingRuleId ? "Save rule" : "Add rule"}</button>
          </div>
        </form>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Rule</th>
                <th>Purpose</th>
                <th>Range</th>
                <th>Stages</th>
                <th>Status / action</th>
              </tr>
            </thead>
            <tbody>
              {rules.data &&
                listResults(rules.data).map((row) => (
                  <tr key={row.id}>
                    <td>
                      <strong>{row.name}</strong>
                    </td>
                    <td>{row.purpose}</td>
                    <td>
                      {row.min_amount} – {row.max_amount || "∞"}
                    </td>
                    <td>{row.stages.map((stage) => `${stage.sequence}. ${stage.role}`).join(" → ")}</td>
                    <td>
                      <StatusBadge value={row.active ? "ACTIVE" : "INACTIVE"} />
                      <div className="actions">
                        <button
                          className="button small"
                          onClick={() => {
                            setEditingRuleId(row.id);
                            setRule({
                              name: row.name,
                              min_amount: row.min_amount,
                              max_amount: row.max_amount || "",
                              roles: row.stages.map((stage) => stage.role).join(", "),
                            });
                          }}
                        >
                          Edit
                        </button>
                        <button
                          className="button small"
                          onClick={() =>
                            toggleRecord(`/approval-rules/${row.id}/`, "active", row.active, () => rules.refetch())
                          }
                        >
                          {row.active ? "Deactivate" : "Activate"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="panel">
        <div className="panel-head">
          <h2>Notification templates</h2>
          <span className="eyebrow">Per event and channel</span>
        </div>
        <form className="panel-body form-grid" onSubmit={createTemplate}>
          <div className="field">
            <label>Event</label>
            <select
              className="input"
              value={template.event_key}
              onChange={(event) => setTemplate({ ...template, event_key: event.target.value })}
            >
              {templateEvents.map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Channel</label>
            <select
              className="input"
              value={template.channel}
              onChange={(event) => setTemplate({ ...template, channel: event.target.value })}
            >
              {["IN_APP", "EMAIL", "WHATSAPP"].map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </div>
          <div className="field span-2">
            <label>Subject</label>
            <input
              className="input"
              value={template.subject_template}
              onChange={(event) => setTemplate({ ...template, subject_template: event.target.value })}
            />
          </div>
          <div className="field span-4">
            <label>
              Body — placeholders: {"{reference}"}, {"{actor}"}, {"{gross}"}, {"{tds}"}, {"{net}"}, {"{action_url}"}
            </label>
            <textarea
              required
              className="input"
              value={template.body_template}
              onChange={(event) => setTemplate({ ...template, body_template: event.target.value })}
            />
          </div>
          <div className="actions">
            {editingTemplateId && (
              <button type="button" className="button" onClick={() => setEditingTemplateId(null)}>
                Cancel
              </button>
            )}
            <button className="button primary">{editingTemplateId ? "Save template" : "Add template"}</button>
          </div>
        </form>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Event</th>
                <th>Channel</th>
                <th>Subject</th>
                <th>Status / action</th>
              </tr>
            </thead>
            <tbody>
              {templates.data &&
                listResults(templates.data).map((row) => (
                  <tr key={row.id}>
                    <td>{row.event_key}</td>
                    <td>{row.channel}</td>
                    <td>{row.subject_template || "—"}</td>
                    <td>
                      <StatusBadge value={row.enabled ? "ACTIVE" : "INACTIVE"} />
                      <div className="actions">
                        <button
                          className="button small"
                          onClick={() => {
                            setEditingTemplateId(row.id);
                            setTemplate({
                              event_key: row.event_key,
                              channel: row.channel,
                              subject_template: row.subject_template,
                              body_template: row.body_template,
                              enabled: row.enabled,
                            });
                          }}
                        >
                          Edit
                        </button>
                        <button
                          className="button small"
                          onClick={() =>
                            toggleRecord(`/notification-templates/${row.id}/`, "enabled", row.enabled, () =>
                              templates.refetch(),
                            )
                          }
                        >
                          {row.enabled ? "Disable" : "Enable"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
