"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { StatusBadge } from "@/components/UI";

// Every document surface used to render a bare download link, so checking an
// evidence pack meant saving six files and opening them one by one. The viewer
// pages through them in place instead; `preview_url` is same-origin (the Next
// /api rewrite proxies it with the session cookie), so a plain <img> or <iframe>
// is authenticated without any fetch/blob dance.
export type ViewableDocument = {
  id: number;
  kind: string;
  original_name: string;
  scan_status: string;
  download_url: string;
  preview_url?: string;
  content_type?: string;
};

const FOCUSABLE = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])';

function label(document: ViewableDocument) {
  return document.kind.replaceAll("_", " ");
}

function Frame({ document }: { document: ViewableDocument }) {
  const type = document.content_type ?? "";
  const source = document.preview_url ?? `/api/documents/${document.id}/preview/`;
  if (type.startsWith("image/"))
    // eslint-disable-next-line @next/next/no-img-element -- a proxied API stream, not a static asset next/image can optimise.
    return <img className="doc-viewer-media" src={source} alt={`${label(document)} · ${document.original_name}`} />;
  if (type === "application/pdf")
    return <iframe className="doc-viewer-media" src={source} title={`${label(document)} · ${document.original_name}`} />;
  return (
    <div className="doc-viewer-fallback">
      <strong>Preview not available</strong>
      <p className="muted">
        {type ? `${type} files` : "This file type"} cannot be shown in the browser. Download it to open it in the
        right application.
      </p>
      <a className="button primary" href={document.download_url}>
        Download {document.original_name}
      </a>
    </div>
  );
}

export function DocumentViewer({
  documents,
  index,
  onIndex,
  onClose,
}: {
  documents: ViewableDocument[];
  index: number;
  onIndex: (index: number) => void;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDivElement>(null);
  const total = documents.length;
  const current = documents[index];

  const step = useCallback(
    (delta: number) => onIndex((index + delta + total) % total),
    [index, onIndex, total],
  );

  useEffect(() => {
    const opener = window.document.activeElement as HTMLElement | null;
    dialog.current?.focus();
    // Restore focus to whatever opened the viewer, so keyboard users land back
    // on the document they were reading rather than at the top of the page.
    return () => opener?.focus?.();
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      } else if (event.key === "ArrowRight") {
        step(1);
      } else if (event.key === "ArrowLeft") {
        step(-1);
      } else if (event.key === "Tab" && dialog.current) {
        const focusable = Array.from(dialog.current.querySelectorAll<HTMLElement>(FOCUSABLE));
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        const active = window.document.activeElement;
        if (event.shiftKey && (active === first || active === dialog.current)) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && active === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, step]);

  if (!current) return null;

  return (
    <div className="doc-viewer-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div
        className="doc-viewer"
        role="dialog"
        aria-modal="true"
        aria-label={`${label(current)} · ${current.original_name}`}
        ref={dialog}
        tabIndex={-1}
      >
        <div className="doc-viewer-head">
          <div>
            <strong>{label(current)}</strong>
            <div className="muted">{current.original_name}</div>
          </div>
          <div className="actions">
            <StatusBadge value={current.scan_status} />
            <button type="button" className="button small" onClick={onClose} aria-label="Close document viewer">
              Close
            </button>
          </div>
        </div>
        <div className="doc-viewer-stage">
          {total > 1 && (
            <button type="button" className="button small" onClick={() => step(-1)} aria-label="Previous document">
              ‹
            </button>
          )}
          <Frame document={current} />
          {total > 1 && (
            <button type="button" className="button small" onClick={() => step(1)} aria-label="Next document">
              ›
            </button>
          )}
        </div>
        <div className="doc-viewer-foot">
          <span className="muted" data-testid="doc-viewer-counter">
            {index + 1} of {total}
          </span>
          <div className="doc-viewer-strip">
            {documents.map((document, position) => (
              <button
                type="button"
                key={document.id}
                className={`button small${position === index ? " primary" : ""}`}
                aria-current={position === index}
                onClick={() => onIndex(position)}
              >
                {label(document)}
              </button>
            ))}
          </div>
          <a className="button small" href={current.download_url}>
            Download
          </a>
        </div>
      </div>
    </div>
  );
}

/** `const { open, viewer } = useDocumentViewer()` - render `viewer`, call `open(docs, i)`. */
export function useDocumentViewer() {
  const [state, setState] = useState<{ documents: ViewableDocument[]; index: number } | null>(null);
  const open = useCallback((documents: ViewableDocument[], index = 0) => {
    if (documents.length) setState({ documents, index });
  }, []);
  const viewer = state ? (
    <DocumentViewer
      documents={state.documents}
      index={state.index}
      onIndex={(index) => setState((old) => (old ? { ...old, index } : old))}
      onClose={() => setState(null)}
    />
  ) : null;
  return { open, viewer };
}

/** A row of document buttons that open the whole row as one deck. */
export function DocumentChips({
  documents,
  empty,
  onOpen,
  variant = "button small",
  render = (document) => `${label(document)} · ${document.original_name}`,
}: {
  documents: ViewableDocument[];
  empty: string;
  onOpen: (documents: ViewableDocument[], index: number) => void;
  variant?: string;
  render?: (document: ViewableDocument) => string;
}) {
  if (!documents.length) return empty ? <span className="muted">{empty}</span> : null;
  return (
    <div className="actions">
      {documents.map((document, index) => (
        <button type="button" className={variant} key={document.id} onClick={() => onOpen(documents, index)}>
          {render(document)}
        </button>
      ))}
    </div>
  );
}
