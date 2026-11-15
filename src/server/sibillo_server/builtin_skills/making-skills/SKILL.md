---
name: making-skills
description: Use when the user asks to make, change or save a skill, or to turn work you just did into one they can reuse in other conversations.
---

# Making skills

A skill is a folder with a `SKILL.md` file and any files it needs, in the open Agent Skills format.
Every conversation of the user sees each skill's name and description, and loads the rest only
when it is useful, so a skill can be long without costing anything until it is used.

## Write it

1. Agree with the user on what the skill is for and when it should be used.
2. Make a folder in your scratch folder named after the skill: lowercase letters, digits and single
   hyphens, at most 64 characters, such as `/scratch/monthly-budget`.
3. Write `SKILL.md`:

   ```markdown
   ---
   name: monthly-budget
   description: Use when the user asks to update or explain the household's monthly budget from bank exports.
   ---

   # Monthly budget

   Steps, in the imperative, with the commands or code that do each one.
   ```

   The description says when to use the skill, in at most 1,024 characters: it is all a
   conversation sees until it loads the skill. The body says how, as briefly as it can.
4. Put scripts in `scripts/` and longer references in `references/`, and point to them from
   `SKILL.md` with paths relative to the skill's folder. Make scripts executable. Keep data
   the skill can fetch again out of it; a skill holds at most 200 files and 10 MiB.
5. Try the skill on a real example before saving it.

## Save it

Call `save_skill` with the folder's path. The user approves it first, and then it is on in their
later conversations; a skill of theirs with the same name is replaced. The name of a built-in
skill cannot be used.

## Change one

The files of every skill that is on are in `/skills/<name>/`, read-only. Copy the folder to your
scratch folder, change it there, and save it again with `save_skill`.

Never put passwords, keys or other secrets in a skill.
