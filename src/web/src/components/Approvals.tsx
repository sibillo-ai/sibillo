// Approval requests, in place of the message box until the user answers them (UX-022, AGT-007, ADR-0090), and the
// one request for internet access of a run (AGT-034, ADR-0113).
import { Globe, ShieldAlert, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ApprovalScope, Interrupt } from "../api/client";
import type { ResumeEntry } from "../api/stream";
import { toolLabel } from "../tools";
import { Button, Notice } from "../ui";
import { CodeBlock, Fact, Facts, RequestCard } from "../ui/RequestCard";

const SCOPE_ORDER: ApprovalScope[] = ["once", "turn", "conversation"];

/** The time left before a request is denied, in words. */
function useTimeLeft(expiresAt: string | undefined): string | null {
  const { t } = useTranslation();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  if (!expiresAt) return null;
  const minutes = Math.max(0, Math.round((Date.parse(expiresAt) - now) / 60_000));
  return minutes >= 60 ? t("approvals.deniedInHours", { count: Math.round(minutes / 60) }) : t("approvals.deniedInMinutes", { count: minutes });
}

/** The scopes an approval request offers, narrowest first. */
export function scopesOf(interrupt: Interrupt): ApprovalScope[] {
  const offered: ApprovalScope[] = interrupt.metadata?.internet_access?.scopes ?? interrupt.metadata?.approval?.scopes ?? [];
  return SCOPE_ORDER.filter((scope) => offered.includes(scope));
}

/** A request for internet access: what it lets the assistant do, what could go out, and the calls that wait. */
function InternetAccess({ interrupt }: { interrupt: Interrupt }) {
  const { t } = useTranslation();
  const request = interrupt.metadata?.internet_access;
  const timeLeft = useTimeLeft(interrupt.expiresAt);
  if (!request) return null;
  return (
    <div className="flex flex-col gap-2 text-body">
      <p className="flex items-center gap-2 font-semibold text-pretty">
        <Globe className="size-4 flex-none" aria-hidden="true" />
        {t("approvals.internet.title")}
      </p>
      <p className="text-pretty">{t("approvals.internet.does")}</p>
      <Notice role="note">{t("approvals.internet.sentOut")}</Notice>
      {/* Content from elsewhere in the run may be what asks (AGT-003). */}
      {request.untrusted_content && (
        <Notice tone="error" role="note" icon={<TriangleAlert aria-hidden="true" />}>
          <span className="font-semibold">{t("approvals.internet.untrusted")}</span>
        </Notice>
      )}
      {request.calls.length === 0 ? (
        <p className="text-small text-ink-2">{t("approvals.internet.asked")}</p>
      ) : (
        <>
          <p className="text-small font-semibold text-ink-2">{t("approvals.internet.waiting")}</p>
          {request.calls.map((call, index) => (
            <Facts key={index}>
              <Fact term={toolLabel(t, call.tool)} mono>
                {call.data}
              </Fact>
              <Fact term={t("approvals.destination")}>{call.destination}</Fact>
            </Facts>
          ))}
        </>
      )}
      {timeLeft && <p className="text-small text-ink-2">{timeLeft}</p>}
    </div>
  );
}

/** One approval request: what the call does, with what and where, and why it asks. */
function Request({ interrupt }: { interrupt: Interrupt }) {
  const { t } = useTranslation();
  const request = interrupt.metadata?.approval;
  const timeLeft = useTimeLeft(interrupt.expiresAt);
  if (interrupt.metadata?.internet_access) return <InternetAccess interrupt={interrupt} />;
  if (!request) return null;
  return (
    <div className="flex flex-col gap-2 text-body">
      <p className="font-semibold text-pretty">
        {toolLabel(t, request.tool)} <code className="font-mono text-small font-normal text-ink-2">{request.tool}</code>
      </p>
      {/* What the call does, unless it only repeats the tool's name. */}
      {request.action !== toolLabel(t, request.tool) && <p className="text-pretty">{request.action}</p>}
      <Facts>
        <Fact term={t("approvals.data")} mono>
          {request.data}
        </Fact>
        <Fact term={t("approvals.destination")}>{request.destination}</Fact>
      </Facts>
      <Notice role="note">{t(`approvals.reasons.${request.reason}`)}</Notice>
      {/* A proposed task from a chat with content from elsewhere may come from injected instructions (TSK-006). */}
      {request.reason === "task_proposal" && request.untrusted_content && (
        <Notice tone="error" role="note" icon={<TriangleAlert aria-hidden="true" />}>
          <span className="font-semibold">{t("approvals.proposalUntrusted")}</span>
        </Notice>
      )}
      {/* The arguments in full, as the model gave them (UX-003, AGT-007). */}
      <p className="text-small font-semibold text-ink-2">{t("approvals.arguments")}</p>
      <CodeBlock>{JSON.stringify(request.arguments, null, 2)}</CodeBlock>
      {timeLeft && <p className="text-small text-ink-2">{timeLeft}</p>}
    </div>
  );
}

/** The pending approval requests, one at a time: Deny first, never chosen for the user (UX-022). */
export function ApprovalCard({ interrupts, onDecided }: { interrupts: Interrupt[]; onDecided: (resume: ResumeEntry[]) => void }) {
  const { t } = useTranslation();
  const [decisions, setDecisions] = useState<ResumeEntry[]>([]);
  const current = interrupts[decisions.length];
  if (!current) return null;
  const scopes = scopesOf(current);

  function decide(entry: ResumeEntry) {
    const all = [...decisions, entry];
    if (all.length >= interrupts.length) onDecided(all);
    else setDecisions(all);
  }

  const decideWith = (scope: ApprovalScope) => decide({ interruptId: current.id, status: "resolved", payload: { approved: true, scope } });
  // The narrowest answer the request offers is the action; the ones that last longer stand apart.
  const [narrowest, ...longer] = scopes;
  return (
    <RequestCard
      tall
      icon={<ShieldAlert aria-hidden="true" />}
      title={t("approvals.title")}
      step={interrupts.length > 1 ? { text: t("questions.counter", { number: decisions.length + 1, total: interrupts.length }) } : undefined}
      footer={
        <>
          <Button size="sm" onClick={() => decide({ interruptId: current.id, status: "resolved", payload: { approved: false } })}>
            {t("approvals.deny")}
          </Button>
          {narrowest && (
            <Button variant="primary" size="sm" onClick={() => decideWith(narrowest)}>
              {t(`approvals.allow.${narrowest}`)}
            </Button>
          )}
        </>
      }
      footerStart={
        longer.length > 0 &&
        longer.map((scope) => (
          <Button key={scope} variant="ghost" size="sm" onClick={() => decideWith(scope)}>
            {t(`approvals.allow.${scope}`)}
          </Button>
        ))
      }
    >
      <Request key={current.id} interrupt={current} />
    </RequestCard>
  );
}
