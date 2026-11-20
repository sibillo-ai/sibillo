// The gallery of the shared components (ADR-0111): every one of them, in each of its states, in both themes.
// A reviewer compares it with the prototype (UX-017). It is a tool for development: `pnpm vite`, then
// /gallery.html. It is not part of the app, so its sample text is written here and not translated.
import "@fontsource/hanken-grotesk/400.css";
import "@fontsource/hanken-grotesk/500.css";
import "@fontsource/hanken-grotesk/600.css";
import "@fontsource/newsreader/400.css";
import "@fontsource/newsreader/500.css";
import "@fontsource/jetbrains-mono/400.css";
import "../src/styles.css";
import "../src/i18n";

import { Bell, CalendarClock, Check, Cloud, Copy, Ellipsis, Folder, House, LogOut, Plus, SlidersHorizontal, Trash2, Users } from "lucide-react";
import { type ReactNode, StrictMode, useId, useState } from "react";
import { createRoot } from "react-dom/client";

import {
  Avatar,
  Badge,
  Button,
  Card,
  Dialog,
  EmptyState,
  FormField,
  Group,
  IconButton,
  Loading,
  Menu,
  MenuItem,
  MenuLabel,
  MenuSeparator,
  NavItem,
  NavLabel,
  Notice,
  PageHeader,
  Radio,
  Row,
  SearchInput,
  Segmented,
  Select,
  Switch,
  TextArea,
  TextInput,
  Tile,
} from "../src/ui";

function Demo({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Group title={title}>
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-canvas p-6">{children}</div>
    </Group>
  );
}

