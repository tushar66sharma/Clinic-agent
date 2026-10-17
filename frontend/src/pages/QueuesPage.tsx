import { RefreshCw, RotateCcw } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { ConfirmDialog, useToast } from "../components/feedback";
import { Badge, Button, Card, EmptyState, ErrorState, PageHeader, Spinner, Stat, UrgencyBadge, humanize } from "../components/ui";
import { errorMessage, useApi } from "../hooks";

const QUEUE_ORDER = ["clinician_urgent", "clinician_routine", "provider_refills", "front_desk", "billing"];

export function QueuesPage() {
  const log = useApi(() => api.queues());
  const [confirm, setConfirm] = useState(false);
  const [resetting, setResetting] = useState(false);
  const notify = useToast();

  async function reset() {
    setResetting(true);
    try {
      await api.reset();
      notify("success", "Clinic data reset to its starting state.");
      setConfirm(false);
      await log.reload();
    } catch (e) {
      notify("error", errorMessage(e));
    } finally {
      setResetting(false);
    }
  }

  const d = log.data;
  return (
    <>
      <PageHeader title="Staff queues" description="Everything the agent handed to people: tickets per queue, refill requests waiting for provider approval, flagged messages and appointment changes."
        actions={<>
          <Button variant="secondary" onClick={() => log.reload()} icon={<RefreshCw className="size-4" aria-hidden />}>Refresh</Button>
          <Button variant="danger" onClick={() => setConfirm(true)} icon={<RotateCcw className="size-4" aria-hidden />}>Reset clinic data</Button>
        </>} />
      {log.loading && <Spinner />}
      {log.error && <ErrorState message={log.error} onRetry={() => log.reload()} />}
      {d && (
        <div className="flex flex-col gap-6">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            {QUEUE_ORDER.map((q) => (
              <Stat key={q} label={humanize(q)} value={d.queue_tickets.filter((t) => t.queue === q).length}
                tone={q === "clinician_urgent" && d.queue_tickets.some((t) => t.queue === q) ? "bad" : "neutral"} />
            ))}
          </div>

          <Card title="Tickets">
            {d.queue_tickets.length === 0 ? <EmptyState title="No tickets yet">Process some messages from the inbox.</EmptyState> : (
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th scope="col">Queue</th><th scope="col">Priority</th><th scope="col">Message</th><th scope="col">Patient</th><th scope="col">Reason</th></tr></thead>
                  <tbody>
                    {[...d.queue_tickets].sort((a, b) => QUEUE_ORDER.indexOf(a.queue) - QUEUE_ORDER.indexOf(b.queue)).map((t) => (
                      <tr key={t.ticket_id}>
                        <td><Badge tone={t.queue === "clinician_urgent" ? "emergency" : "brand"}>{humanize(t.queue)}</Badge></td>
                        <td><UrgencyBadge urgency={t.priority} /></td>
                        <td className="font-mono text-xs">{t.message_id}</td>
                        <td>{t.patient_id ?? "—"}</td>
                        <td className="min-w-48">{t.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card title={`Refill requests awaiting provider approval (${d.refill_requests.length})`}>
              {d.refill_requests.length === 0 ? <EmptyState title="None" /> : (
                <ul className="divide-y divide-line text-sm">
                  {d.refill_requests.map((r) => (
                    <li key={r.request_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                      <span><span className="font-medium">{r.medication}</span> <span className="text-ink-subtle">· {r.patient_id} · {r.message_id}</span></span>
                      <Badge tone="urgent">Awaiting {r.prescriber}</Badge>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card title={`Flagged messages (${d.flags.length})`}>
              {d.flags.length === 0 ? <EmptyState title="None" /> : (
                <ul className="divide-y divide-line text-sm">
                  {d.flags.map((f, i) => (
                    <li key={i} className="py-2"><span className="font-mono text-xs">{f.message_id}</span> <q className="text-ink-muted">{f.excerpt}</q></li>
                  ))}
                </ul>
              )}
            </Card>
          </div>

          <Card title={`Appointment changes (${d.appointment_changes.length})`}>
            {d.appointment_changes.length === 0 ? <EmptyState title="None" /> : (
              <ul className="flex flex-wrap gap-2 text-sm">
                {d.appointment_changes.map((c, i) => (
                  <li key={i}><Badge tone="success">{humanize(c.kind)} {c.appointment_id}{c.replaces ? ` (was ${c.replaces})` : ""} · {c.message_id}</Badge></li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}
      <ConfirmDialog open={confirm} danger title="Reset clinic data?" confirmLabel="Reset" busy={resetting}
        onCancel={() => setConfirm(false)} onConfirm={reset}>
        All bookings, cancellations, tickets, refill requests and processed results from this session will be
        cleared, and the schedule returns to its starting state. This cannot be undone.
      </ConfirmDialog>
    </>
  );
}
