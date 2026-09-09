"use client";

import { FormEvent, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, listResults } from "@/lib/api";
import type { DocumentRecord, Paginated, User } from "@/lib/types";
import { DateText, Empty, ErrorNotice, Loading } from "@/components/UI";
import { DocumentChips, useDocumentViewer } from "@/components/DocumentViewer";

type Candidate = { id: number; label: string; role: string };
type Comment = {
  id: number;
  author: number;
  author_name: string;
  body: string;
  visibility: string;
  parent: number | null;
  mentions: number[];
  attachments: DocumentRecord[];
  edit_history: Array<{ body: string; edited_at: string }>;
  edited_at?: string;
  created_at: string;
};

export function CommentsPanel({
  objectType,
  objectId,
  title = "Discussion",
}: {
  objectType: "approval" | "trip" | "payment";
  objectId: string | number;
  title?: string;
}) {
  const [body, setBody] = useState("");
  const [visibility, setVisibility] = useState("INTERNAL");
  const [mentions, setMentions] = useState<number[]>([]);
  const [parent, setParent] = useState<number | null>(null);
  const [editing, setEditing] = useState<Comment | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const { open: openDocument, viewer } = useDocumentViewer();
  const comments = useQuery({
    queryKey: ["comments", objectType, objectId],
    queryFn: () => api<Paginated<Comment>>(`/comments/?object_type=${objectType}&object_id=${objectId}&page_size=200`),
  });
  const people = useQuery({
    queryKey: ["mention-candidates"],
    queryFn: () => api<Candidate[]>("/comments/mention-candidates/"),
  });
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<User>("/auth/me/") });
  const rows = comments.data ? listResults(comments.data) : [];

  const reset = () => {
    setBody("");
    setVisibility("INTERNAL");
    setMentions([]);
    setParent(null);
    setEditing(null);
    setFile(null);
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      if (editing) {
        await api(`/comments/${editing.id}/`, {
          method: "PATCH",
          body: JSON.stringify({ body, visibility, mentions }),
        });
      } else {
        const created = await api<Comment>("/comments/", {
          method: "POST",
          body: JSON.stringify({
            object_type: objectType,
            object_id: String(objectId),
            body,
            visibility,
            mentions,
            parent,
          }),
        });
        if (file) {
          const upload = new FormData();
          upload.append("file", file);
          upload.append("kind", "OTHER");
          upload.append("object_type", "comment");
          upload.append("object_id", String(created.id));
          await api("/documents/", { method: "POST", body: upload });
        }
      }
      reset();
      await comments.refetch();
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(false);
    }
  };
  const beginReply = (comment: Comment) => {
    reset();
    setParent(comment.id);
    setBody(`@${comment.author_name} `);
  };
  const beginEdit = (comment: Comment) => {
    setEditing(comment);
    setParent(comment.parent);
    setBody(comment.body);
    setVisibility(comment.visibility);
    setMentions(comment.mentions);
  };

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>{title}</h2>
        <span className="muted">{rows.length} comment(s)</span>
      </div>
      <div className="panel-body">
        {Boolean(error) && <ErrorNotice error={error} />}
        {comments.isPending ? (
          <Loading />
        ) : rows.length === 0 ? (
          <Empty message="No comments yet." />
        ) : (
          <div className="timeline">
            {rows.map((entry) => (
              <div className="timeline-item" key={entry.id} style={{ marginLeft: entry.parent ? 24 : 0 }}>
                <strong>{entry.author_name}</strong>
                <small>
                  <DateText value={entry.created_at} /> · {entry.visibility.replaceAll("_", " ")}
                  {entry.edited_at ? " · edited" : ""}
                </small>
                <p>{entry.body}</p>
                {entry.attachments?.length > 0 && (
                  <DocumentChips
                    documents={entry.attachments}
                    empty=""
                    onOpen={openDocument}
                    render={(doc) => doc.original_name}
                  />
                )}
                <div className="actions">
                  <button type="button" className="button small" onClick={() => beginReply(entry)}>
                    Reply
                  </button>
                  {me.data?.id === entry.author && (
                    <button type="button" className="button small" onClick={() => beginEdit(entry)}>
                      Edit
                    </button>
                  )}
                  {entry.edit_history.length > 0 && (
                    <span className="muted">{entry.edit_history.length} previous version(s)</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
        <form onSubmit={submit} style={{ marginTop: 20 }}>
          <div className="form-grid two">
            <div className="field span-2">
              <label>{editing ? "Edit comment" : parent ? `Replying to comment #${parent}` : "Add comment"}</label>
              <textarea
                required
                className="input"
                value={body}
                onChange={(e) => setBody(e.target.value)}
                placeholder="Record context or mention a teammate…"
              />
            </div>
            <div className="field">
              <label>Visibility</label>
              <select className="input" value={visibility} onChange={(e) => setVisibility(e.target.value)}>
                <option value="INTERNAL">Internal team only</option>
                <option value="TRANSPORTER_VISIBLE">Visible to transporter</option>
              </select>
            </div>
            <div className="field">
              <label>Mention teammates</label>
              <select
                multiple
                className="input"
                value={mentions.map(String)}
                onChange={(e) => setMentions(Array.from(e.target.selectedOptions, (option) => Number(option.value)))}
              >
                {people.data?.map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.label} · {person.role}
                  </option>
                ))}
              </select>
            </div>
            {!editing && (
              <div className="field span-2">
                <label>Attachment (optional)</label>
                <input
                  className="input"
                  type="file"
                  accept=".pdf,.png,.jpg,.jpeg,.xlsx"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                />
              </div>
            )}
          </div>
          <div className="actions" style={{ marginTop: 8 }}>
            {(editing || parent) && (
              <button type="button" className="button" onClick={reset}>
                Cancel
              </button>
            )}
            <button className="button primary" disabled={busy}>
              {busy ? "Saving…" : editing ? "Save edit" : parent ? "Post reply" : "Post comment"}
            </button>
          </div>
        </form>
      </div>
      {viewer}
    </section>
  );
}