function Gallery() {
  const [dark, setDark] = useState(false);
  const [local, setLocal] = useState(true);
  const [reasoning, setReasoning] = useState<"off" | "on" | "deep">("on");
  const [price, setPrice] = useState("low");
  const [dialog, setDialog] = useState<"form" | "ask" | null>(null);
  const localId = useId();
  const theme = () => {
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    setDark(!dark);
  };
  return (
    <main className="mx-auto flex max-w-read flex-col gap-12 px-6 py-12">
      <PageHeader title="Shared components">Screens are assembled from these. A screen never styles a button, a field or a dialog of its own.</PageHeader>
      <div>
        <Button onClick={theme}>{dark ? "Light theme" : "Dark theme"}</Button>
      </div>

      <Demo title="Button">
        <Button variant="primary">Primary</Button>
        <Button>Secondary</Button>
        <Button variant="ghost">Ghost</Button>
        <Button variant="danger">Remove</Button>
        <Button variant="danger-solid">Delete forever</Button>
        <Button>
          <Plus aria-hidden="true" />
          With icon
        </Button>
        <IconButton label="More" variant="secondary" size="md">
          <Ellipsis aria-hidden="true" />
        </IconButton>
      </Demo>
      <Demo title="Button, small and states">
        <Button variant="primary" size="sm">
          Small
        </Button>
        <Button size="sm">Small</Button>
        <Button variant="ghost" size="sm">
          <Folder aria-hidden="true" />
          Files
        </Button>
        <IconButton label="Copy">
          <Copy aria-hidden="true" />
        </IconButton>
        <IconButton label="Copying" busy>
          <Copy aria-hidden="true" />
        </IconButton>
        <Button variant="primary" disabled>
          Disabled
        </Button>
        <Button variant="primary" busy>
          Saving
        </Button>
      </Demo>

      <Group title="Fields">
        <div className="grid gap-4 rounded-lg border border-line bg-canvas p-6 sm:grid-cols-2">
          <FormField label="Name" hint="Shown in the list of tasks.">
            {(ties) => <TextInput {...ties} defaultValue="Morning briefing" />}
          </FormField>
          <FormField label="Address" error="Start the address with http:// or https://">
            {(ties) => <TextInput {...ties} mono defaultValue="htp://ollama.local" />}
          </FormField>
          <FormField label="Language">
            {(ties) => (
              <Select {...ties} defaultValue="auto">
                <option value="auto">The language of your messages</option>
                <option value="it">Italiano</option>
              </Select>
            )}
          </FormField>
          <FormField label="Disabled">{(ties) => <TextInput {...ties} disabled defaultValue="Cannot change" />}</FormField>
          <SearchInput label="Search conversations" />
          <span />
          <div className="sm:col-span-2">
            <FormField label="Instructions">{(ties) => <TextArea {...ties} defaultValue="Answer briefly. Use metric units." />}</FormField>
          </div>
        </div>
      </Group>

      <Demo title="Choices">
        <Switch checked={local} onChange={setLocal} aria-label="Use only local models" />
        <Switch checked={false} onChange={() => undefined} disabled aria-label="Disabled" />
        <Segmented
          label="Reasoning"
          value={reasoning}
          onChange={setReasoning}
          options={[
            { value: "off", label: "Off" },
            { value: "on", label: "On" },
            { value: "deep", label: "Deep" },
          ]}
        />
        <Badge>Remote</Badge>
        <Badge tone="ok">
          <Check aria-hidden="true" />
          513 models
        </Badge>
        <Badge tone="warn">Needs sign-in</Badge>
        <Badge tone="accent">New</Badge>
        <Avatar name="Ada" />
      </Demo>

      <Group title="Rows in a card" description="The one pattern for settings and for lists." action={<Button size="sm">Add connection</Button>}>
        <Card rows>
          <Row title="Use only local models" description="Your messages never leave the house." htmlFor={localId}>
            <Switch id={localId} checked={local} onChange={setLocal} />
          </Row>
          <Row title="Reasoning" description="How much the model thinks before it answers.">
            <Segmented
              label="Reasoning"
              value={reasoning}
              onChange={setReasoning}
              options={[
                { value: "off", label: "Off" },
                { value: "on", label: "On" },
                { value: "deep", label: "Deep" },
              ]}
            />
          </Row>
          <Row
            leading={
              <Tile>
                <Cloud />
              </Tile>
            }
            title={
              <>
                OpenRouter <Badge>Remote</Badge>
              </>
            }
            description={<span className="font-mono">https://openrouter.ai/api/v1</span>}
          >
            <Badge tone="ok">
              <Check aria-hidden="true" />
              513 models
            </Badge>
            <IconButton label="More">
              <Ellipsis aria-hidden="true" />
            </IconButton>
          </Row>
          <Row title="Instructions" description="Added to every new conversation." below={<TextArea aria-label="Instructions" defaultValue="Answer briefly." />} />
        </Card>
      </Group>

      <Group title="Radio, in rows">
        <Card rows>
          {[
            ["low", "Up to 2 €", "Supermarket bread flour"],
            ["high", "2 to 4 €", "Stone-ground, from a mill"],
          ].map(([value, title, description]) => (
            <Row key={value} title={title} description={description} htmlFor={`price-${value}`} leading={<Radio id={`price-${value}`} name="price" checked={price === value} onChange={() => setPrice(value ?? "")} />} />
          ))}
        </Card>
      </Group>

      <Group title="Notices and empty states">
        <div className="flex flex-col gap-3">
          <Notice icon={<Users />}>These settings apply to everyone in the household.</Notice>
          <Notice tone="warn" icon={<Bell />} title="Notifications are off." action={<Button size="sm">Turn on</Button>}>
            Allow them in the browser's site settings.
          </Notice>
          <Notice tone="error" title="The model did not answer." action={<Button size="sm">Try again</Button>}>
            The connection to Ollama timed out.
          </Notice>
          <Card>
            <EmptyState
              icon={<CalendarClock />}
              title="No tasks yet"
              action={
                <Button variant="primary">
                  <Plus aria-hidden="true" />
                  New task
                </Button>
              }
            >
              A task starts a conversation on its own, at the times you choose, and leaves the answer waiting for you.
            </EmptyState>
          </Card>
          <Card>
            <Loading />
          </Card>
        </div>
      </Group>

      <Demo title="Dialogs and menus">
        <Button onClick={() => setDialog("form")}>Open a dialog</Button>
        <Button variant="danger" onClick={() => setDialog("ask")}>
          Ask before deleting
        </Button>
        <Menu trigger={<Button>Open a menu</Button>}>
          <MenuLabel>Ada</MenuLabel>
          <MenuItem icon={<SlidersHorizontal />} onSelect={() => undefined}>
            Settings
          </MenuItem>
          <MenuItem icon={<House />} end="System" onSelect={() => undefined}>
            Theme
          </MenuItem>
          <MenuSeparator />
          <MenuItem icon={<LogOut />} onSelect={() => undefined}>
            Sign out
          </MenuItem>
          <MenuItem icon={<Trash2 />} danger onSelect={() => undefined}>
            Delete
          </MenuItem>
        </Menu>
      </Demo>

      <Group title="Navigation">
        <div className="w-full max-w-sidebar rounded-lg bg-sunken p-3">
          <NavLabel>Today</NavLabel>
          <NavItem current>Sourdough that will not rise</NavItem>
          <NavItem>Gift ideas for Nonna</NavItem>
          <NavLabel>Folders</NavLabel>
          <NavItem icon={<Folder />} end="12">
            Recipes
          </NavItem>
        </div>
      </Group>

      {dialog === "form" && (
        <Dialog
          onClose={() => setDialog(null)}
          title="New task"
          description="It starts a conversation on its own and leaves the answer waiting."
          footer={
            <>
              <Button onClick={() => setDialog(null)}>Cancel</Button>
              <Button variant="primary" onClick={() => setDialog(null)}>
                Create task
              </Button>
            </>
          }
        >
          <FormField label="Name">{(ties) => <TextInput {...ties} defaultValue="Morning briefing" />}</FormField>
          <FormField label="What to do">{(ties) => <TextArea {...ties} defaultValue="Summarise today's calendar and the weather in three lines." />}</FormField>
        </Dialog>
      )}
      {dialog === "ask" && (
        <Dialog
          asks
          size="sm"
          onClose={() => setDialog(null)}
          title="Delete this conversation?"
          description="Its messages and its files are removed for good."
          leading={
            <Tile tone="danger">
              <Trash2 />
            </Tile>
          }
          footer={
            <>
              <Button onClick={() => setDialog(null)}>Cancel</Button>
              <Button variant="danger-solid" onClick={() => setDialog(null)}>
                Delete
              </Button>
            </>
          }
        />
      )}
    </main>
  );
}

const root = document.getElementById("root");
if (root === null) throw new Error("no #root element");
createRoot(root).render(
  <StrictMode>
    <Gallery />
  </StrictMode>,
);
