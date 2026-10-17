import { KeyRound } from "lucide-react";
import { useState } from "react";
import { BASE, api, getToken, setToken } from "../api";
import { useToast } from "../components/feedback";
import { Badge, Button, Card, ErrorState, PageHeader, Spinner } from "../components/ui";
import { useApi } from "../hooks";

export function SystemPage() {
  const health = useApi(() => api.health());
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const clinic = useApi(() => api.clinic() as Promise<Record<string, any>>);
  const [token, setTokenValue] = useState(getToken());
  const notify = useToast();
  const h = health.data;

  return (
    <>
      <PageHeader title="System" description="Server status, the AI provider in use, clinic configuration and your access token." />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Status">
          {health.loading && <Spinner />}
          {health.error && <ErrorState message={health.error} onRetry={() => health.reload()} />}
          {h && (
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-ink-muted">API</dt><dd><Badge tone="success">{h.status}</Badge></dd>
              <dt className="text-ink-muted">Clinic date</dt><dd>{h.today}</dd>
              <dt className="text-ink-muted">AI provider</dt>
              <dd>{h.ai.configured ? <Badge tone="success">{h.ai.provider}</Badge> : <Badge tone="urgent">Not configured</Badge>}</dd>
              {h.ai.models && Object.entries(h.ai.models).map(([role, model]) => (
                <div key={role} className="contents"><dt className="text-ink-muted">Model ({role})</dt><dd className="font-mono text-xs">{model}</dd></div>
              ))}
              {h.ai.error && <><dt className="text-ink-muted">AI error</dt><dd className="text-danger-fg">{h.ai.error}</dd></>}
              <dt className="text-ink-muted">Access token</dt><dd>{h.access_token_required ? "Required for actions" : "Not required"}</dd>
              <dt className="text-ink-muted">API docs</dt><dd><a className="text-brand-700 underline" href={`${BASE}/api/docs`} target="_blank" rel="noreferrer">/api/docs</a></dd>
            </dl>
          )}
        </Card>

        <Card title={<span className="inline-flex items-center gap-2"><KeyRound className="size-4" aria-hidden />Access token</span>}>
          <p className="mb-3 text-sm text-ink-muted">If the server sets <code>DEMO_ACCESS_TOKEN</code>, processing messages and resetting data require it. It is kept only in this browser tab.</p>
          <form className="flex flex-col gap-2 sm:flex-row" onSubmit={(e) => { e.preventDefault(); setToken(token.trim()); notify("success", token.trim() ? "Access token saved for this tab." : "Access token cleared."); }}>
            <label htmlFor="token" className="sr-only">Access token</label>
            <input id="token" type="password" className="input" value={token} onChange={(e) => setTokenValue(e.target.value)} autoComplete="off" placeholder="Paste access token" />
            <Button type="submit">Save</Button>
          </form>
        </Card>

        <Card title="Clinic configuration" className="lg:col-span-2">
          {clinic.loading && <Spinner />}
          {clinic.error && <ErrorState message={clinic.error} onRetry={() => clinic.reload()} />}
          {clinic.data && (
            <div className="grid gap-4 text-sm md:grid-cols-3">
              <div>
                <h3 className="font-semibold">Hours</h3>
                <p className="text-ink-muted">{clinic.data.hours.days.join(", ")} · {clinic.data.hours.open}–{clinic.data.hours.close} · lunch {clinic.data.hours.lunch.join("–")}</p>
                <h3 className="mt-3 font-semibold">Holidays</h3>
                <p className="text-ink-muted">{clinic.data.holidays.join(", ")}</p>
              </div>
              <div>
                <h3 className="font-semibold">Providers</h3>
                <ul className="text-ink-muted">{clinic.data.providers.map((p: any) => (
                  <li key={p.id}>{p.name} · {p.languages.join("/")}{p.leave.length ? ` · leave ${p.leave.map((l: string[]) => l.join(" to ")).join(", ")}` : ""}</li>
                ))}</ul>
              </div>
              <div>
                <h3 className="font-semibold">Visit lengths</h3>
                <ul className="text-ink-muted">{Object.entries(clinic.data.visit_type_minutes).map(([k, v]) => <li key={k}>{k.replace(/_/g, " ")}: {String(v)} min</li>)}</ul>
              </div>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
