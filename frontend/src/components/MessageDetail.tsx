// Everything about one processed message: what came in, what the agent did, and why.

import { Check, Copy, ShieldAlert, Wrench } from "lucide-react";
import { useState } from "react";
import type { ProcessedItem } from "../types";
import { ActionChip, Badge, Card, QueueChip, UrgencyBadge, cx, humanize } from "./ui";

const PATH_TEXT: Record<string, string> = {
  emergency_fast_path: "Emergency red flags detected by the safety guard. Escalated immediately, without calling the AI.",
  emergency_model: "The AI judged this a possible emergency. Escalated with the fixed safe reply.",
  standard: "AI analysed the message; code carried out the actions through the clinic tools; AI wrote the reply from verified facts.",
  fallback_no_model: "The AI was unavailable, so the message was handed to a person.",
};

export function MessageDetail({ item }: { item: ProcessedItem }) {
  const { message, result, trace } = item;
  return (
    <div className="flex flex-col gap-4">
      <Card title={<span>Message {message.id}</span>}
        actions={<span className="text-xs text-ink-subtle">{message.channel.toUpperCase()} · {formatTime(message.received_at)}</span>}>
        <p className="text-sm font-medium text-ink">{message.from_name} <span className="font-normal text-ink-subtle">({message.from_contact})</span></p>
        <blockquote className="mt-2 border-l-4 border-line pl-3 text-sm text-ink whitespace-pre-wrap">{message.body}</blockquote>
      </Card>

      {result.urgency === "emergency" && (
        <div role="alert" className="flex items-start gap-3 rounded-xl border border-emergency-solid/30 bg-emergency-bg px-4 py-3 text-sm text-emergency-fg">
          <ShieldAlert className="mt-0.5 size-5 shrink-0" aria-hidden />
          <p><strong>Possible emergency.</strong> Escalated to the urgent clinician queue. The patient was told to call 911 or go to the nearest emergency department. No automated medical advice was given.</p>
        </div>
      )}

      <Card title="Outcome">
        <dl className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
          <Field label="Urgency"><UrgencyBadge urgency={result.urgency} /></Field>
          <Field label="Patient">{result.patient_id ?? <span className="text-ink-subtle">Not identified</span>}
            {result.patient_id && <span className="ml-2 text-xs text-ink-subtle">{trace.verified ? `verified${trace.relationship === "caregiver" ? " (caregiver)" : ""}` : "not verified"}</span>}
          </Field>
          <Field label="Intents"><Chips items={result.intents.map((i) => <Badge key={i}>{humanize(i)}</Badge>)} /></Field>
          <Field label="Routed to">{result.routed_to.length ? <Chips items={result.routed_to.map((q) => <QueueChip key={q} queue={q} />)} /> : <span className="text-ink-subtle">No hand-off</span>}</Field>
          <Field label="Actions" className="sm:col-span-2"><Chips items={result.actions.map((a) => <ActionChip key={a} action={a} />)} /></Field>
        </dl>
      </Card>

      <ReplyCard text={result.reply_draft} />

      <Card title="How the agent decided">
        <p className="text-sm text-ink-muted">{PATH_TEXT[trace.path] ?? trace.path}</p>
        {trace.guard && trace.guard.level !== "none" && (
          <p className="mt-2 text-sm"><span className="font-medium">Safety guard:</span> {trace.guard.level} ({trace.guard.matches.map(humanize).join(", ")})</p>
        )}
        {trace.facts.length > 0 && (
          <>
            <h3 className="mt-4 text-xs font-semibold uppercase tracking-wide text-ink-muted">Facts given to the reply writer</h3>
            <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">{trace.facts.map((f, i) => <li key={i}>{f}</li>)}</ul>
          </>
        )}
        {trace.notes.length > 0 && (
          <>
            <h3 className="mt-4 text-xs font-semibold uppercase tracking-wide text-ink-muted">Notes</h3>
            <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-ink-muted">{trace.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
          </>
        )}
        {trace.llm_error && <p className="mt-3 text-sm text-danger-fg">AI error: {trace.llm_error}</p>}
        {trace.analysis && (
          <details className="mt-4">
            <summary className="cursor-pointer text-sm font-medium text-brand-700">AI analysis (raw)</summary>
            <pre className="mt-2 max-h-80 overflow-auto rounded-lg bg-neutral-bg p-3 text-xs">{JSON.stringify(trace.analysis, null, 2)}</pre>
          </details>
        )}
      </Card>

      <Card title={<span className="inline-flex items-center gap-2"><Wrench className="size-4" aria-hidden /> Tool calls ({trace.tool_trace.length})</span>}>
        <ol className="flex flex-col gap-2">
          {trace.tool_trace.map((c, i) => (
            <li key={i}>
              <details className="rounded-lg border border-line">
                <summary className="flex cursor-pointer items-center justify-between gap-2 px-3 py-2 text-sm">
                  <span className="font-mono text-xs sm:text-sm"><span className="text-ink-subtle">{i + 1}.</span> {c.tool}</span>
                  <span className="flex items-center gap-2">
                    <Badge tone={c.result?.ok === false ? "danger" : "success"}>{c.result?.ok === false ? "refused" : "ok"}</Badge>
                    <span className="text-xs text-ink-subtle">{c.ms} ms</span>
                  </span>
                </summary>
                <div className="grid gap-2 border-t border-line p-3 md:grid-cols-2">
                  <JsonBlock title="Arguments" value={c.args} />
                  <JsonBlock title="Result" value={c.result} />
                </div>
              </details>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}

function ReplyCard({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Card title="Reply draft (for staff review)"
      actions={text ? (
        <button onClick={() => navigator.clipboard?.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000); })}
          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-brand-700 hover:bg-brand-50">
          {copied ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />} {copied ? "Copied" : "Copy"}
        </button>
      ) : undefined}>
      {text ? <p className="whitespace-pre-wrap text-sm leading-relaxed">{text}</p>
        : <p className="text-sm text-ink-subtle">No reply (no action needed).</p>}
    </Card>
  );
}

function Field({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={className}>
      <dt className="text-xs font-semibold uppercase tracking-wide text-ink-muted">{label}</dt>
      <dd className="mt-1">{children}</dd>
    </div>
  );
}

function Chips({ items }: { items: React.ReactNode[] }) {
  return <div className="flex flex-wrap gap-1.5">{items}</div>;
}

function JsonBlock({ title, value }: { title: string; value: unknown }) {
  return (
    <div className={cx("min-w-0")}>
      <p className="mb-1 text-xs font-semibold text-ink-muted">{title}</p>
      <pre className="max-h-64 overflow-auto rounded-md bg-neutral-bg p-2 text-xs">{JSON.stringify(value, null, 2)}</pre>
    </div>
  );
}

export function formatTime(iso: string): string {
  const m = iso.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/);
  return m ? `${m[1]} ${m[2]}` : iso;
}
