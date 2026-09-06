"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { api, listResults } from "@/lib/api";
import type { DocumentRecord, Paginated, Vendor } from "@/lib/types";
import { DateText, Empty, ErrorNotice, Loading, Money, PageHeader, StatusBadge } from "@/components/UI";

type Ledger = {
  vendor_name: string;
  total_freight_100: string;
  total_advance_amount: string;
  freight_balance_after_advance: string;
  total_vendor_liability: string;
  approved_gross: string;
  approved_remaining: string;
  tds: string;
  cash_paid: string;
  remaining_to_pay: string;
  entries: Array<{
    date: string;
    timestamp: string;
    trip_no: string;
    approval_no: string;
    payment_no: string;
    type: string;
    gross: string;
    tds: string;
    cash: string;
    utr: string;
    status: string;
  }>;
};

function ChequeProof({ bankId, uploaded }: { bankId: number; uploaded: boolean }) {
  const proof = useQuery({
    queryKey: ["documents", "vendor-bank-account", bankId],
    queryFn: async () =>
      listResults(
        await api<Paginated<DocumentRecord>>(`/documents/?object_type=vendor_bank_account&object_id=${bankId}`),
      )[0] ?? null,
  });
  if (proof.data)
    return (
      <a className="chip" href={proof.data.download_url}>
        View proof
      </a>
    );
  return <StatusBadge value={uploaded ? "VERIFIED" : "MISSING"} />;
}

export default function VendorDetailPage() {
  const { id } = useParams<{ id: string }>();
  const vendor = useQuery({ queryKey: ["vendor", id], queryFn: () => api<Vendor>(`/vendors/${id}/`) });
  const ledger = useQuery({ queryKey: ["vendor-ledger", id], queryFn: () => api<Ledger>(`/vendor-ledger/${id}/`) });
  const kyc = useQuery({
    queryKey: ["documents", "vendor", id],
    queryFn: async () =>
      listResults(await api<Paginated<DocumentRecord>>(`/documents/?object_type=vendor&object_id=${id}`)),
  });
  if (vendor.isPending) return <Loading />;
  if (vendor.error) return <ErrorNotice error={vendor.error} />;
  const v = vendor.data!;
  return (
    <>
      <PageHeader title={v.display_name} description={`${v.vendor_code} · ${v.legal_name}`}>
        <StatusBadge value={v.status} />
      </PageHeader>
      <div className="summary-strip">
        <div>
          <span>Primary contact</span>
          <strong>{v.primary_phone || "—"}</strong>
        </div>
        <div>
          <span>Email</span>
          <strong>{v.email || "—"}</strong>
        </div>
        <div>
          <span>Active vehicles</span>
          <strong>{v.vehicles_count}</strong>
        </div>
        <div>
          <span>KYC files</span>
          <strong>{kyc.data?.length ?? 0}</strong>
        </div>
      </div>
      <div className="split">
        <section className="panel">
          <div className="panel-head">
            <h2>Bank details</h2>
          </div>
          {!v.bank_accounts?.length ? (
            <Empty message="No bank account available" />
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Bank</th>
                    <th>Account holder</th>
                    <th>Account</th>
                    <th>IFSC</th>
                    <th>Cheque proof</th>
                  </tr>
                </thead>
                <tbody>
                  {v.bank_accounts.map((bank) => {
                    return (
                      <tr key={bank.id}>
                        <td>{bank.bank_name}</td>
                        <td>{bank.account_holder}</td>
                        <td>{bank.masked_account_number}</td>
                        <td>{bank.ifsc_code}</td>
                        <td>
                          <ChequeProof bankId={bank.id} uploaded={bank.cancelled_cheque_uploaded} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
        <section className="panel">
          <div className="panel-head">
            <h2>Identity verification</h2>
          </div>
          {kyc.isPending ? (
            <Loading />
          ) : kyc.error ? (
            <ErrorNotice error={kyc.error} />
          ) : !kyc.data?.length ? (
            <Empty message="No Aadhaar or PAN uploaded" />
          ) : (
            <div className="panel-body">
              <div className="actions">
                {kyc.data.map((document) => (
                  <a key={document.id} className="chip" href={document.download_url}>
                    {document.kind} · {document.original_name}
                  </a>
                ))}
              </div>
            </div>
          )}
        </section>
      </div>
      {ledger.isPending ? (
        <Loading />
      ) : ledger.error ? (
        <ErrorNotice error={ledger.error} />
      ) : (
        <>
          <div className="cards">
            {[
              ["Full freight (100%)", ledger.data!.total_freight_100],
              ["Planned advance", ledger.data!.total_advance_amount],
              ["Freight after advance", ledger.data!.freight_balance_after_advance],
              ["Cash paid", ledger.data!.cash_paid],
              ["TDS deducted", ledger.data!.tds],
              ["Remaining to pay", ledger.data!.remaining_to_pay],
              ["Approved, still unpaid", ledger.data!.approved_remaining],
            ].map(([label, value]) => (
              <div className="card stat" key={label}>
                <div className="stat-label">{label}</div>
                <div className="stat-value">
                  <Money value={value} />
                </div>
              </div>
            ))}
          </div>
          <section className="panel">
            <div className="panel-head">
              <h2>Recent vendor ledger</h2>
            </div>
            {ledger.data!.entries.length === 0 ? (
              <Empty />
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Date / timestamp</th>
                      <th>Trip</th>
                      <th>Approval / payment</th>
                      <th>Type</th>
                      <th className="money">Gross</th>
                      <th className="money">TDS</th>
                      <th className="money">Cash</th>
                      <th>UTR</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ledger.data!.entries.map((entry, index) => (
                      <tr key={`${entry.payment_no}-${index}`}>
                        <td>
                          <DateText value={entry.date} />
                          <div className="muted">
                            <DateText value={entry.timestamp} />
                          </div>
                        </td>
                        <td>{entry.trip_no}</td>
                        <td>
                          {entry.approval_no}
                          <div className="muted">{entry.payment_no}</div>
                        </td>
                        <td>
                          <StatusBadge value={entry.type} />
                        </td>
                        <td className="money">
                          <Money value={entry.gross} />
                        </td>
                        <td className="money">
                          <Money value={entry.tds} />
                        </td>
                        <td className="money">
                          <Money value={entry.cash} />
                        </td>
                        <td>{entry.utr}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </>
  );
}
