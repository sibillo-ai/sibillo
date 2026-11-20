// Actions or options that float above the page (UX-037, ADR-0111).
import * as Primitive from "@radix-ui/react-dropdown-menu";
import type { ReactNode } from "react";

import { cx } from "./cx";

const CONTENT = "z-50 min-w-40 rounded-md border border-line bg-raised p-1 text-body text-ink shadow-float";
const ITEM =
  "flex h-8 cursor-pointer items-center gap-2 rounded-sm px-2 outline-none select-none data-[disabled]:cursor-not-allowed data-[disabled]:opacity-45 data-[highlighted]:bg-hover pointer-coarse:min-h-11 [&_svg]:size-4 [&_svg]:flex-none";

/** A menu, opened by its trigger: a shared button. */
export function Menu({ trigger, align = "start", children }: { trigger: ReactNode; align?: "start" | "end"; children: ReactNode }) {
  return (
    <Primitive.Root>
      <Primitive.Trigger asChild>{trigger}</Primitive.Trigger>
      <Primitive.Portal>
        <Primitive.Content align={align} sideOffset={4} collisionPadding={8} className={CONTENT}>
          {children}
        </Primitive.Content>
      </Primitive.Portal>
    </Primitive.Root>
  );
}

export function MenuItem({
  icon,
  end,
  danger = false,
  disabled = false,
  onSelect,
  children,
}: {
  icon?: ReactNode;
  /** A value or a shortcut, at the end of the item. */
  end?: ReactNode;
  danger?: boolean;
  disabled?: boolean;
  onSelect: () => void;
  children: ReactNode;
}) {
  return (
    <Primitive.Item disabled={disabled} onSelect={onSelect} className={cx(ITEM, danger && "text-danger")}>
      {icon}
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {end && <span className="text-caption text-ink-3">{end}</span>}
    </Primitive.Item>
  );
}

/** A menu inside an item, such as the folders a conversation moves to. */
export function MenuSub({ label, icon, children }: { label: string; icon?: ReactNode; children: ReactNode }) {
  return (
    <Primitive.Sub>
      <Primitive.SubTrigger className={ITEM}>
        {icon}
        <span className="min-w-0 flex-1 truncate">{label}</span>
      </Primitive.SubTrigger>
      <Primitive.Portal>
        <Primitive.SubContent sideOffset={4} collisionPadding={8} className={CONTENT}>
          {children}
        </Primitive.SubContent>
      </Primitive.Portal>
    </Primitive.Sub>
  );
}

export function MenuLabel({ children }: { children: ReactNode }) {
  return <Primitive.Label className="px-2 pt-2 pb-1 text-caption font-medium text-ink-3">{children}</Primitive.Label>;
}

export function MenuSeparator() {
  return <Primitive.Separator className="-mx-1 my-1 border-t border-line" />;
}
