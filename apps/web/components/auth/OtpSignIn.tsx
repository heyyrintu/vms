"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";
import { OtpCodeStep, type OtpChallengeResponse } from "./OtpCodeStep";

export function OtpSignIn({ onBack }: { onBack: () => void }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [identifier, setIdentifier] = useState("");
  const [challenge, setChallenge] = useState<OtpChallengeResponse | null>(null);
  const [code, setCode] = useState("");
  const [authenticator, setAuthenticator] = useState("");
  const [mfaRequired, setMfaRequired] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const requestCode = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await api<OtpChallengeResponse>("/auth/otp/request/", {
        method: "POST",
        body: JSON.stringify({ identifier, purpose: "LOGIN" }),
      });
      setChallenge(result);
      setCode("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not send a code");
    } finally {
      setBusy(false);
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!challenge) return requestCode();
    setBusy(true);
    setError("");
    try {
      const user = await api<User>("/auth/otp/verify/", {
        method: "POST",
        body: JSON.stringify({
          challenge_id: challenge.challenge_id,
          code,
          purpose: "LOGIN",
          otp: authenticator,
        }),
      });
      queryClient.setQueryData(["me"], user);
      const requested = new URLSearchParams(window.location.search).get("next") ?? "/";
      router.replace(requested.startsWith("/") && !requested.startsWith("//") ? requested : "/");
    } catch (reason) {
      const data = (reason as { data?: { mfa_required?: boolean } }).data;
      if (data?.mfa_required) setMfaRequired(true);
      setError(reason instanceof Error ? reason.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="login-form" onSubmit={submit}>
      <div className="login-form-kicker">Drona Logitech</div>
      <h2>Sign in with a code</h2>
      {error && <div className="notice error">{error}</div>}
      {challenge ? (
        <>
          <OtpCodeStep challenge={challenge} code={code} onCodeChange={setCode} onResend={requestCode} busy={busy} />
          {mfaRequired && (
            <div className="field">
              <label htmlFor="otp-authenticator">Authenticator code</label>
              <input id="otp-authenticator" className="input" inputMode="numeric" maxLength={6}
                value={authenticator} onChange={(event) => setAuthenticator(event.target.value)} />
            </div>
          )}
        </>
      ) : (
        <div className="field">
          <label htmlFor="otp-identifier">Email or WhatsApp number</label>
          <input id="otp-identifier" className="input" required value={identifier}
            autoComplete="username" onChange={(event) => setIdentifier(event.target.value)} />
        </div>
      )}
      <button className="button primary" disabled={busy}>
        {busy ? "Working…" : challenge ? "Verify and sign in" : "Send code"}
      </button>
      <button type="button" className="button" onClick={onBack}>
        Back to sign in
      </button>
    </form>
  );
}
