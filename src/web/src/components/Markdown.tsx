import { Check, Copy } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { highlight } from "../highlight";
import { Checkbox, IconButton } from "../ui";
import { CodeFrame } from "../ui/Panel";

/**
 * A message in Markdown, with tables, highlighted code and math (UX-002).
 * Raw HTML is never rendered and images are never loaded: a message cannot
 * run scripts or make the browser fetch anything.
 */
export function Markdown({ text }: { text: string }) {
  return (
    <div className="prose-message space-y-3 text-reading break-words">
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={COMPONENTS} skipHtml>
        {text}
      </ReactMarkdown>
    </div>
  );
}

// Headings step down within the type roles (ADR-0111): a message's own headings sit below the page's.
const HEADING = "mt-2 text-title";
const SUBHEADING = "mt-2 text-reading font-semibold";

const COMPONENTS: Components = {
  // The accent is not for links: they are ink, underlined.
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-ink underline underline-offset-2">
      {children}
    </a>
  ),
  // No remote resources: an image is shown as its description.
  img: ({ alt }) => <ImageText alt={alt} />,
  table: ({ children }) => (
    <div className="overflow-x-auto rounded-md border border-line">
      <table className="w-full border-collapse text-body [&_td]:border-b [&_td]:border-line [&_td]:px-3 [&_td]:py-2 [&_td]:align-top [&_th]:border-b [&_th]:border-line [&_th]:bg-sunken [&_th]:px-3 [&_th]:py-2 [&_th]:text-left [&_th]:font-semibold [&_tr:last-child_td]:border-b-0">
        {children}
      </table>
    </div>
  ),
  blockquote: ({ children }) => <blockquote className="space-y-3 border-l-2 border-line-strong pl-4 font-serif text-ink-2 italic">{children}</blockquote>,
  ul: ({ children }) => <ul className="list-disc space-y-1 pl-6 marker:text-ink-3">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal space-y-1 pl-6 marker:text-ink-3">{children}</ol>,
  h1: ({ children }) => <h3 className={HEADING}>{children}</h3>,
  h2: ({ children }) => <h3 className={HEADING}>{children}</h3>,
  h3: ({ children }) => <h4 className={SUBHEADING}>{children}</h4>,
  h4: ({ children }) => <h5 className={SUBHEADING}>{children}</h5>,
  h5: ({ children }) => <h6 className={SUBHEADING}>{children}</h6>,
  h6: ({ children }) => <h6 className={SUBHEADING}>{children}</h6>,
  // A task list's box, shown and named rather than offered as a control nobody can use.
  input: ({ type, checked }) => (type === "checkbox" ? <TaskBox done={checked === true} /> : null),
  pre: ({ children }) => <>{children}</>,
  code: ({ className, children }) => {
    const language = /language-([\w-]+)/.exec(className ?? "")?.[1];
    const code = String(children ?? "").replace(/\n$/, "");
    if (language === undefined && !code.includes("\n")) {
      return <code className="rounded-sm bg-hover px-1 py-px font-mono text-body">{children}</code>;
    }
    return <CodeBlock code={code} language={language ?? "text"} />;
  },
};

/** Code in its frame: the language and a button that copies it above, the highlighted code below. `flush` is for inside another frame. */
export function CodeBlock({ code, language, flush = false }: { code: string; language: string; flush?: boolean }) {
  const { t } = useTranslation();
  const [highlighted, setHighlighted] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let current = true;
    // Shiki escapes the code: the HTML it returns holds only the code's text.
    void highlight(code, language)
      .then((html) => current && setHighlighted(html))
      .catch(() => current && setHighlighted(null));
    return () => {
      current = false;
    };
  }, [code, language]);

  let body: ReactNode = <code>{code}</code>;
  if (highlighted !== null) body = <div className="shiki-block" dangerouslySetInnerHTML={{ __html: highlighted }} />;

  return (
    <CodeFrame
      flush={flush}
      title={<span className="font-mono">{language}</span>}
      actions={
        <IconButton
          label={copied ? t("message.copied") : t("message.copy")}
          onClick={() => {
            void navigator.clipboard.writeText(code).then(() => {
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            });
          }}
        >
          {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
        </IconButton>
      }
    >
      <pre className={flush ? "overflow-x-auto pt-3 font-mono text-small" : "overflow-x-auto p-3 font-mono text-small"}>{body}</pre>
    </CodeFrame>
  );
}

function ImageText({ alt }: { alt: string | undefined }) {
  const { t } = useTranslation();
  return <span className="italic">[{alt || t("message.image")}]</span>;
}

function TaskBox({ done }: { done: boolean }) {
  const { t } = useTranslation();
  return (
    <span className="mr-2 inline-flex align-middle">
      <Checkbox checked={done} disabled readOnly aria-label={t(done ? "tasks.status.completed" : "tasks.status.pending")} />
    </span>
  );
}
