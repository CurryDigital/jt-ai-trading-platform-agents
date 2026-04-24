# MEMORY.md — qr_etl_manager

_Starts empty. Updated by the agent as it discovers persistent patterns._

---

## Self-Improving System

A learning capture system is active in `.learnings/`:

- **ERRORS.md** — Log command failures, exceptions, tool errors
- **LEARNINGS.md** — Log corrections, discovered patterns, best practices  
- **FEATURE_REQUESTS.md** — Log user-requested capabilities

### When to Log

| Situation | Log To | Action After |
|-----------|--------|--------------|
| Command fails | ERRORS.md | If repeats, add prevention to TOOLS.md |
| User corrects me | LEARNINGS.md | Apply correction; promote to SOUL.md if changes personality |
| User wants feature | FEATURE_REQUESTS.md | Ask questions, implement, mark complete |
| Same issue 2+ times | — | Promote pattern to AGENTS.md/TOOLS.md |

See `.learnings/SKILL.md` for full documentation and templates.

---

## Silent Replies
When you have nothing to say, respond with ONLY: NO_REPLY
⚠️ Rules:
- It must be your ENTIRE message — nothing else
- Never append it to an actual response (never include "NO_REPLY" in real replies)
- Never wrap it in markdown or code blocks
❌ Wrong: "Here's help... NO_REPLY"
❌ Wrong: "NO_REPLY"
✅ Right: NO_REPLY

<!-- OPENCLAW_CACHE_BOUNDARY -->
