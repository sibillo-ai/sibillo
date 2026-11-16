// Remote MCP servers: the household's, for its admins, and as each user sees them (UX-029, ADR-0099, ADR-0100).
import { useQuery } from "@tanstack/react-query";

import { api, unwrap, type Schemas } from "./api/client";

export type McpServer = Schemas["McpServer"];
export type McpServerTool = Schemas["McpServerTool"];
export type McpServerSummary = Schemas["McpServerSummary"];
export type McpServerAuth = Schemas["McpServerAuth"];

export const MCP_SERVERS = ["mcp-servers"] as const;
export const HOUSEHOLD_MCP_SERVERS = ["tenant", "mcp-servers"] as const;
// Separates a server's prefix from its tool's name; no tool of Sibillo has it (ADR-0099).
const SEPARATOR = "__";

/** The household's servers that are on, as the user sees them: their tools, and the user's own credential. */
export function useMcpServers() {
  return useQuery({ queryKey: MCP_SERVERS, queryFn: async () => unwrap(await api.GET("/mcp-servers")).items });
}

/** Every server of the household, with every tool it lists, for its admins. */
export function useHouseholdMcpServers() {
  return useQuery({ queryKey: HOUSEHOLD_MCP_SERVERS, queryFn: async () => unwrap(await api.GET("/tenant/mcp-servers")).items });
}

/** A server's tool, by the name the model calls it by: its title and its server's name, or `null` for another tool. */
export function useServerTool(name: string): { title: string; server: string } | null {
  const servers = useMcpServers();
  if (!name.includes(SEPARATOR)) return null;
  for (const server of servers.data ?? []) {
    if (!name.startsWith(`${server.prefix}${SEPARATOR}`)) continue;
    const tool = server.tools.find((item) => item.model_name === name);
    return { title: tool?.title ?? name.slice(server.prefix.length + SEPARATOR.length), server: server.name };
  }
  return null;
}
