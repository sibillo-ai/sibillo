// The switch of internet access, in a conversation's top bar and on the new-chat screen (UX-042, AGT-034, ADR-0115).
import { Globe } from "lucide-react";
import { useId } from "react";
import { useTranslation } from "react-i18next";

import { useTools } from "../tools";
import { Switch } from "../ui";

/** On while the conversation, or the turn that is going on, has internet access; absent for a user denied it. */
export function InternetSwitch({ checked, onChange, disabled = false }: { checked: boolean; onChange: (on: boolean) => void; disabled?: boolean }) {
  const { t } = useTranslation();
  const tools = useTools();
  const label = useId();
  // A user whose permissions deny internet access has none to turn on (ADR-0113 point 5).
  const denied = tools.data?.some((tool) => tool.name === "request_internet_access" && tool.effective === "deny");
  if (!tools.data || denied) return null;
  return (
    <span className="flex flex-none items-center gap-2 px-1 text-small font-medium text-ink-2">
      <Globe className="size-4 flex-none" aria-hidden="true" />
      <span id={label} className="whitespace-nowrap max-md:sr-only">
        {t("internet.switch")}
      </span>
      <Switch aria-labelledby={label} title={t("internet.switchHint")} checked={checked} disabled={disabled} onChange={onChange} />
    </span>
  );
}
