// The user's skills and the built-in ones (AGT-017, AGT-024 to AGT-026, UX-028, ADR-0096).
import { useQuery } from "@tanstack/react-query";

import { API_BASE, ApiError, REQUEST_HEADER, api, unwrap, type Problem, type Schemas } from "./api/client";

export type Skill = Schemas["Skill"];
export type SkillDetail = Schemas["SkillDetail"];

export const SKILLS = ["me", "skills"] as const;
// The settings section that shows them, as a link names it.
export const SKILLS_SECTION = "/settings?section=skills";

export function useSkills() {
  return useQuery({ queryKey: SKILLS, queryFn: async () => unwrap(await api.GET("/me/skills")) });
}

/** The skills on for the user, which a conversation can turn off: built-in first, by name. */
export function skillsOn(skills: Schemas["Skills"] | undefined): Skill[] {
  return [...(skills?.builtin ?? []), ...(skills?.own ?? [])].filter((skill) => skill.enabled);
}

export async function skillDetail(skill: Skill): Promise<SkillDetail> {
  return skill.id === null
    ? unwrap(await api.GET("/me/skills/builtin/{skill_name}", { params: { path: { skill_name: skill.name } } }))
    : unwrap(await api.GET("/me/skills/{skill_id}", { params: { path: { skill_id: skill.id } } }));
}

/** A skill from an archive the user chose; untrusted, as someone else may have written it (AGT-025). */
export async function uploadSkill(file: File): Promise<SkillDetail> {
  const form = new FormData();
  form.append("archive", file, file.name);
  const response = await fetch(`${API_BASE}/me/skills`, { method: "POST", body: form, headers: REQUEST_HEADER, credentials: "same-origin" });
  if (!response.ok) {
    const problem = (await response.json().catch(() => ({}))) as Partial<Problem>;
    throw new ApiError(response.status, problem.code ?? "internal.error", problem);
  }
  return (await response.json()) as SkillDetail;
}

/** Where a skill's file is downloaded from. */
export function fileAddress(skill: Skill, path: string): string {
  const query = `path=${encodeURIComponent(path)}`;
  return skill.id === null ? `${API_BASE}/me/skills/builtin/${encodeURIComponent(skill.name)}/file?${query}` : `${API_BASE}/me/skills/${skill.id}/file?${query}`;
}

/** A call that loaded a skill, by the skill it named; null for any other call, or one refused (UX-028). */
export function loadedSkillOf(name: string, args: Record<string, unknown>, result: string | undefined): string | null {
  if (name !== "load_capability" || result === undefined || typeof args.id !== "string") return null;
  // Only a load that happened: a repeated call is refused, and says so.
  return result.includes(`'${args.id}' loaded.`) ? args.id : null;
}

/** A call that saved a skill, by its name; null for any other call, or one that failed (AGT-026). */
export function savedSkillOf(name: string, result: string | undefined): string | null {
  if (name !== "save_skill" || result === undefined) return null;
  const saved = /^(?:Saved|Replaced) the skill '([^']+)'/.exec(result);
  return saved?.[1] ?? null;
}
