# Integration setup

Local development uses deterministic fake-provider boundaries. No external credentials are required. Every outbound message is written to the encrypted, idempotent outbox and delivered by Celery; administrators can inspect failures and retry them from the Integrations screen.

Set `INTEGRATION_DELIVERY_MODE=async` when Redis, Celery worker and Celery beat are running. For a single-machine installation that starts Django directly without those services, set `INTEGRATION_DELIVERY_MODE=sync`; external messages are then delivered immediately after the approval/payment database transaction commits. Provider failures still remain in the outbox for inspection and retry.

## SMTP production adapter

Set `EMAIL_PROVIDER=smtp` and provide these environment values, or save the same connection from Settings → Integrations:

- `SMTP_HOST`
- `SMTP_PORT` (normally `587` for STARTTLS or `465` for implicit SSL)
- `SMTP_USERNAME` and `SMTP_PASSWORD` (both may be blank for an authenticated network relay)
- `SMTP_FROM_EMAIL`
- `SMTP_USE_TLS=true` and `SMTP_USE_SSL=false` for STARTTLS, or the inverse for implicit SSL
- `SMTP_TIMEOUT_SECONDS` (defaults to `20`)

The SMTP adapter encrypts UI-supplied credentials, adds a stable application idempotency header, records the RFC message ID, supports STARTTLS/SSL, and keeps retryable failures in the transactional outbox. A migration deliberately disconnects any old Gmail OAuth record because OAuth tokens are not SMTP credentials; enter the SMTP details after upgrading.

SMTP is an outbound protocol. If your mail provider or inbound mail gateway can POST parsed replies, set `EMAIL_WEBHOOK_TOKEN` and send authenticated events to `/api/webhooks/email/` with `Authorization: Bearer <EMAIL_WEBHOOK_TOKEN>`. The JSON fields are `external_message_id`, `external_thread_id`, `subject`, `body`, and optional `sender`. Reply mapping remains idempotent and uses outbound thread IDs or stable `[PA-YYYY-NNNNNN]` approval references.

## WhatsApp production adapter

Set `WHATSAPP_PROVIDER=whatsapp` and provide:

- `WHATSAPP_ACCESS_TOKEN`
- `WHATSAPP_PHONE_NUMBER_ID`
- `WHATSAPP_VERIFY_TOKEN`
- `WHATSAPP_APP_SECRET`
- `WHATSAPP_API_VERSION`
- `WHATSAPP_TEMPLATE_NAME` and `WHATSAPP_TEMPLATE_LANGUAGE` when an approved template is required

Configure the Meta webhook at `/api/webhooks/whatsapp/` for messages and message-template status updates. Verification tokens and `X-Hub-Signature-256` HMAC checks are enforced. Outbound IDs and sent/delivered/read/failed states are retained. Replies map through provider context; supported media is downloaded with the provider token, size/signature/malware checked, and stored privately. The payment/approval payload builders query vendor-specific lines only.

### Interactive WhatsApp approval template

Create a Meta Utility template named `drona_logitech_approval_review` using language code `en` (or update `WHATSAPP_APPROVAL_TEMPLATE_LANGUAGE` to exactly match the approved language). It must have:

- a document header;
- a body with six parameters: approval number, requester, trip count, gross amount, TDS amount and net payable;
- two quick-reply buttons in this exact order: `Approve`, then `Reject`.

Recommended body:

```text
Approval {{1}} needs your decision.
Requested by: {{2}}
Trips: {{3}}
Gross requested: INR {{4}}
TDS: INR {{5}}
Net payable: INR {{6}}

Review the attached trip PDF, then choose Approve or Reject.
```

The application uploads the generated approval PDF to WhatsApp, fills all six parameters and signs each button payload for the individual approver. Replies are accepted only when the sender number matches that active user, the response is linked to the original outbound request, the approval is still pending at that user's stage and the token has not expired. The default expiry is seven days (`WHATSAPP_APPROVAL_EXPIRY_SECONDS=604800`). Duplicate webhook deliveries do not repeat the decision.

Approval-button payloads use compact timestamped signatures and remain within Meta's 128-character quick-reply payload limit. Retrying an approval request regenerates the signed buttons so older queued payload formats cannot block delivery.

### Finance and Operations WhatsApp templates

Create the following templates as **Utility → Default** in WhatsApp Manager. Use the exact template names, body-variable order, language code, and button position shown here. Replace `https://vms.example.com` with the public HTTPS value used by `WEB_ORIGIN`. For each website button, keep the record ID as the final dynamic part of the URL.

#### 1. Finance queue: `drona_logitech_finance_ready`

Body (seven variables):

