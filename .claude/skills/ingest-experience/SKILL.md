---
name: ingest-experience
description: >
  Turn a free-form experience or note ("I was just at a cool bar / playground /
  read a great book …", "ich war gerade …") into a schema-conforming item in one
  of this repo's collections, then publish it to the live GitHub Pages site. Use
  when the user describes something they want to log, add, or update in a
  collection. Structures + beautifies with Claude, validates in code, previews for
  confirmation, then commits and pushes.
---

# Ingest an experience into a collection

You are the ingestion agent. The user describes an experience in natural language
(often from the Claude mobile app). You turn it into a valid item and publish it.
The site is **public**, so treat publishing as a deliberate, confirmed action.

## Workflow

1. **Pick the collection.** Infer it from what the user describes; if ambiguous,
   list options and ask. Discover collections with:
   `uv run collections list`  (defaults to `examples/collections`).

2. **Read the schema — it is the single source of truth for fields.**
   Read `examples/collections/<collection>/schema.json`. Only use fields the
   schema declares.

3. **Structure + beautify the item.**
   - Map the user's words onto schema fields. **Fill only information that was
     given or is safely known — never invent facts** (don't guess an author, a
     year, an address). If unsure, leave the field out.
   - Beautify free-text fields (e.g. a `description`) into a short, pleasant
     **plain-text** blurb. No HTML and no Markdown control characters — the value
     is rendered as text on the site; injected markup must not be possible.
   - Fill date/time fields if the schema has them (use today's date for a
     "just now" experience). If the schema has a location field, keep it **coarse**
     (place or city, not precise GPS) unless the user explicitly wants precision.
   - Choose a readable id/slug (e.g. from a name/title). To **update** an existing
     item, reuse its id.

4. **Preview + confirm (required).** Show the user the structured item (or, for an
   update, the changed fields). Add a one-line **privacy reminder** that this goes
   to the public site. Wait for explicit confirmation. If they mention anything
   sensitive (home address, real-time exact location, anything private), call it
   out before proceeding.

5. **Validate + write (deterministic gate).** Run:
   ```
   uv run collections ingest <collection> --data '<json>' --id <slug> --yes
   ```
   This validates against the schema and writes the file (create or update). If it
   exits with a schema error, fix the item and retry — do not work around the
   validation.

6. **Publish.** `git add` the item file, commit with a short message, and push to
   **main** (the deployed branch). The Pages workflow rebuilds the site; give the
   user the live URL (`https://onefloid.github.io/balyoo/`) and note it may take
   ~a minute.

## Safety rules

- Never publish secrets, credentials, tokens, or another person's private data.
- Never write an item that fails schema validation.
- Prefer omitting a field over hallucinating its value.
- Keep free-text plain; the UI renders values as text — don't rely on markup.
- Publishing is public and (near-)permanent — always confirm first.
