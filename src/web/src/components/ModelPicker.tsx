import { ChevronDown, Cloud, House } from "lucide-react";
import { type CSSProperties, type RefObject, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import type { EgressPolicy, ModelChoice, ModelOption } from "../api/client";
import { findModel, refusedBy, sameModel, shortPrice, useModels } from "../models";
import { Badge, Button, PickerEmpty, PickerGroup, PickerOption, PickerPanel, SearchInput, SelectButton } from "../ui";

// The space the panel keeps from the window's edges and from its button.
const MARGIN = 12;
const GAP = 8;
const HEIGHT = 480;

/**
 * A button showing a model, which opens the model picker: in the message box
 * (`compact`) and for the household's default model in the settings (UX-015).
 */
export function ModelSelect(props: {
  value: ModelChoice | null;
  onChange: (choice: ModelChoice) => void;
  compact?: boolean;
  label?: string;
  placeholder?: string;
  // Which models to offer: chat models unless said otherwise (ADR-0088).
  kind?: ModelOption["kind"];
  // Whose data egress policy marks remote models unavailable: the user's, or the household's for its
  // defaults (MOD-003, ADR-0091).
  policy?: "effective" | "household";
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const models = useModels();
  const chosen = findModel(models.data?.items, props.value);
  // Without a model, the message box offers to choose one when there is something to choose.
  if (props.compact && !chosen && !props.placeholder) return null;
  const local = chosen?.location === "local";
  const shown = chosen ? (props.compact ? chosen.name : `${chosen.name} · ${chosen.connection_name}`) : props.placeholder;
  const icon = chosen && (local ? <House aria-hidden="true" /> : <Cloud aria-hidden="true" />);
  // Where the model runs, in words beside its sign: the warning that a remote model's data leaves the household (MOD-010).
  const where = chosen && (local ? t("picker.runsLocally") : t("picker.runsRemotely", { connection: chosen.connection_name }));
  const named = [props.label ? `${props.label}: ${shown ?? ""}` : shown, where].filter(Boolean).join(", ");
  const trigger = {
    // The name holds what the button shows, so that it can be spoken as it reads (UX-007).
    ...(props.label || where ? { "aria-label": named } : {}),
    ...(where ? { title: where } : {}),
    "aria-haspopup": "dialog" as const,
    "aria-expanded": open,
    onClick: () => setOpen(!open),
  };
  return (
    <>
      {props.compact ? (
        <Button ref={button} variant="ghost" size="sm" shrink {...trigger}>
          {icon}
          <span className="truncate">{shown}</span>
          <ChevronDown aria-hidden="true" />
        </Button>
      ) : (
        <SelectButton ref={button} leading={icon} {...trigger}>
          {shown}
        </SelectButton>
      )}
      {open && models.data && (
        <ModelPicker
          anchor={button}
          options={models.data.items.filter((option) => option.kind === (props.kind ?? "chat"))}
          defaultModel={models.data.default}
          chosen={props.value}
          policy={models.data.egress[props.policy ?? "effective"]}
          onPick={(option) => {
            setOpen(false);
            props.onChange({ connection_id: option.connection_id, model: option.model });
          }}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

/** Where the panel fits: on the side of its button with more room, never past the window. */
function placement(anchor: HTMLElement): CSSProperties {
  const box = anchor.getBoundingClientRect();
  const width = Math.min(400, window.innerWidth - 2 * MARGIN);
  const left = Math.min(Math.max(MARGIN, box.right - width), window.innerWidth - width - MARGIN);
  const above = box.top - GAP - MARGIN;
  const below = window.innerHeight - box.bottom - GAP - MARGIN;
  if (above >= below) return { left, width, bottom: window.innerHeight - box.top + GAP, maxHeight: Math.min(HEIGHT, above) };
  return { left, width, top: box.bottom + GAP, maxHeight: Math.min(HEIGHT, below) };
}

/** Every model of the household's connections, searchable, grouped by connection (UX-015). */
function ModelPicker(props: {
  anchor: RefObject<HTMLElement | null>;
  options: ModelOption[];
  defaultModel: ModelChoice | null;
  chosen: ModelChoice | null;
  policy: EgressPolicy;
  onPick: (option: ModelOption) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [style, setStyle] = useState<CSSProperties | null>(null);
  const panel = useRef<HTMLDivElement>(null);
  const { anchor, onClose } = props;
  useLayoutEffect(() => {
    function place() {
      if (anchor.current) setStyle(placement(anchor.current));
    }
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [anchor]);
  useEffect(() => {
    function outside(event: MouseEvent) {
      const target = event.target as Node;
      // The button toggles the panel itself.
      if (panel.current?.contains(target) || anchor.current?.contains(target)) return;
      onClose();
    }
    function escape(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [anchor, onClose]);
  const needle = query.trim().toLowerCase();
  const matching = props.options.filter(
    (option) => !needle || option.name.toLowerCase().includes(needle) || option.connection_name.toLowerCase().includes(needle) || option.model.toLowerCase().includes(needle),
  );
  const groups = new Map<string, ModelOption[]>();
  for (const option of matching) groups.set(option.connection_id, [...(groups.get(option.connection_id) ?? []), option]);

  return createPortal(
    <PickerPanel
      ref={panel}
      label={t("picker.title")}
      style={style ?? { visibility: "hidden" }}
      header={<SearchInput autoFocus label={t("picker.search")} placeholder={t("picker.searchPlaceholder", { count: props.options.length })} value={query} onChange={(event) => setQuery(event.target.value)} />}
      footer={t("picker.footer")}
    >
      {matching.length === 0 && <PickerEmpty>{t("picker.none", { query })}</PickerEmpty>}
      {[...groups.values()].map((options) => {
        const first = options[0];
        if (first === undefined) return null;
        return (
          <PickerGroup
            key={first.connection_id}
            icon={first.location === "local" ? <House aria-hidden="true" /> : <Cloud aria-hidden="true" />}
            title={first.connection_name}
            end={first.location === "local" ? t("picker.local") : t("picker.remote")}
            note={refusedBy(props.policy, first) && t("picker.refused")}
          >
            {options.map((option) => (
              <PickerOption
                key={option.model}
                title={option.name}
                disabled={refusedBy(props.policy, option)}
                chosen={sameModel(option, props.chosen)}
                onPick={() => props.onPick(option)}
                badges={
                  <>
                    {sameModel(option, props.defaultModel) && <Badge tone="accent">{t("picker.default")}</Badge>}
                    {option.tools === false && <Badge>{t("picker.chatOnly")}</Badge>}
                    {option.images === true && <Badge>{t("picker.seesImages")}</Badge>}
                  </>
                }
                detail={
                  <>
                    {option.connection_name} ·{" "}
                    {option.location === "local"
                      ? t("picker.free")
                      : option.prices
                        ? t("picker.price", { input: shortPrice(option.prices.input), output: shortPrice(option.prices.output) })
                        : t("picker.unknownPrice")}
                  </>
                }
              />
            ))}
          </PickerGroup>
        );
      })}
    </PickerPanel>,
    document.body,
  );
}
