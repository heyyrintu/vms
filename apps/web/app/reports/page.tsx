"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Empty, ErrorNotice, Loading, PageHeader, Pagination } from "@/components/UI";

type Catalog = { slug: string; name: string };
type Report = {
  slug: string;
  name: string;
  columns: string[];
  count: number;
  rows: Array<Record<string, unknown>>;
  totals: Record<string, unknown>;
};

const display = (value: unknown) => (value === null || value === undefined || value === "" ? "—" : String(value));

export default function ReportsPage() {
  const catalog = useQuery({ queryKey: ["report-catalog"], queryFn: () => api<Catalog[]>("/reports/") });
  const [slug, setSlug] = useState("approved-unpaid");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);
  const query = new URLSearchParams({
    page: String(page),
    page_size: "50",
    ...(dateFrom && { date_from: dateFrom }),
    ...(dateTo && { date_to: dateTo }),
  });
  const report = useQuery({
    queryKey: ["report", slug, dateFrom, dateTo, page],
    queryFn: () => api<Report>(`/reports/${slug}/?${query}`),
    enabled: Boolean(slug),
  });
  const exportHref = (format: string) =>
    `/api/reports/${slug}/?${new URLSearchParams({ ...Object.fromEntries(query), format })}`;
  return (
    <>
      <PageHeader
        title="Reports & transition exports"
        description="Operational and financial reporting with consistent definitions, filters, totals, CSV and XLSX output."
      >
        <a className="button" href="/api/imports/excel/export/">
          Legacy Excel export
        </a>
        <a className="button" href={exportHref("csv")}>
          CSV
        </a>
        <a className="button primary" href={exportHref("xlsx")}>
          XLSX
        </a>
      </PageHeader>
      <section className="panel">
        <div className="panel-body filters">
          <div className="field span-2">
            <label>Report</label>
            <select
              className="input"
              value={slug}
              onChange={(e) => {
                setSlug(e.target.value);
                setPage(1);
              }}
            >
              {catalog.data?.map((item) => (
                <option key={item.slug} value={item.slug}>
                  {item.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>From date</label>
            <input
              className="input"
              type="date"
              value={dateFrom}
              onChange={(e) => {
                setDateFrom(e.target.value);
                setPage(1);
              }}
            />
          </div>
          <div className="field">
            <label>To date</label>
            <input
              className="input"
              type="date"
              value={dateTo}
              onChange={(e) => {
                setDateTo(e.target.value);
                setPage(1);
              }}
            />
          </div>
        </div>
      </section>
      {catalog.error ? (
        <ErrorNotice error={catalog.error} />
      ) : report.isPending ? (
        <Loading />
      ) : report.error ? (
        <ErrorNotice error={report.error} />
      ) : (
        <section className="panel">
          <div className="panel-head">
            <h2>{report.data!.name}</h2>
            <span className="eyebrow">{report.data!.count} rows</span>
          </div>
          {report.data!.rows.length === 0 ? (
            <Empty />
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    {report.data!.columns.map((column) => (
                      <th key={column}>{column.replaceAll("_", " ")}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {report.data!.rows.map((row, index) => (
                    <tr key={index}>
                      {report.data!.columns.map((column) => (
                        <td key={column}>{display(row[column])}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
                {Object.keys(report.data!.totals).length > 0 && (
                  <tfoot>
                    <tr>
                      {report.data!.columns.map((column, index) => (
                        <td key={column}>
                          <strong>{index === 0 ? "Totals" : display(report.data!.totals[column])}</strong>
                        </td>
                      ))}
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>
          )}
          <Pagination count={report.data!.count} page={page} pageSize={50} onPage={setPage} />
        </section>
      )}
    </>
  );
}
