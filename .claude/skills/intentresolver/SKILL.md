---
name: intentresolver
description: >
  Implements the Intent Resolver component of the voice-guided UI click pipeline.
  Use this skill when building or modifying the intent resolver, which takes a
  voice transcript and lightweight screen context and produces a concrete,
  grounded understanding of what the user wants to do. The resolver must decide
  on its own whether a web search is needed to interpret the user's command.
---

# Intent Resolver

The Intent Resolver is the first component in a voice-guided UI automation
pipeline. Its sole job is **disambiguation and grounding**: turn a raw voice
transcript into a concrete, detailed natural-language statement of what the user
actually wants to accomplish, given lightweight context about what is currently
on screen.

It does not pick a button. It does not produce structured click targets. It
produces text — specifically the clearest possible understanding of the user's
intent — which the downstream Button Picker uses to match against a labeled map
of UI elements.

---

## Input schema

```ts
type IntentResolverInput = {
  transcript: string         // raw speech-to-text output
  context: {
    app_name: string         // always available via OS APIs
    window_title: string     // always available via OS APIs
    url?: string             // only if browser, via extension or accessibility tree
    active_element?: string  // only if app exposes accessibility tree
  }
}
```

**Context availability notes:**
- `app_name` and `window_title` are always populated. Build your primary
  reasoning around these.
- `url` and `active_element` are best-effort. Many apps — games, Electron apps,
  some native apps — expose neither. The resolver must handle their absence
  gracefully and never assume they will be present.
- The orchestrator is responsible for populating context before invoking the
  resolver. The resolver only receives what it is given.

---

## Output schema

```ts
type ResolvedIntent = {
  understanding: string       // concrete, detailed natural language
  search_results?: SearchResult[]
}

type SearchResult = {
  title: string
  snippet: string
  url: string
}
```

**`understanding` requirements:**
- Always present. Never empty.
- Concrete and specific. "The user wants to increase the render distance in
  Minecraft via the video settings menu" is correct. "The user wants to click
  something related to graphics" is not.
- Written as a complete sentence describing the user's goal in terms of the
  actual application and action, not in terms of UI elements (that is Button
  Picker's job).
- If the transcript is unambiguously clear given the context, state the
  understanding plainly. Do not over-explain.

**`search_results` requirements:**
- Optional. Only populate when domain knowledge was required to interpret the
  command and a web search was performed.
- Include 1–3 results. Prefer official documentation, wikis, or support pages
  over forums.
- Do not populate with generic results. If the search did not meaningfully help
  ground the intent, omit the field.

---

## Decision: when to search

The resolver itself decides whether a web search is needed. The orchestrator
does not control this. The rule is:

**Search when** the transcript references a concept, setting, feature, or
error that requires external knowledge to interpret — i.e., when the model
cannot confidently produce a concrete `understanding` from the transcript and
context alone.

**Do not search when** the command is self-evident given the context. "Click
submit", "open settings", "go back", "close this window" require no search.

Examples that require search:
- "Why can't I see far away?" in Minecraft → needs to know about render distance
- "Turn on vsync" in a game → needs to know where vsync lives in that game's settings
- "Fix the CORS error" in a browser dev console → may need to know what CORS is
  and what the typical fix involves

Examples that do not require search:
- "Click the blue button at the bottom" — spatial, no domain knowledge needed
- "Submit the form" — universal UI concept
- "Open the file menu" — universal UI concept

---

## Behavior requirements

1. **Resolve deictic references** using context. "That thing", "the blue one",
   "the button on the right" should be resolved as specifically as possible
   given `app_name`, `window_title`, and any available `url` or `active_element`.
   If they cannot be resolved, say so explicitly in `understanding` (e.g.,
   "The user is pointing to a specific UI element that cannot be identified
   without visual context").

2. **Use context to narrow domain.** "Open settings" means different things in
   Minecraft vs. macOS System Settings vs. a browser. Always qualify the
   understanding with the application context.

3. **Do not hallucinate UI structure.** If the resolver doesn't know where a
   setting lives in a specific app, say the goal in terms of the user's intent,
   not a fabricated navigation path. Button Picker will handle locating the
   element.

4. **Be terse but complete.** The `understanding` field is consumed by another
   model component downstream. One or two sentences is usually right. Do not
   add caveats, alternatives, or hedging unless the intent is genuinely
   ambiguous, in which case surface the ambiguity plainly.

---

## Examples

**Input:**
```json
{
  "transcript": "why can't I see far away",
  "context": {
    "app_name": "Minecraft",
    "window_title": "Minecraft 1.21.1"
  }
}
```
**Output:**
```json
{
  "understanding": "The user wants to increase their render distance in Minecraft, which is controlled in Settings → Video Settings → Render Distance.",
  "search_results": [
    {
      "title": "Render Distance – Minecraft Wiki",
      "snippet": "Render distance controls the number of chunks visible in each direction. It can be adjusted in Video Settings under Options.",
      "url": "https://minecraft.wiki/w/Options#Video_settings"
    }
  ]
}
```

---

**Input:**
```json
{
  "transcript": "submit the form",
  "context": {
    "app_name": "Google Chrome",
    "window_title": "Checkout – Acme Store",
    "url": "https://acme.com/checkout"
  }
}
```
**Output:**
```json
{
  "understanding": "The user wants to submit the checkout form on the Acme Store checkout page."
}
```

---

**Input:**
```json
{
  "transcript": "turn off the thing that makes it slow",
  "context": {
    "app_name": "Adobe Premiere Pro",
    "window_title": "Adobe Premiere Pro 2025"
  }
}
```
**Output:**
```json
{
  "understanding": "The user's intent is ambiguous — 'the thing that makes it slow' cannot be resolved without knowing which performance issue they are experiencing. Possible candidates include hardware acceleration, background rendering, or auto-save frequency.",
  "search_results": [
    {
      "title": "Improve performance in Premiere Pro – Adobe Support",
      "snippet": "Common causes of slowness include GPU rendering issues, high-resolution previews, and conflicting background processes. Disabling GPU acceleration or adjusting playback resolution can help.",
      "url": "https://helpx.adobe.com/premiere-pro/using/improve-performance.html"
    }
  ]
}
```

---

## Position in pipeline

```
[Voice Input] → [Intent Resolver] → understanding: string → [Button Picker]
                                    search_results?: SearchResult[]
```

The orchestrator calls Intent Resolver and Button Labeler concurrently. Button
Picker is invoked only after both have resolved. Intent Resolver's output is
passed directly to Button Picker as the query for matching against the labeled
button map. The `search_results` field is not consumed by Button Picker — it is
retained in the orchestrator's run context for logging and debugging.