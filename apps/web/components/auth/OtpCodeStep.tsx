"use client";

import { useEffect, useState } from "react";

export type OtpChallengeResponse = {
  challenge_id: string;
  channel: "EMAIL" | "WHATSAPP";
  destination_masked: string;
  expires_in: number;
};

export function OtpCodeStep({
  challenge,
  code,
  onCodeChange,
  onResend,
  busy,
}: {
  challenge: OtpChallengeResponse;
  code: string;
  onCodeChange: (value: string) => void;
  onResend: () => void;
  busy: boolean;
}) {
  const [seconds, setSeconds] = useState(60);
  const [trackedChallengeId, setTrackedChallengeId] = useState(challenge.challenge_id);

  if (trackedChallengeId !== challenge.challenge_id) {
    setTrackedChallengeId(challenge.challenge_id);
    setSeconds(60);
  }

  useEffect(() => {
    const timer = setInterval(() => setSeconds((value) => (value > 0 ? value - 1 : 0)), 1000);
    return () => clearInterval(timer);
  }, [challenge.challenge_id]);

  return (
    <>
      <p>
        We sent a {Math.round(challenge.expires_in / 60)}-minute code
        {challenge.channel === "WHATSAPP" ? " on WhatsApp" : " by email"} to {challenge.destination_masked}.
      </p>
      <div className="field">
        <label htmlFor="otp-code">Verification code</label>
        <input
          id="otp-code"
          className="input"
          required
          inputMode="numeric"
          maxLength={6}
          autoComplete="one-time-code"
          value={code}
          onChange={(event) => onCodeChange(event.target.value.replace(/\D/g, ""))}
        />
      </div>
      <button type="button" className="button" disabled={busy || seconds > 0} onClick={onResend}>
        {seconds > 0 ? `Resend code in ${seconds}s` : "Resend code"}
      </button>
    </>
  );
}
