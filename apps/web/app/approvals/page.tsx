"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, listResults } from "@/lib/api";
import type { Approval, Paginated } from "@/lib/types";
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

export default function ApprovalInboxPage() {
  const [status, setStatus] = useState("PENDING");
  const [search, setSearch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);
  const pageSize = 25;
  const approvals = useQuery({
    queryKey: ["approvals", status, search, dateFrom, dateTo, page],
    queryFn: () =>
      api<Paginated<Approval>>(
        `/approval-batches/?page=${page}&page_size=${pageSize}&status=${status}&search=${encodeURIComponent(search)}&date_from=${dateFrom}&date_to=${dateTo}`,
      ),
  });
  const rows = approvals.data ? listResults(approvals.data) : [];
  return (
    <>
      <PageHeader
        title="Approval inbox"
        description="Review every trip line, vendor subtotal and locked calculation snapshot before deciding."
      >
        <Link className="button primary" href="/approvals/new">
          + Build approval
        </Link>
      </PageHeader>
      <div className="panel">
        <div className="panel-body">
          <div className="filters">
            <div className="field span-2">
              <label>Search approval, requester, client, vendor or trip</label>
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
              <label>Queue</label>
              <select
                className="input"
                value={status}
                onChange={(e) => {
                  setStatus(e.target.value);
                  setPage(1);
                }}
              >
                <option>PENDING</option>
                <option>PARTIALLY_APPROVED</option>
                <option>APPROVED</option>
                <option>CHANGES_REQUESTED</option>
                <option>REJECTED</option>
                <option value="">ALL</option>
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
        {approvals.isPending ? (
          <Loading />
        ) : approvals.error ? (
          <ErrorNotice error={approvals.error} />
        ) : rows.length === 0 ? (
          <Empty message="This approval queue is clear." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Approval</th>
                  <th>Requester</th>
                  <th>Submitted</th>
                  <th>Lines</th>
                  <th>Vendors</th>
                  <th className="money">Gross</th>
                  <th className="money">TDS</th>
                  <th className="money">Net</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((batch) => (
                  <tr key={batch.id}>
                    <td>
                      <DetailLink href={`/approvals/${batch.id}`}>{batch.approval_no}</DetailLink>
                      <div className="muted">Revision {batch.revision_no}</div>
                    </td>
                    <td>{batch.requester_name}</td>
                    <td>
                      <DateText value={batch.submitted_at} />
                    </td>
                    <td>{batch.items.length}</td>
                    <td>{batch.vendor_subtotals.length}</td>
                    <td className="money">
                      <Money value={batch.gross_requested} />
                    </td>
                    <td className="money">
                      <Money value={batch.tds_requested} />
                    </td>
                    <td className="money">
                      <strong>
                        <Money value={batch.net_requested} />
                      </strong>
                    </td>
                    <td>
                      <StatusBadge value={batch.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {approvals.data && <Pagination count={approvals.data.count} page={page} pageSize={pageSize} onPage={setPage} />}
      </div>
    </>
  );
}
