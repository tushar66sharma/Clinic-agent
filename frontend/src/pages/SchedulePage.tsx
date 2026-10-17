import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { Badge, Button, EmptyState, ErrorState, PageHeader, Spinner, cx, humanize } from "../components/ui";
import { useApi } from "../hooks";

export function SchedulePage() {
  const [day, setDay] = useState<string>("");
  const sched = useApi(() => api.schedule(day || undefined), [day]);
  const s = sched.data;

  return (
    <>
      <PageHeader title="Schedule" description="Booked appointments per provider. Bookings made or moved by the agent in this session are highlighted." />
      <div className="mb-4 flex flex-wrap items-end gap-2">
        <Button variant="secondary" aria-label="Previous day" disabled={!s} onClick={() => s && setDay(s.prev)} icon={<ChevronLeft className="size-4" aria-hidden />} />
        <div>
          <label htmlFor="day" className="label">Date</label>
          <input id="day" type="date" className="input" value={day || s?.date || ""} onChange={(e) => setDay(e.target.value)} />
        </div>
        <Button variant="secondary" aria-label="Next day" disabled={!s} onClick={() => s && setDay(s.next)} icon={<ChevronRight className="size-4" aria-hidden />} />
      </div>
      {sched.loading && <Spinner />}
      {sched.error && <ErrorState message={sched.error} onRetry={() => sched.reload()} />}
      {s && !sched.loading && (
        <>
          <h2 className="mb-3 text-lg font-semibold">{s.weekday} {s.date}</h2>
          {!s.open ? (
            <div className="card"><EmptyState title={`Clinic closed (${s.closed_reason})`}>No appointments can be booked on this day.</EmptyState></div>
          ) : (
            <div className="grid gap-4 md:grid-cols-3">
              {s.providers.map((p) => (
                <section key={p.id} className="card" aria-label={p.name}>
                  <header className="flex items-center justify-between border-b border-line px-4 py-3">
                    <h3 className="text-sm font-semibold">{p.name}</h3>
                    {p.on_leave ? <Badge tone="urgent">On leave</Badge> : <Badge>{p.appointments.filter((a) => a.status === "booked").length} booked</Badge>}
                  </header>
                  {p.appointments.length === 0 ? <EmptyState title={p.on_leave ? "On leave" : "No bookings"} /> : (
                    <ul className="divide-y divide-line">
                      {p.appointments.map((a) => (
                        <li key={a.appointment_id} className={cx("px-4 py-2 text-sm", a.changed_this_session && "bg-success-bg/50", a.status === "cancelled" && "opacity-60")}>
                          <div className="flex items-center justify-between gap-2">
                            <span className={cx("font-mono", a.status === "cancelled" && "line-through")}>{a.start}–{a.end}</span>
                            <span className="flex gap-1">
                              {a.changed_this_session && <Badge tone="success">Agent</Badge>}
                              {a.status === "cancelled" && <Badge tone="danger">Cancelled</Badge>}
                            </span>
                          </div>
                          <p className="text-ink-muted">{humanize(a.visit_type)} · {a.patient_name ?? a.patient_id}</p>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              ))}
            </div>
          )}
        </>
      )}
    </>
  );
}
