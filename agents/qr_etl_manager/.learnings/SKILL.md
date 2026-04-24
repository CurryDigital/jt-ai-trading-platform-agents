# SKILL.md — self-improving

A lightweight learning capture system for agents. Records errors, learnings, and feature requests in markdown logs, then periodically promotes patterns to permanent documentation.

## When to Use

Use this skill when:
- Something went wrong (log to ERRORS.md)
- User corrected you or you discovered a better way (log to LEARNINGS.md)
- User asks for a new capability (log to FEATURE_REQUESTS.md)
- You notice a recurring pattern that should become permanent

## How It Works

### 1. Capture Phase (Immediate)
When something notable happens, append to the appropriate log file:

```markdown
[2026-04-16 01:20 UTC] API Timeout: FMP ingestion failed on connection timeout
- **Context**: Running bronze/fmp/ingest_fmp.py during daily refresh
- **Root Cause**: FMP API rate limit exceeded (503 response)
- **Resolution**: Added 30s retry with exponential backoff
- **Prevention**: Check rate limits before batch calls; implement circuit breaker
```

### 2. Promotion Phase (Periodic)
Every 5-10 entries or when explicitly asked, review logs and promote patterns to:
- **AGENTS.md** — Workflow changes, boot sequence updates
- **TOOLS.md** — New tool patterns, API quirks, SQL patterns
- **SOUL.md** — Personality adjustments, tone refinements
- **MEMORY.md** — Persistent facts about the user/project

Clear promoted entries or mark with `✓ PROMOTED`.

## File Structure

```
.learnings/
├── ERRORS.md          # Failures, exceptions, what went wrong
├── LEARNINGS.md       # Corrections, discovered patterns, best practices
├── FEATURE_REQUESTS.md # User requests, enhancement ideas
└── SKILL.md           # This file — how the system works
```

## Log Templates

### Error Entry
```markdown
[YYYY-MM-DD HH:MM UTC] <Error Type>: <Brief description>
- **Context**: What was happening
- **Root Cause**: Why it happened
- **Resolution**: How fixed
- **Prevention**: How to avoid
```

### Learning Entry
```markdown
[YYYY-MM-DD HH:MM UTC] <Category>: <Title>
- **Discovery**: What was learned
- **Source**: User correction, failure, docs
- **Impact**: How this changes behavior
- **Promote To**: AGENTS.md | TOOLS.md | SOUL.md | MEMORY.md
```

### Feature Request Entry
```markdown
[YYYY-MM-DD HH:MM UTC] <Priority>: <Title>
- **Request**: What the user wants
- **Rationale**: Why they want it
- **Implementation**: Rough approach
- **Status**: pending | in-progress | completed | declined
```

## Promotion Triggers

Promote a pattern when:
- [ ] Same error occurs 2+ times
- [ ] User repeats the same correction/guidance
- [ ] A learning changes how you fundamentally operate
- [ ] Feature request is completed (move to completed section)
- [ ] 5+ entries accumulated (time to clean house)

## Quick Commands

Check current log status:
```bash
cat .learnings/ERRORS.md
cat .learnings/LEARNINGS.md
cat .learnings/FEATURE_REQUESTS.md
```

Count entries:
```bash
grep -c "^\[" .learnings/ERRORS.md
grep -c "^\[" .learnings/LEARNINGS.md
```

## Agent Instructions

When something goes wrong:
1. Fix the immediate issue
2. Log to ERRORS.md with full context
3. If pattern emerges, add prevention note to TOOLS.md

When user corrects you:
1. Thank them
2. Log to LEARNINGS.md immediately
3. Apply the correction going forward
4. Promote to SOUL.md if it changes your personality/approach

When user requests a feature:
1. Log to FEATURE_REQUESTS.md with their exact words
2. Ask clarifying questions if needed
3. When done, update status and move to Completed

## Self-Review Checklist

Before ending a session with persistent work:
- [ ] Any errors to log?
- [ ] Any user corrections to capture?
- [ ] Any features completed to mark?
- [ ] Patterns ready for promotion?
