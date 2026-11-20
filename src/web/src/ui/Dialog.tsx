// The one dialog of the design language: a title, a body, and a footer whose last button is the action
// (UX-037, ADR-0111). On a phone it is a sheet that rises from the bottom.
import * as Primitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { FormEvent, ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { IconButton } from "./Button";
import { cx } from "./cx";

const WIDTHS = { sm: "sm:max-w-dialog-sm", md: "sm:max-w-dialog-md", lg: "sm:max-w-dialog-lg" };

export function Dialog({
  open = true,
  onClose,
  title,
  description,
  descriptionHidden = false,
  size = "md",
  asks = false,
  leading,
  footer,
  footerStart,
  onSubmit,
  children,
}: {
  open?: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  /** The description is only for assistive technologies. */
  descriptionHidden?: boolean;
  size?: keyof typeof WIDTHS;
  /** The dialog asks before something that cannot be undone: it has no close button, and is announced as an alert. */
  asks?: boolean;
  leading?: ReactNode;
  /** The buttons, the action last. A dialog without them has a button that closes it. */
  footer?: ReactNode;
  /** What stands apart at the start of the footer, such as a button that tests what the dialog adds. */
  footerStart?: ReactNode;
  /** The dialog is a form: its body and its footer are inside it, and the action submits it. */
  onSubmit?: (event: FormEvent<HTMLFormElement>) => void;
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  const body = (
    <>
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-6">{children}</div>
      {footer && (
        <footer className="flex flex-none flex-wrap items-center justify-end gap-2 border-t border-line px-6 py-4 max-sm:flex-col-reverse max-sm:items-stretch">
          {footerStart && <div className="flex sm:mr-auto max-sm:flex-col">{footerStart}</div>}
          {footer}
        </footer>
      )}
    </>
  );
  return (
    <Primitive.Root open={open} onOpenChange={(next) => !next && onClose()}>
      <Primitive.Portal>
        <Primitive.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Primitive.Content
          {...(asks ? { role: "alertdialog" } : {})}
          {...(description ? {} : { "aria-describedby": undefined })}
          className={cx(
            "slide fixed z-50 flex flex-col bg-raised text-ink shadow-above outline-none",
            "max-sm:inset-x-0 max-sm:bottom-0 max-sm:max-h-[92dvh] max-sm:rounded-t-lg",
            "sm:top-1/2 sm:left-1/2 sm:max-h-[min(92dvh,48rem)] sm:w-[calc(100vw-2rem)] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-lg",
            WIDTHS[size],
          )}
        >
          <header className="flex items-start gap-4 px-6 pt-6">
            {leading}
            <div className="min-w-0 flex-1">
              <Primitive.Title className="text-title">{title}</Primitive.Title>
              {description && <Primitive.Description className={descriptionHidden ? "sr-only" : "mt-1 text-small text-ink-2"}>{description}</Primitive.Description>}
            </div>
            {!asks && !footer && (
              <Primitive.Close asChild>
                <IconButton label={t("ui.close")}>
                  <X aria-hidden="true" />
                </IconButton>
              </Primitive.Close>
            )}
          </header>
          {onSubmit ? (
            <form onSubmit={onSubmit} className="flex min-h-0 flex-1 flex-col">
              {body}
            </form>
          ) : (
            body
          )}
        </Primitive.Content>
      </Primitive.Portal>
    </Primitive.Root>
  );
}
