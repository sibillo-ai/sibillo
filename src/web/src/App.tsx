import { Navigate, Route, Routes } from "react-router";

import { ConversationView } from "./components/ConversationView";
import { McpSignIn } from "./components/McpSettings";
import { ChoosePassword } from "./components/Password";
import { Settings } from "./components/Settings";
import { Shell } from "./components/Shell";
import { SignIn } from "./components/SignIn";
import { Welcome } from "./components/Welcome";
import { NoticeProvider } from "./notices";
import { useMe } from "./session";

export function App() {
  const me = useMe();
  if (me === undefined) return null;
  return (
    <NoticeProvider>
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
            <Route path="mcp-sign-in" element={<McpSignIn />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      )}
    </NoticeProvider>
  );
}
