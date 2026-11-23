import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, Route, Routes } from "react-router";

import { ConversationView } from "./components/ConversationView";
import { useSettings } from "./components/AssistantSettings";
import { McpSignIn } from "./components/McpSettings";
import { ChoosePassword } from "./components/Password";
import { Settings } from "./components/Settings";
import { Shell } from "./components/Shell";
import { SignIn } from "./components/SignIn";
import { Welcome } from "./components/Welcome";
import { browserLanguages, interfaceLanguage, showInterfaceIn } from "./i18n";
import { NoticeProvider, useNotify } from "./notices";
import { watchForUpdates } from "./update";
import { useMe } from "./session";

export function App() {
  const me = useMe();
  if (me === undefined) return null;
  return (
    <NoticeProvider>
      <NewVersion />
      {me === null ? <InterfaceLanguage preferred={null} /> : <PreferredInterfaceLanguage />}
      {me === null ? (
        <SignIn />
      ) : me.password_change_required ? (
        // Nothing else answers until the initial password is replaced (AUTH-012, ADR-0105).
        <ChoosePassword />
      ) : (
        <Routes>
          <Route element={<Shell me={me} />}>
            <Route index element={<Welcome me={me} />} />
            <Route path="c/:conversationId" element={<ConversationView />} />
            <Route path="settings" element={<Settings me={me} />} />
            {/* Where a sign-in to a remote MCP server comes back (ADR-0100). */}
            <Route path="mcp-sign-in/:serverId" element={<McpSignIn />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      )}
    </NoticeProvider>
  );
}

/** A new version of the app takes over; while the page cannot load it yet, a notice says it is ready (UX-040, ADR-0112). */
function NewVersion() {
  const { t } = useTranslation();
  const notify = useNotify();
  useEffect(() => {
    watchForUpdates(() =>
      notify({ kind: "info", lasting: true, title: t("update.ready"), text: t("update.when"), action: { label: t("update.load"), run: () => window.location.reload() } }),
    );
  }, [notify, t]);
  return null;
}

/** The interface in the user's preferred language, once their defaults are known (I18N-004, ADR-0135). */
function PreferredInterfaceLanguage() {
  const settings = useSettings();
  if (settings.data === undefined) return null;
  return <InterfaceLanguage preferred={settings.data.language ?? null} />;
}

/** The interface in the preferred language, else the browser's, else English, as soon as either changes. */
function InterfaceLanguage({ preferred }: { preferred: string | null }) {
  const language = interfaceLanguage(preferred, browserLanguages());
  useEffect(() => {
    void showInterfaceIn(language);
  }, [language]);
  useEffect(() => {
    const changed = () => void showInterfaceIn(interfaceLanguage(preferred, browserLanguages()));
    window.addEventListener("languagechange", changed);
    return () => window.removeEventListener("languagechange", changed);
  }, [preferred]);
  return null;
}
