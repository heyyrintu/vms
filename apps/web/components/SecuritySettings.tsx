"use client";

import { FormEvent, useState } from "react";
import { api } from "@/lib/api";
import { ErrorNotice } from "@/components/UI";

export function SecuritySettings({ mfaEnabled }: { mfaEnabled: boolean }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [secret, setSecret] = useState("");
  const [uri, setUri] = useState("");
  const [otp, setOtp] = useState("");
  const [error, setError] = useState<unknown>();
  const [message, setMessage] = useState("");
  const changePassword = async (event: FormEvent) => {
    event.preventDefault();
    setError(undefined);
    try {
      await api("/auth/password/change/", {
        method: "POST",
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      setCurrent("");
      setNext("");
      setMessage("Password changed.");
    } catch (reason) {
      setError(reason);
    }
  };
  const setup = async () => {
    try {
      const result = await api<{ secret: string; provisioning_uri: string }>("/auth/mfa/setup/", { method: "POST" });
      setSecret(result.secret);
      setUri(result.provisioning_uri);
    } catch (reason) {
      setError(reason);
    }
  };
  const confirm = async () => {
    try {
      await api("/auth/mfa/confirm/", { method: "POST", body: JSON.stringify({ otp }) });
      setMessage("Multi-factor authentication enabled.");
      setSecret("");
    } catch (reason) {
      setError(reason);
    }
  };
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Account security</h2>
        <span className="eyebrow">MFA {mfaEnabled ? "enabled" : "available"}</span>
      </div>
      <div className="panel-body">
        {message && <div className="notice">{message}</div>}
        {Boolean(error) && <ErrorNotice error={error} />}
        <form className="form-grid two" onSubmit={changePassword}>
          <div className="field">
            <label>Current password</label>
            <input
              required
              type="password"
              className="input"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
            />
          </div>
          <div className="field">
            <label>New password (12+ characters)</label>
            <input
              required
              minLength={12}
              type="password"
              className="input"
              value={next}
              onChange={(e) => setNext(e.target.value)}
            />
          </div>
          <div>
            <button className="button">Change password</button>
          </div>
        </form>
        <hr style={{ border: 0, borderTop: "1px solid var(--line)", margin: "22px 0" }} />
        {!mfaEnabled && !secret && (
          <button className="button" onClick={setup}>
            Set up authenticator MFA
          </button>
        )}
        {secret && (
          <div>
            <div className="notice">
              <strong>Authenticator secret:</strong> <code>{secret}</code>
              <br />
              <small>Add it to your authenticator app. URI: {uri}</small>
            </div>
            <div className="actions">
              <input
                aria-label="Authenticator code"
                className="input"
                style={{ maxWidth: 180 }}
                value={otp}
                onChange={(e) => setOtp(e.target.value)}
                placeholder="6-digit code"
              />
              <button className="button primary" onClick={confirm}>
                Confirm MFA
              </button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
