"use client";

import { FormEvent, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { DateText, Empty, ErrorNotice, Loading, PageHeader, StatusBadge } from "@/components/UI";
import { api, listResults } from "@/lib/api";
import type { Paginated, User } from "@/lib/types";

type Connection = {
  id: number;
  provider: string;
  status: string;
  account_label: string;
  configuration: {
    host?: string;
    port?: number;
    from_email?: string;
    security?: string;
    approval_template_name?: string;
    finance_template_name?: string;
    operations_approval_template_name?: string;
    operations_payment_template_name?: string;
    operations_settlement_template_name?: string;
    login_button_type?: string;
    password_reset_button_type?: string;
  };
  last_error: string;
};

type Message = {
  id: number;
  channel: string;
  direction: string;
  recipient: string;
  subject: string;
  event_key: string;
  status: string;
  retry_count: number;
  last_error: string;
  created_at: string;
};
type Unmapped = {
  id: number;
  reason: string;
  resolved_at?: string;
  message_detail: Message & { body_summary?: string };
};

export default function IntegrationsPage() {
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<User>("/auth/me/") });
  const connections = useQuery({
    queryKey: ["integration-connections"],
    queryFn: () => api<Paginated<Connection>>("/integration-connections/"),
    enabled: me.data?.role === "ADMIN",
  });
  const messages = useQuery({
    queryKey: ["integration-messages"],
    queryFn: () => api<Paginated<Message>>("/messages/?page_size=25"),
    enabled: me.data?.role === "ADMIN",
  });
  const unmapped = useQuery({
    queryKey: ["unmapped-inbound"],
    queryFn: () => api<Paginated<Unmapped>>("/unmapped-messages/?page_size=100"),
    enabled: me.data?.role === "ADMIN",
  });
  const [smtp, setSmtp] = useState({
    host: "",
    port: "587",
    username: "",
    password: "",
    from_email: "",
    security: "STARTTLS",
  });
  const [token, setToken] = useState("");
  const [phoneId, setPhoneId] = useState("");
  const [whatsAppLanguage, setWhatsAppLanguage] = useState("en");
  const [whatsAppTemplates, setWhatsAppTemplates] = useState({
    approval_template_name: "drona_logitech_approval_review",
    finance_template_name: "drona_logitech_finance_ready",
    operations_approval_template_name: "drona_logitech_operations_approval",
    operations_payment_template_name: "drona_logitech_operations_payment",
    operations_settlement_template_name: "drona_logitech_operations_settlement",
    login_otp_template_name: "vms_login",
    password_recovery_template_name: "password_recovery",
  });
  // "" means "leave whatever is stored alone". The connect endpoint only
  // writes a button type when the key is present in the request body.
  const [loginButtonType, setLoginButtonType] = useState("");
  const [passwordResetButtonType, setPasswordResetButtonType] = useState("");
  const [error, setError] = useState<unknown>();
  const [message, setMessage] = useState("");

  if (me.isPending) return <Loading />;
  if (me.data?.role !== "ADMIN") {
    return (
      <ErrorNotice
        error={new Error("Administrator permission is required to manage provider credentials and outbox operations.")}
      />
    );
  }

  const connectSmtp = async (event: FormEvent) => {
    event.preventDefault();
    setError(undefined);
    try {
      await api("/integration-connections/smtp/connect/", {
        method: "POST",
        body: JSON.stringify({
          ...smtp,
          port: Number(smtp.port),
          use_tls: smtp.security === "STARTTLS",
          use_ssl: smtp.security === "SSL",
        }),
      });
      setSmtp((current) => ({ ...current, password: "" }));
      setMessage("SMTP connection saved securely.");
      await connections.refetch();
    } catch (reason) {
      setError(reason);
    }
  };

  const connectWhatsApp = async (event: FormEvent) => {
    event.preventDefault();
    setError(undefined);
    try {
      await api("/integration-connections/whatsapp/connect/", {
        method: "POST",
        body: JSON.stringify({
          access_token: token,
          phone_number_id: phoneId,
          ...whatsAppTemplates,
          approval_template_language: whatsAppLanguage,
          finance_template_language: whatsAppLanguage,
          operations_approval_template_language: whatsAppLanguage,
          operations_payment_template_language: whatsAppLanguage,
          operations_settlement_template_language: whatsAppLanguage,
          login_otp_template_language: whatsAppLanguage,
          password_recovery_template_language: whatsAppLanguage,
          ...(loginButtonType ? { login_button_type: loginButtonType } : {}),
          ...(passwordResetButtonType ? { password_reset_button_type: passwordResetButtonType } : {}),
        }),
      });
      setToken("");
      setMessage("WhatsApp connection saved securely.");
      await connections.refetch();
    } catch (reason) {
      setError(reason);
    }
  };

  const retry = async (id: number) => {
    try {
      await api(`/messages/${id}/retry/`, { method: "POST" });
      await messages.refetch();
    } catch (reason) {
      setError(reason);
    }
  };
  const resolveInbound = async (event: FormEvent<HTMLFormElement>, id: number) => {
    event.preventDefault();
    setError(undefined);
    const values = new FormData(event.currentTarget);
    try {
      await api(`/unmapped-messages/${id}/resolve/`, {
        method: "POST",
        body: JSON.stringify({ object_type: values.get("object_type"), object_id: values.get("object_id") }),
      });
      await unmapped.refetch();
    } catch (reason) {
      setError(reason);
    }
  };

  const connectionRows = connections.data ? listResults(connections.data) : [];
  const smtpConnection = connectionRows.find((row) => row.provider === "SMTP");
  const whatsappConnection = connectionRows.find((row) => row.provider === "WHATSAPP");
  const outbox = messages.data ? listResults(messages.data) : [];
  const unresolved = unmapped.data ? listResults(unmapped.data).filter((row) => !row.resolved_at) : [];

  return (
    <>
      <PageHeader
        title="Integration operations"
        description="Configure SMTP and WhatsApp delivery, inspect provider status, and retry failed outbox records."
      />
      {message && <div className="notice">{message}</div>}
      {Boolean(error) && <ErrorNotice error={error} />}
      <div className="split">
        <form className="panel" onSubmit={connectSmtp}>
          <div className="panel-head">
            <h2>SMTP email</h2>
            {smtpConnection && <StatusBadge value={smtpConnection.status} />}
          </div>
          <div className="panel-body">
            <p className="muted">
              Credentials are encrypted at rest. Use STARTTLS on port 587 or implicit SSL on port 465 unless your mail
              provider specifies otherwise.
            </p>
            {smtpConnection && (
              <p className="muted">
                Current: {smtpConnection.configuration.from_email} via {smtpConnection.configuration.host}:
                {smtpConnection.configuration.port} ({smtpConnection.configuration.security})
              </p>
            )}
            <div className="field">
              <label htmlFor="smtp-host">SMTP host</label>
              <input
                id="smtp-host"
                required
                className="input"
                value={smtp.host}
                onChange={(event) => setSmtp({ ...smtp, host: event.target.value })}
                placeholder="smtp.example.com"
              />
            </div>
            <div className="form-grid" style={{ marginTop: 12 }}>
              <div className="field">
                <label htmlFor="smtp-port">Port</label>
                <input
                  id="smtp-port"
                  required
                  className="input"
                  inputMode="numeric"
                  value={smtp.port}
                  onChange={(event) => setSmtp({ ...smtp, port: event.target.value })}
                />
              </div>
              <div className="field">
                <label htmlFor="smtp-security">Security</label>
                <select
                  id="smtp-security"
                  className="input"
                  value={smtp.security}
                  onChange={(event) => setSmtp({ ...smtp, security: event.target.value })}
                >
                  <option>STARTTLS</option>
                  <option>SSL</option>
                  <option>PLAIN</option>
                </select>
              </div>
            </div>
            <div className="field" style={{ marginTop: 12 }}>
              <label htmlFor="smtp-username">Username</label>
              <input
                id="smtp-username"
                className="input"
                autoComplete="username"
                value={smtp.username}
                onChange={(event) => setSmtp({ ...smtp, username: event.target.value })}
              />
            </div>
            <div className="field" style={{ marginTop: 12 }}>
              <label htmlFor="smtp-password">Password</label>
              <input
                id="smtp-password"
                className="input"
                required={Boolean(smtp.username)}
                type="password"
                autoComplete="new-password"
                value={smtp.password}
                onChange={(event) => setSmtp({ ...smtp, password: event.target.value })}
              />
            </div>
            <div className="field" style={{ marginTop: 12 }}>
              <label htmlFor="smtp-from-email">From email</label>
              <input
                id="smtp-from-email"
                required
                type="email"
                className="input"
                value={smtp.from_email}
                onChange={(event) => setSmtp({ ...smtp, from_email: event.target.value })}
                placeholder="transport@example.com"
              />
            </div>
            <button className="button primary" style={{ marginTop: 12 }}>
              Save encrypted SMTP connection
            </button>
          </div>
        </form>
        <form className="panel" onSubmit={connectWhatsApp}>
          <div className="panel-head">
            <h2>WhatsApp Cloud API</h2>
            {whatsappConnection && <StatusBadge value={whatsappConnection.status} />}
          </div>
          <div className="panel-body">
            <div className="notice">
              <strong>Meta Utility templates</strong>
              <br />
              Create the five approved templates shown below. Approval uses a document plus Approve/Reject quick
              replies; Finance and Operations templates use a dynamic “Open in VMS” website button.
            </div>
            <div className="field">
              <label htmlFor="whatsapp-phone-id">Phone number ID</label>
              <input
                id="whatsapp-phone-id"
                required
                className="input"
                value={phoneId}
                onChange={(event) => setPhoneId(event.target.value)}
              />
            </div>
            <div className="field" style={{ marginTop: 12 }}>
              <label htmlFor="whatsapp-token">Access token</label>
              <input
                id="whatsapp-token"
                required
                type="password"
                autoComplete="off"
                className="input"
                value={token}
                onChange={(event) => setToken(event.target.value)}
              />
            </div>
            <div className="field" style={{ marginTop: 12 }}>
              <label htmlFor="whatsapp-language">Approved language code</label>
              <input
                id="whatsapp-language"
                required
                className="input"
                value={whatsAppLanguage}
                onChange={(event) => setWhatsAppLanguage(event.target.value)}
                placeholder="en"
              />
            </div>
            {Object.entries(whatsAppTemplates).map(([key, value]) => (
              <div className="field" style={{ marginTop: 12 }} key={key}>
                <label htmlFor={`whatsapp-${key}`}>{key.replaceAll("_", " ")}</label>
                <input
                  id={`whatsapp-${key}`}
                  required
                  className="input"
                  value={value}
                  onChange={(event) => setWhatsAppTemplates((current) => ({ ...current, [key]: event.target.value }))}
                />
              </div>
            ))}
            <div className="field" style={{ marginTop: 12 }}>
              <label htmlFor="whatsapp-login-button-type">Login OTP button type</label>
              <select
                id="whatsapp-login-button-type"
                className="input"
                value={loginButtonType}
                onChange={(event) => setLoginButtonType(event.target.value)}
              >
                <option value="">Keep current setting</option>
                <option value="none">None</option>
                <option value="url">URL</option>
              </select>
            </div>
            <div className="field" style={{ marginTop: 12 }}>
              <label htmlFor="whatsapp-password-reset-button-type">Password recovery button type</label>
              <select
                id="whatsapp-password-reset-button-type"
                className="input"
                value={passwordResetButtonType}
                onChange={(event) => setPasswordResetButtonType(event.target.value)}
              >
                <option value="">Keep current setting</option>
                <option value="none">None</option>
                <option value="url">URL</option>
              </select>
            </div>
            {whatsappConnection && (
              <p className="muted" style={{ marginTop: 12 }}>
                Saved Finance template:{" "}
                <code>{whatsappConnection.configuration.finance_template_name || "not configured"}</code>
                {" · "}Login button: <code>{whatsappConnection.configuration.login_button_type || "none"}</code>
                {" · "}Recovery button:{" "}
                <code>{whatsappConnection.configuration.password_reset_button_type || "none"}</code>
              </p>
            )}
            <button className="button primary" style={{ marginTop: 12 }}>
              Save encrypted connection
            </button>
          </div>
        </form>
      </div>
      <section className="panel">
        <div className="panel-head">
          <h2>Outbox and provider events</h2>
          <span className="eyebrow">Latest 25</span>
        </div>
        {messages.isPending ? (
          <Loading />
        ) : outbox.length === 0 ? (
          <Empty />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Created</th>
                  <th>Channel</th>
                  <th>Direction</th>
                  <th>Recipient / subject</th>
                  <th>Event</th>
                  <th>Status</th>
                  <th>Retries</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {outbox.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <DateText value={row.created_at} />
                    </td>
                    <td>{row.channel}</td>
                    <td>{row.direction}</td>
                    <td>
                      {row.recipient}
                      <div className="muted">{row.subject}</div>
                      {row.last_error && <div style={{ color: "var(--red)" }}>{row.last_error}</div>}
                    </td>
                    <td>{row.event_key || "—"}</td>
                    <td>
                      <StatusBadge value={row.status} />
                    </td>
                    <td>{row.retry_count}</td>
                    <td>
                      {["FAILED", "QUEUED"].includes(row.status) && row.direction === "OUTBOUND" && (
                        <button className="button small" onClick={() => retry(row.id)}>
                          Retry
                        </button>
                      )}
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
          <h2>Unmapped inbound replies</h2>
          <span className="eyebrow">Manual reconciliation</span>
        </div>
        {unmapped.isPending ? (
          <Loading />
        ) : unresolved.length === 0 ? (
          <Empty message="No inbound replies need reconciliation." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Received</th>
                  <th>Channel / sender</th>
                  <th>Reason and message</th>
                  <th>Link to record</th>
                </tr>
              </thead>
              <tbody>
                {unresolved.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <DateText value={row.message_detail.created_at} />
                    </td>
                    <td>
                      {row.message_detail.channel}
                      <div className="muted">{row.message_detail.recipient}</div>
                    </td>
                    <td>
                      {row.reason}
                      <div className="muted">{row.message_detail.body_summary || row.message_detail.subject}</div>
                    </td>
                    <td>
                      <form className="actions" onSubmit={(event) => resolveInbound(event, row.id)}>
                        <select className="input" name="object_type" required defaultValue="approval">
                          <option value="approval">Approval</option>
                          <option value="trip">Trip</option>
                          <option value="payment">Payment</option>
                        </select>
                        <input
                          className="input"
                          name="object_id"
                          inputMode="numeric"
                          required
                          placeholder="Record ID"
                        />
                        <button className="button small">Reconcile</button>
                      </form>
                    </td>
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
