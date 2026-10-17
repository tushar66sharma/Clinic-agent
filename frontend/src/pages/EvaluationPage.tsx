import { CheckCircle2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { ActionChip, Badge, Card, EmptyState, ErrorState, PageHeader, Spinner, Stat, cx, pct } from "../components/ui";
import { useApi } from "../hooks";

const REPORT_LABELS: Record<string, string> = {
  "sample-40": "Sample (40)",
  "unseen-14": "Unseen (14)",
  "unseen-14-blind": "Unseen, blind run",
};

export function EvaluationPage() {
  const list = useApi(() => api.reports());
  const [name, setName] = useState<string | null>(null);
  const [onlyWrong, setOnlyWrong] = useState(false);
  useEffect(() => {
    if (!name && list.data?.items.length) setName(list.data.items.find((i) => i.name === "sample-40")?.name ?? list.data.items[0].name);
  }, [list.data, name]);
  const report = useApi(() => (name ? api.report(name) : Promise.resolve(null)), [name]);

  const ev = report.data?.evaluation;
  const h = ev?.headline;
  const rows = ev?.per_message.filter((m) => !onlyWrong || !m.fully_correct) ?? [];

  return (
    <>
      <PageHeader title="Evaluation" description="How the agent scores against the labelled answers. Results come from the published reports in the repository's reports/ folder." />
      {list.loading && <Spinner />}
      {list.error && <ErrorState message={list.error} onRetry={() => list.reload()} />}
      {list.data && list.data.items.length === 0 && <div className="card"><EmptyState title="No reports published">Run the evaluation harness with --publish.</EmptyState></div>}
      {list.data && list.data.items.length > 0 && (
        <div role="tablist" aria-label="Report" className="mb-5 flex flex-wrap gap-2">
          {list.data.items.map((r) => (
            <button key={r.name} role="tab" aria-selected={name === r.name} onClick={() => setName(r.name)}
              className={cx("min-h-10 rounded-lg px-3 py-2 text-sm font-medium",
                name === r.name ? "bg-brand-700 text-white" : "border border-line bg-surface text-ink-muted hover:text-ink")}>
              {REPORT_LABELS[r.name] ?? r.name}
            </button>
          ))}
        </div>
      )}
      {report.loading && name && <Spinner />}
      {report.error && <ErrorState message={report.error} onRetry={() => report.reload()} />}
      {ev && h && (
        <div className="flex flex-col gap-6">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Emergency recall" value={pct(h.emergency_recall)} hint={`${h.emergencies_total - h.emergencies_missed.length} of ${h.emergencies_total} escalated`} tone={h.emergencies_missed.length ? "bad" : "good"} />
            <Stat label="must_not violations" value={h.must_not_violations} hint={`Safety invariant issues: ${h.safety_invariant_issues}`} tone={h.must_not_violations ? "bad" : "good"} />
            <Stat label="Fully correct" value={`${h.fully_correct} / ${h.messages}`} hint="Urgency, actions, patient, no violations" />
            <Stat label="Urgency accuracy" value={pct(h.urgency_accuracy)} hint={`False alarms: ${h.false_alarms.length}`} />
            <Stat label="Action exact match" value={pct(h.action_exact_match)} hint={`F1 ${pct(h.action_f1)}`} />
            <Stat label="Patient identified" value={pct(h.patient_id_accuracy)} />
            <Stat label="Reply language" value={pct(h.reply_language_accuracy)} />
            <Stat label="Bookings correct" value={h.bookings_checked ? pct(h.booking_detail_accuracy) : "n/a"} hint={h.bookings_checked ? `${h.bookings_checked} checked` : "No booking details labelled"} />
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card title="Missed emergencies">
              {h.emergencies_missed.length === 0 ? <Good text="None. Every labelled emergency was escalated with the safe reply." />
                : <ul className="list-disc pl-5 text-sm text-danger-fg">{h.emergencies_missed.map((id) => <li key={id}>{id}</li>)}</ul>}
            </Card>
            <Card title="Safety rule violations">
              {ev.must_not_violations.length + ev.safety_invariant_issues.length === 0 ? <Good text="None found on any message." /> : (
                <ul className="space-y-1 text-sm text-danger-fg">
                  {ev.must_not_violations.map((v, i) => <li key={`v${i}`}><strong>{v.id}</strong> {v.code}: {v.evidence.join("; ")}</li>)}
                  {ev.safety_invariant_issues.map((v, i) => <li key={`i${i}`}><strong>{v.id}</strong> {v.issue}</li>)}
                </ul>
              )}
            </Card>
          </div>

          <Card title="Per message" actions={
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" className="size-4 accent-brand-700" checked={onlyWrong} onChange={(e) => setOnlyWrong(e.target.checked)} />
              Only differences
            </label>}>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th scope="col">Id</th><th scope="col">Result</th><th scope="col">Urgency</th><th scope="col">Actions</th><th scope="col">Difference</th></tr></thead>
                <tbody>
                  {rows.map((m) => (
                    <tr key={m.id}>
                      <td className="font-mono text-xs">{m.id}</td>
                      <td>{m.fully_correct ? <Badge tone="success">Correct</Badge> : <Badge tone="danger">Differs</Badge>}</td>
                      <td><Badge tone={m.urgency_ok ? m.urgency : "danger"}>{m.urgency}</Badge></td>
                      <td><div className="flex min-w-48 flex-wrap gap-1">{m.actions.map((a) => <ActionChip key={a} action={a} />)}</div></td>
                      <td className="min-w-56 text-xs text-ink-muted">
                        {[m.missing_actions.length ? `missing ${m.missing_actions.join(", ")}` : "",
                          m.extra_actions.length ? `extra ${m.extra_actions.join(", ")}` : "",
                          !m.urgency_ok ? `urgency accepted: ${m.accepted_urgency.join("/")}` : "",
                          !m.patient_ok ? `patient expected ${m.expected_patient_id}` : "",
                          ...(m.booking_issues ?? []), ...m.violations].filter(Boolean).join(" · ") || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <Card title="Cost and speed">
            <dl className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
              <div><dt className="text-ink-muted">Run time</dt><dd className="font-semibold">{String(ev.operations.run_seconds ?? "n/a")} s</dd></div>
              <div><dt className="text-ink-muted">Tokens (this run)</dt><dd className="font-semibold">{String(ev.operations.total_tokens ?? "n/a")}</dd></div>
              <div><dt className="text-ink-muted">Cost on free tier</dt><dd className="font-semibold">$0.00</dd></div>
              <div><dt className="text-ink-muted">At paid rates (this run)</dt><dd className="font-semibold">{ev.operations.cost_at_paid_rates_usd == null ? "n/a" : `$${ev.operations.cost_at_paid_rates_usd}`}</dd></div>
            </dl>
          </Card>
        </div>
      )}
    </>
  );
}

function Good({ text }: { text: string }) {
  return <p className="flex items-center gap-2 text-sm text-success-fg"><CheckCircle2 className="size-4" aria-hidden />{text}</p>;
}
