"use client";

import { FormEvent, useState } from "react";
import { api } from "@/lib/api";
import { OtpCodeStep, type OtpChallengeResponse } from "./OtpCodeStep";

export function ForgotPassword({ onBack }: { onBack: () => void }) {
  const [identifier, setIdentifier] = useState("");
  const [challenge, setChallenge] = useState<OtpChallengeResponse | null>(null);
  const [code, setCode] = useState("");
  const [ticket, setTicket] = useState("");
  const [password, setPassword] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const requestCode = async () => {
    setBusy(true);
    setError("");
    try {
      setChallenge(
        await api<OtpChallengeResponse>("/auth/otp/request/", {
          method: "POST",
          body: JSON.stringify({ identifier, purpose: "PASSWORD_RESET" }),
        }),
      );
      setCode("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not send a code");
    } finally {
      setBusy(false);
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (!challenge) {
        await requestCode();
      } else if (!ticket) {
        const result = await api<{ reset_ticket: string }>("/auth/otp/verify/", {
          method: "POST",
          body: JSON.stringify({
            challenge_id: challenge.challenge_id,
            code,
            purpose: "PASSWORD_RESET",
          }),
        });
        setTicket(result.reset_ticket);
      } else {
        await api("/auth/password/reset/confirm/", {
          method: "POST",
          body: JSON.stringify({ reset_ticket: ticket, new_password: password }),
        });
        setNotice("Password reset. You can now sign in.");
        setTicket("");
        setChallenge(null);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Password reset failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="login-form" onSubmit={submit}>
      <div className="login-form-kicker">Drona Logitech</div>
      <h2>Reset password</h2>
      {notice && <div className="notice">{notice}</div>}
      {error && <div className="notice error">{error}</div>}
      {!challenge && (
        <div className="field">
          <label htmlFor="reset-identifier">Email or WhatsApp number</label>
          <input
            id="reset-identifier"
            className="input"
            required
            value={identifier}
            onChange={(event) => setIdentifier(event.target.value)}
          />
        </div>
      )}
      {challenge && !ticket && (
        <OtpCodeStep challenge={challenge} code={code} onCodeChange={setCode} onResend={requestCode} busy={busy} />
      )}
      {ticket && (
        <div className="field">
          <label htmlFor="reset-password">New password</label>
          <input
            id="reset-password"
            type="password"
            className="input"
            required
            minLength={12}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>
      )}
      <button className="button primary" disabled={busy}>
        {busy ? "Working…" : !challenge ? "Send code" : !ticket ? "Verify code" : "Reset password"}
      </button>
      <button type="button" className="button" onClick={onBack}>
        Back to sign in
      </button>
    </form>
  );
}