```text
Payment approval {{1}} is ready for Finance.
Requested by: {{2}}
Approved by: {{3}}
Trips: {{4}}
Gross approved: INR {{5}}
TDS: INR {{6}}
Net payable: INR {{7}}

Review the approval and record the payment in VMS.
```

Add one **Visit website** button:

- Button text: `Open finance queue`
- URL: `https://vms.example.com/finance?approval={{1}}`
- Dynamic sample: `123`

Variable samples, in order: `PA-2026-000123`, `Team Drona`, `Amit Sharma`, `3`, `150000.00`, `1500.00`, `148500.00`.

#### 2. Operations approval result: `drona_logitech_operations_approval`

Body (five variables):

```text
Approval {{1}} status: {{2}}.
Updated by: {{3}}
Trips: {{4}}
Net payable: INR {{5}}

Open VMS to review the decision and comments.
```

Add one **Visit website** button:

- Button text: `View approval`
- URL: `https://vms.example.com/approvals/{{1}}`
- Dynamic sample: `123`

Variable samples, in order: `PA-2026-000123`, `Approved`, `Amit Sharma`, `3`, `148500.00`.

The same template is used for `Approved`, `Rejected`, and `Changes requested`, so Operations receives the result without creating three nearly identical Meta templates.

#### 3. Operations payment confirmation: `drona_logitech_operations_payment`

Body (eight variables):

```text
Payment {{1}} has been recorded.
Vendor: {{2}}
Trips: {{3}}
Gross: INR {{4}}
TDS: INR {{5}}
Net paid: INR {{6}}
UTR: {{7}}
Paid at: {{8}}

Open VMS for the payment allocation and proof.
```

Add one **Visit website** button:

- Button text: `View payment`
- URL: `https://vms.example.com/payments/{{1}}`
- Dynamic sample: `123`

Variable samples, in order: `PAY-2026-000123`, `ABC Transport`, `3`, `150000.00`, `1500.00`, `148500.00`, `UTR123456789`, `04 Sep 2026, 03:30 PM`.

#### 4. Operations settlement alert: `drona_logitech_operations_settlement`

Body (five variables):

```text
Trip {{1}} is ready for final settlement.
Route: {{2}}
Vendor: {{3}}
Delivered at: {{4}}
Freight 100%: INR {{5}}

Open VMS to verify POD, charges, paid amount, TDS and remaining payable.
```

Add one **Visit website** button:

- Button text: `Open trip`
- URL: `https://vms.example.com/trips/{{1}}`
- Dynamic sample: `123`

Variable samples, in order: `NPL-2026-000123`, `Sonipat to Kichha`, `ABC Transport`, `04 Sep 2026, 03:30 PM`, `50000.00`.

After Meta approves the templates, enter their exact names and language code on **Settings → Integrations → WhatsApp Cloud API**. The server also supports the corresponding `WHATSAPP_FINANCE_*` and `WHATSAPP_OPERATIONS_*` environment variables shown in `.env.example`.

## Templates and preferences

Administrators can configure a unique event/channel template using `{reference}`, `{vendor}`, `{trip_lines}`, `{gross}`, `{tds}`, `{net}`, and `{utr}` placeholders as relevant. In-app users may disable individual event/channel combinations. Transporter delivery is driven by the selected vendor only; internal comments and cross-vendor approval attachments are never exposed through vendor-facing APIs.

When a final approval decision is accepted, the vendor receives an approval notice through both configured channels: `Vendor.email` by SMTP and `Vendor.primary_phone` by WhatsApp. Recording a paid transaction sends a payment/UTR notice through the same two channels. A missing contact value skips only that channel; delivery state and retries remain independent. WhatsApp numbers are stored in international digits-only format, such as `919876543210`.

Internal workflow notifications also use all configured channels. Submitting an approval sends in-app, SMTP email and WhatsApp messages to every active user assigned to the current approval-stage role. Final approval sends the same three-channel `FINANCE_READY` notice to active Finance users. Approval outcomes and completed payments notify the Operations requester, while delivered trips notify active Operations users that settlement is pending. Administrators maintain each internal user's email and WhatsApp number under Settings → User and role management; per-event/channel notification preferences can disable individual deliveries.

Approval email and WhatsApp messages contain an `{action_url}` pointing to the exact approval. If the approver is signed out, the application preserves that destination through login and returns them to the approval. Only the signed `Approve` and `Reject` quick-reply buttons on the approval template execute a decision; plain text replies do not. Finance and Operations template buttons only open the authenticated VMS record, preserving role checks, optional MFA, CSRF protection, required comments and immutable audit history.

Use fake providers in development and CI. Before enabling live delivery, send one approval and one payment in staging, verify SMTP delivery and optional inbound mapping, force a retryable failure, and confirm that no provider password or full payload appears in logs.
