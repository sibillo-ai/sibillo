// The assistant's questions to the user, and its task list (AGT-015, UX-009, ADR-0083).
import { Check, Circle, CircleDot, MessageCircleQuestion, X } from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Interrupt, PlanStep, Question } from "../api/client";
import type { ResumeEntry } from "../api/stream";
import { Button, TextInput } from "../ui";
import { ChoiceList, ChoiceRow, RequestCard, Step, StepList } from "../ui/RequestCard";

interface Choice {
  selected: string[];
  ownWords: string;
}

function questionsOf(interrupt: Interrupt): Question[] {
  return interrupt.metadata?.questions ?? [];
}

/** One question: its choices, and a field for the user's own words instead. */
function QuestionField({ question, choice, onChange }: { question: Question; choice: Choice; onChange: (choice: Choice) => void }) {
  const { t } = useTranslation();
  const name = useId();
  const own = useId();
  function toggle(label: string, on: boolean) {
    const selected = question.multi_select ? (on ? [...choice.selected, label] : choice.selected.filter((item) => item !== label)) : [label];
    onChange({ selected, ownWords: "" });
  }
  return (
    <fieldset className="flex min-w-0 flex-col gap-2">
      <legend className="mb-2 text-body font-semibold text-pretty">{question.question}</legend>
      <ChoiceList>
        {question.options.map((option) => (
          <ChoiceRow
            key={option.label}
            several={question.multi_select}
            name={name}
            checked={choice.selected.includes(option.label)}
            onChange={(on) => toggle(option.label, on)}
            title={option.label}
            description={option.description}
          />
        ))}
      </ChoiceList>
      <label htmlFor={own} className="sr-only">
        {t("questions.ownWords")}
      </label>
      <TextInput id={own} value={choice.ownWords} maxLength={2000} placeholder={t("questions.ownWords")} onChange={(event) => onChange({ selected: [], ownWords: event.target.value })} />
    </fieldset>
  );
}

/** The assistant's questions, in place of the message box until the user answers or skips them: one at a time. */
export function QuestionCard({ interrupts, onAnswer }: { interrupts: Interrupt[]; onAnswer: (resume: ResumeEntry[]) => void }) {
  const { t } = useTranslation();
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const [index, setIndex] = useState(0);
  const key = (interrupt: Interrupt, question: Question) => `${interrupt.id}\u0000${question.header}`;
  const choiceOf = (interrupt: Interrupt, question: Question) => choices[key(interrupt, question)] ?? { selected: [], ownWords: "" };
  const all = interrupts.flatMap((interrupt) => questionsOf(interrupt).map((question) => ({ interrupt, question })));
  const current = all[Math.min(index, all.length - 1)];
  const isAnswered = (interrupt: Interrupt, question: Question) => {
    const choice = choiceOf(interrupt, question);
    return choice.selected.length > 0 || choice.ownWords.trim() !== "";
  };
  const answered = all.every(({ interrupt, question }) => isAnswered(interrupt, question));
  const last = index >= all.length - 1;

  // A choice stays on its question: the user moves on with Next or the arrows (ADR-0083).
  function choose(interrupt: Interrupt, question: Question, choice: Choice) {
    setChoices((chosen) => ({ ...chosen, [key(interrupt, question)]: choice }));
  }

  function answer() {
    onAnswer(
      interrupts.map((interrupt) => ({
        interruptId: interrupt.id,
        status: "resolved",
        payload: {
          answers: questionsOf(interrupt).map((question) => {
            const choice = choiceOf(interrupt, question);
            return choice.ownWords.trim() !== "" ? { header: question.header, custom_answer: choice.ownWords.trim() } : { header: question.header, selected: choice.selected };
          }),
        },
      })),
    );
  }

  return (
    <RequestCard
      icon={<MessageCircleQuestion aria-hidden="true" />}
      title={t("questions.title")}
      step={
        all.length > 1
          ? {
              text: t("questions.counter", { number: index + 1, total: all.length }),
              previous: { label: t("questions.previous"), disabled: index === 0, onClick: () => setIndex(index - 1) },
              next: { label: t("questions.next"), disabled: index >= all.length - 1, onClick: () => setIndex(index + 1) },
            }
          : undefined
      }
      footer={
        <>
          <Button size="sm" onClick={() => onAnswer(interrupts.map((interrupt) => ({ interruptId: interrupt.id, status: "cancelled" })))}>
            {t("questions.skip")}
          </Button>
          {/* Next until the last question, then Answer (ADR-0083). */}
          {last ? (
            <Button variant="primary" size="sm" disabled={!answered} onClick={answer}>
              {t("questions.answer")}
            </Button>
          ) : (
            <Button variant="primary" size="sm" disabled={!current || !isAnswered(current.interrupt, current.question)} onClick={() => setIndex(index + 1)}>
              {t("questions.nextButton")}
            </Button>
          )}
        </>
      }
    >
      {current && (
        <QuestionField
          key={key(current.interrupt, current.question)}
          question={current.question}
          choice={choiceOf(current.interrupt, current.question)}
          onChange={(choice) => choose(current.interrupt, current.question, choice)}
        />
      )}
    </RequestCard>
  );
}

const STATUS_ICONS = {
  completed: Check,
  in_progress: CircleDot,
  pending: Circle,
  cancelled: X,
  blocked: Circle,
} as const;

/** The task list, as a checklist: what is done, what goes on, what is left (UX-009). */
export function TaskList({ steps }: { steps: PlanStep[] }) {
  const { t } = useTranslation();
  if (steps.length === 0) return null;
  const done = steps.filter((step) => step.status === "completed").length;
  return (
    <StepList summary={t("tasks.progress", { done, total: steps.length })} label={t("tasks.title")}>
      {steps.map((step) => {
        const Icon = STATUS_ICONS[step.status];
        const going = step.status === "in_progress";
        return (
          <Step
            key={step.id}
            icon={<Icon aria-hidden="true" />}
            state={t(`tasks.status.${step.status}`)}
            tone={going ? "going" : step.status === "cancelled" ? "dropped" : step.status === "completed" ? "past" : "pending"}
          >
            {going ? (step.active_form ?? step.content) : step.content}
          </Step>
        );
      })}
    </StepList>
  );
}
