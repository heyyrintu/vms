"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, listResults } from "@/lib/api";
import type { Paginated, Payment, Vendor } from "@/lib/types";
import {
  DateText,
  DetailLink,
  Empty,
  ErrorNotice,
  Loading,
  Money,
  PageHeader,
  Pagination,
  StatusBadge,
} from "@/components/UI";

export default function PaymentRegisterPage() {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [vendor, setVendor] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);
  const pageSize = 25;
  const payments = useQuery({
    queryKey: ["payments", search, status, vendor, dateFrom, dateTo, page],
    queryFn: () =>
      api<Paginated<Payment>>(
        `/payments/?page=${page}&page_size=${pageSize}&search=${encodeURIComponent(search)}&status=${status}&vendor=${vendor}&date_from=${dateFrom}&date_to=${dateTo}`,
      ),
  });
  const vendors = useQuery({
    queryKey: ["payment-filter-vendors"],
    queryFn: () => api<Paginated<Vendor>>("/vendors/?page_size=200"),
  });
  const rows = payments.data ? listResults(payments.data) : [];
  return (
    <>
      <PageHeader
        title="Payment register"
        description="Immutable bank payment records with vendor ownership, UTR and trip-wise allocations."
      >
        <Link href="/finance" className="button primary">
          Open finance queue
        </Link>
      </PageHeader>
      <section className="panel">
        <div className="panel-body">
          <div className="filters">
            <div className="field span-2">
              <label>Search payment, UTR, vendor or trip</label>
              <input
                className="input"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
              />
            </div>
            <div className="field">
              <label>Status</label>
              <select
                className="input"
                value={status}
                onChange={(e) => {
                  setStatus(e.target.value);
                  setPage(1);
                }}
              >
                <option value="">All</option>
                <option>PAID</option>
                <option>REVERSED</option>
                <option>FAILED</option>
              </select>
            </div>
            <div className="field">
              <label>Vendor</label>
              <select
                className="input"
                value={vendor}
                onChange={(e) => {
                  setVendor(e.target.value);
                  setPage(1);
                }}
              >
                <option value="">All vendors</option>
                {vendors.data &&
                  listResults(vendors.data).map((row) => (
                    <option key={row.id} value={row.id}>
                      {row.display_name}
                    </option>
                  ))}
              </select>
            </div>
            <div className="field">
              <label>From</label>
              <input
                type="date"
                className="input"
                value={dateFrom}
                onChange={(e) => {
                  setDateFrom(e.target.value);
                  setPage(1);
                }}
              />
            </div>
            <div className="field">
              <label>To</label>
              <input
                type="date"
                className="input"
                value={dateTo}
                onChange={(e) => {
                  setDateTo(e.target.value);
                  setPage(1);
                }}
              />
            </div>
          </div>
        </div>
        {payments.isPending ? (
          <Loading />
        ) : payments.error ? (
          <ErrorNotice error={payments.error} />
        ) : rows.length === 0 ? (
          <Empty />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Payment</th>
                  <th>Vendor</th>
                  <th>Date / paid timestamp</th>
                  <th>Mode / UTR</th>
                  <th>Trips</th>
                  <th className="money">Gross</th>
                  <th className="money">TDS</th>
                  <th className="money">Net paid</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((payment) => (
                  <tr key={payment.id}>
                    <td>
                      <DetailLink href={`/payments/${payment.id}`}>{payment.payment_no}</DetailLink>
                    </td>
                    <td>{payment.vendor_name}</td>
                    <td>
                      <DateText value={payment.payment_date} />
                      <div className="muted">
                        <DateText value={payment.paid_at || payment.created_at} />
                      </div>
                    </td>
                    <td>
                      {payment.payment_mode}
                      <div className="muted">{payment.utr_reference}</div>
                    </td>
                    <td>{payment.allocations.length}</td>
                    <td className="money">
                      <Money value={payment.gross_allocated_amount} />
                    </td>
                    <td className="money">
                      <Money value={payment.tds_amount} />
                    </td>
                    <td className="money">
                      <strong>
                        <Money value={payment.net_paid_amount} />
                      </strong>
                    </td>
                    <td>
                      <StatusBadge value={payment.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {payments.data && <Pagination count={payments.data.count} page={page} pageSize={pageSize} onPage={setPage} />}
      </section>
    </>
  );
}
