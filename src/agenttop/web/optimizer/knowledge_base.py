# ruff: noqa: E501
"""Knowledge base: per-tool best practices sourced from official docs.

The LLM uses this to identify features the user isn't leveraging.
Sourced from official docs (March 2026) for each tool.
"""

from __future__ import annotations

KNOWLEDGE_BASE: dict = {
    "claude_code": {
        "display_name": "Claude Code",
        "features": [
            {
                "name": "CLAUDE.md project memory",
                "description": "Place CLAUDE.md at project root with coding style, build commands, architecture notes. Loaded every session. Use @path/to/file to import inline. Keep under 500 lines. Use CLAUDE.local.md for personal gitignored overrides.",
                "impact": "Saves ~500 tokens/session of repeated context. Improves code consistency.",
                "detection_hint": "Check if projects have CLAUDE.md files",
                "setup_guide": "1. Create CLAUDE.md at project root\n2. Add sections: ## Build Commands, ## Architecture, ## Code Style\n3. Keep under 500 lines — agent ignores overlong files\n4. For personal overrides, create CLAUDE.local.md (gitignored)\n5. Import shared configs: @path/to/shared-rules.md",
                "prompt_tips": "GOOD: 'Refactor auth module following the patterns in CLAUDE.md'\nBAD: 'Fix the code' (no context, agent wastes tokens rediscovering project conventions)\nTIP: Reference CLAUDE.md sections explicitly so the agent knows which rules apply",
            },
            {
                "name": "Sub-agents for parallel research",
                "description": "Define in .claude/agents/*.md with name, tools, model. Spawn explore agents for codebase search, plan agents for architecture. Each runs in separate context — doesn't bloat main conversation.",
                "impact": "Reduces main context pollution. Enables parallel investigation.",
                "detection_hint": "High tool_call_count relative to messages suggests manual exploration that could be delegated",
                "setup_guide": "1. Create .claude/agents/ directory\n2. Add agent files like explore.md, plan.md, review.md\n3. Each file needs --- frontmatter with: name, description, tools list\n4. Spawn with: 'Use the explore agent to find all auth-related files'\n5. Agents run in separate context — main conversation stays clean",
                "prompt_tips": "GOOD: 'Use the explore agent to find where rate limiting is implemented'\nBAD: 'Find all files related to rate limiting' (runs in main context, pollutes it)\nTIP: Delegate research to subagents, use main context only for decisions and implementation",
            },
            {
                "name": "Model selection strategy",
                "description": "Use /model to switch mid-session. Opus for complex architecture, Sonnet for general coding (default), Haiku for simple subagent tasks. Extended thinking on by default (31,999 tokens). Reduce with MAX_THINKING_TOKENS=8000 for simpler tasks.",
                "impact": "Sonnet is 5x cheaper than Opus with similar quality for most tasks.",
                "detection_hint": "Check model_usage for diversity",
                "setup_guide": "1. Default model is Sonnet (best cost/quality for coding)\n2. Switch mid-session: /model claude-opus-4-6 (for architecture decisions)\n3. For subagents, specify model in agent .md frontmatter\n4. Reduce thinking budget: export MAX_THINKING_TOKENS=8000\n5. Check current model: look at status bar or run /model",
                "prompt_tips": "GOOD: Switch to Opus BEFORE asking complex architecture questions\nBAD: Using Opus for simple file edits or formatting\nTIP: Sonnet handles 90% of coding tasks. Save Opus for system design, complex refactoring, multi-file architecture",
            },
            {
                "name": "Prompt caching optimization",
                "description": "System prompt + CLAUDE.md + tool definitions are automatically cached. Cache reads cost 90% less. Avoid cache breakers: adding MCP tools mid-session, switching models. Use /context to check context usage.",
                "impact": "Up to 80% savings on input tokens.",
                "detection_hint": "Check cacheReadInputTokens ratio",
                "setup_guide": "1. Prompt caching is automatic — no setup needed\n2. Check cache stats: /context shows cache hit rates\n3. Avoid cache breakers: don't add/remove MCP servers mid-session\n4. Don't switch models frequently — each switch invalidates cache\n5. For heavy MCP users: ENABLE_TOOL_SEARCH=auto:5 defers loading",
                "prompt_tips": "GOOD: Keep sessions focused on one task (cache stays warm)\nBAD: Switching between unrelated tasks without /clear (cache thrashes)\nTIP: Cache reads cost 90% less than cache writes. Stable sessions = massive savings",
            },
            {
                "name": "Session hygiene with /clear and /compact",
                "description": "/clear between unrelated tasks (single most important habit). /compact <focus> for manual compaction: '/compact Focus on API changes'. Double-tap Esc for checkpoint restoration. --continue to resume last session.",
                "impact": "Prevents context pollution. Reduces token waste from stale context.",
                "detection_hint": "Long sessions (>50 messages) suggest lack of /clear usage",
                "setup_guide": "1. Use /clear between unrelated tasks (most impactful habit)\n2. Use /compact <focus> to summarize context: '/compact Focus on API changes'\n3. Double-tap Esc to restore from checkpoint\n4. Use --continue to resume your last session\n5. Watch for sessions >50 messages — time to /clear or /compact",
                "prompt_tips": "GOOD: '/clear' then 'Now let's work on the payment module'\nBAD: 'Also while you're at it, fix the auth bug too' (kitchen sink session)\nTIP: One task per session. If you catch yourself saying 'also', it's time for /clear",
            },
            {
                "name": "Skills and slash commands",
                "description": "Create .claude/commands/*.md for repetitive workflows. Define with --- frontmatter (name, description, tools). Invoke with /skill-name. Unlike CLAUDE.md, skills load on-demand only when relevant.",
                "impact": "Reduces CLAUDE.md bloat. Reusable workflows.",
                "detection_hint": "Repetitive prompt patterns suggest skill candidates",
                "setup_guide": "1. Create .claude/commands/ directory\n2. Add .md files with --- frontmatter (name, description)\n3. Example: review.md with 'Review this PR for security issues'\n4. Invoke with /review in any session\n5. Skills load on-demand — don't bloat every session like CLAUDE.md",
                "prompt_tips": "GOOD: Create a /deploy skill for your deployment checklist\nBAD: Putting deployment steps in CLAUDE.md (loads every session)\nTIP: If you type the same instructions 3+ times, it should be a skill",
            },
            {
                "name": "Hooks for automation",
                "description": "Configure in .claude/settings.json. Types: command, http, prompt (Haiku yes/no), agent (multi-turn). Events: PostToolUse, PreToolUse, SessionStart, etc. Example: auto-format on Edit/Write. Exit code 2 blocks action with feedback.",
                "impact": "Deterministic tasks (lint, format, test) handled without AI tokens.",
                "detection_hint": "Tool calls for formatting/linting suggest hook candidates",
                "setup_guide": "1. Edit .claude/settings.json, add 'hooks' section\n2. Event types: PreToolUse, PostToolUse, SessionStart, Stop\n3. Hook types: command (run shell), http, prompt (Haiku y/n)\n4. Example: auto-format on file write: {event: 'PostToolUse', tools: ['Write','Edit'], command: 'prettier --write $FILE'}\n5. Exit code 2 from hook blocks the action with feedback",
                "prompt_tips": "GOOD: Use hooks for lint/format/test — deterministic, no AI needed\nBAD: Asking Claude to 'run prettier on every file you edit'\nTIP: Every hook saves AI tokens. If a task is deterministic, hook it",
            },
            {
                "name": "MCP server management",
                "description": "Each MCP server adds tool definitions consuming context even when idle. Use /context to check. Prefer CLI tools (gh, aws) over MCP when possible. ENABLE_TOOL_SEARCH=auto:5 defers loading until needed.",
                "impact": "Reduces baseline context size. Cheaper per message.",
                "detection_hint": "High input tokens relative to output may indicate context bloat",
                "setup_guide": "1. Check loaded MCP servers: /context\n2. Remove unused servers from .claude/settings.json\n3. Prefer CLI tools (gh, aws, docker) over MCP equivalents\n4. Set ENABLE_TOOL_SEARCH=auto:5 to defer MCP loading\n5. Each idle MCP server costs ~500-2000 tokens per message",
                "prompt_tips": "GOOD: Use 'gh pr create' instead of MCP GitHub server\nBAD: Loading 10 MCP servers when you only use 2\nTIP: Audit your MCP servers monthly. Remove what you don't use",
            },
        ],
        "anti_patterns": [
            "Kitchen sink sessions: mixing unrelated tasks without /clear",
            "Correction spirals: correcting 3+ times instead of /clear + better prompt",
            "Over-specified CLAUDE.md (>500 lines): agent ignores critical rules",
            "Not using subagents for exploration (manual file-by-file investigation)",
            "Running all tasks on Opus when Sonnet handles them fine",
        ],
        "cost_benchmarks": {
            "typical_daily": "$6/dev/day",
            "90th_percentile": "$12/dev/day",
            "monthly_sonnet": "$100-200/dev/month",
        },
    },
    "cursor": {
        "display_name": "Cursor",
        "features": [
            {
                "name": ".cursor/rules/*.mdc files (replaces .cursorrules)",
                "description": "Modular rules in .cursor/rules/ with YAML frontmatter. Types: alwaysApply (every chat), fileMatch (glob-triggered), auto (agent decides from description), manual (@rule-name). Keep each under 500 lines. Use @file-reference for patterns.",
                "impact": "Scoped rules = less context waste. Modular = easier maintenance.",
                "detection_hint": "Check if user has .cursorrules (legacy) vs .cursor/rules/ (current)",
                "setup_guide": "1. Create .cursor/rules/ directory in your project\n2. Add .mdc files with YAML frontmatter\n3. Types: alwaysApply, fileMatch (glob), auto, manual\n4. Example: api-rules.mdc with 'fileMatch: src/api/**/*.ts'\n5. Migrate from .cursorrules: split into modular .mdc files",
                "prompt_tips": "GOOD: 'Follow the API patterns from our cursor rules'\nBAD: 'Use REST best practices' (generic, agent has no project context)\nTIP: Write rules for YOUR project's patterns, not generic best practices",
            },
            {
                "name": "Four modes: Agent, Ask, Plan, Debug",
                "description": "Agent (Cmd+.): autonomous multi-file. Ask: read-only exploration. Plan: creates detailed plan before execution. Debug: hypothesis generation + log instrumentation.",
                "impact": "Plan mode prevents expensive rework. Ask mode is cheaper for exploration.",
                "detection_hint": "If user's sessions show exploration patterns, they may not be using Ask/Plan modes",
                "setup_guide": "1. Agent mode (Cmd+.): autonomous multi-file changes\n2. Ask mode: read-only, cheaper, great for exploration\n3. Plan mode: generates plan before executing — use for complex tasks\n4. Debug mode: hypothesis-driven debugging with log instrumentation\n5. Switch modes from the dropdown in the chat input",
                "prompt_tips": "GOOD: Use Plan mode for 'Refactor the auth system to use OAuth'\nBAD: Using Agent mode for 'What does this function do?' (Ask mode is cheaper)\nTIP: Plan first, then Agent. Never Agent directly for complex multi-file changes",
            },
            {
                "name": "Background / Cloud agents",
                "description": "Run tasks asynchronously in isolated environments at cursor.com/agent. Best for documentation, large refactors, test writing.",
                "impact": "Parallel task execution without blocking main workflow.",
                "detection_hint": "Long-running sessions may benefit from background delegation",
                "setup_guide": "1. Go to cursor.com/agent\n2. Connect your GitHub repo\n3. Assign tasks like 'Write tests for the payment module'\n4. Agent runs in isolated environment, creates PR when done\n5. Best for: docs, large refactors, test generation",
                "prompt_tips": "GOOD: 'Write comprehensive tests for src/services/' (clear scope)\nBAD: 'Improve the codebase' (too vague for background agent)\nTIP: Background agents work best with clear, scoped tasks that don't need interactive feedback",
            },
            {
                "name": "@-mentions for targeted context",
                "description": "@file, @folder, @codebase (semantic search), @web, @docs, @git. Use @codebase to leverage indexed codebase instead of manual file hunting.",
                "impact": "Precise context = better responses. Avoids loading irrelevant files.",
                "detection_hint": "General",
                "setup_guide": "1. @file — include specific file as context\n2. @folder — include directory contents\n3. @codebase — semantic search across indexed codebase\n4. @web — search the web for documentation\n5. @docs — reference Cursor's built-in docs\n6. @git — reference git history and diffs",
                "prompt_tips": "GOOD: '@codebase how is authentication implemented here?'\nBAD: 'How is auth implemented?' (agent searches blindly)\nTIP: @codebase is your best friend. Use it instead of manually hunting files",
            },
            {
                "name": "Notepads for reusable context",
                "description": "Store coding standards, API patterns, review checklists as reusable snippets. Team-shareable for consistency.",
                "impact": "Eliminates repeated instructions across conversations.",
                "detection_hint": "Repetitive prompts across sessions suggest notepad candidates",
                "setup_guide": "1. Open Command Palette > 'Create Notepad'\n2. Write reusable context: coding standards, API patterns, review checklists\n3. Reference in chat: @notepad-name\n4. Share with team via .cursor/notepads/ directory\n5. Unlike rules, notepads are opt-in per conversation",
                "prompt_tips": "GOOD: Create a 'code-review' notepad with your team's checklist\nBAD: Pasting the same review checklist in every conversation\nTIP: If you copy-paste the same instructions across sessions, make it a notepad",
            },
        ],
        "anti_patterns": [
            "Single monolithic .cursorrules instead of modular .mdc files",
            "Not scoping rules with globs — everything loads into every context",
            "Not using Plan mode before complex multi-file Agent changes",
            "Ignoring Notepads — repeating same instructions across conversations",
            "Using Agent mode for exploration (Ask mode is cheaper/safer)",
        ],
    },
    "copilot": {
        "display_name": "GitHub Copilot",
        "features": [
            {
                "name": "Copilot Coding Agent (assign to issues)",
                "description": "Assign @copilot to GitHub Issues — creates PR autonomously. Self-reviews with Code Review. Runs security scans. Pushes to copilot/ branches only.",
                "impact": "Automate routine PRs. Free up developer time for complex work.",
                "detection_hint": "General",
                "setup_guide": "1. Enable Copilot in repo settings > Features > Copilot\n2. Create a well-structured GitHub Issue with acceptance criteria\n3. Assign @copilot to the issue\n4. Copilot creates a PR on copilot/ branch\n5. Review the PR — Copilot self-reviews with Code Review",
                "prompt_tips": "GOOD: Issue: 'Add rate limiting to POST /api/users — max 10 req/min per IP, return 429'\nBAD: Issue: 'Fix the API' (too vague, agent won't know what to do)\nTIP: Write issues like you're briefing a junior dev — specific acceptance criteria",
            },
            {
                "name": "copilot-setup-steps.yml",
                "description": "Pre-install dependencies in .github/workflows/copilot-setup-steps.yml so agent can build/test immediately instead of discovering by trial-and-error.",
                "impact": "Reduces wasted Actions minutes. Faster agent execution.",
                "detection_hint": "General",
                "setup_guide": "1. Create .github/workflows/copilot-setup-steps.yml\n2. Add steps to install dependencies: npm ci, pip install, etc.\n3. Include build steps so agent can verify changes compile\n4. Add test commands so agent can run tests\n5. This runs BEFORE Copilot starts working — saves Actions minutes",
                "prompt_tips": "N/A (configuration file, not prompt-driven)",
            },
            {
                "name": "Custom instructions (.github/copilot-instructions.md)",
                "description": "Repository-level + path-specific instructions (.github/instructions/*.instructions.md with applyTo globs). Custom agents in .github/agents/*.md.",
                "impact": "Agent has project context. Better code quality.",
                "detection_hint": "General",
                "setup_guide": "1. Create .github/copilot-instructions.md for repo-wide instructions\n2. For path-specific rules: .github/instructions/*.instructions.md with applyTo globs\n3. For custom agents: .github/agents/*.md with specialized behaviors\n4. Keep instructions concise — Copilot has limited context\n5. Include: tech stack, coding style, testing requirements",
                "prompt_tips": "GOOD: Reference your custom agents: '@agent-name review this PR'\nBAD: Explaining your entire codebase in every chat\nTIP: Instructions are your project's memory. Keep them updated",
            },
        ],
        "anti_patterns": [
            "Vague issues without acceptance criteria for coding agent",
            "Not setting up copilot-setup-steps.yml — agent wastes time",
            "Missing custom instructions — Copilot has no project context",
        ],
    },
    "kiro": {
        "display_name": "Kiro",
        "features": [
            {
                "name": "Specs-driven development",
                "description": "Three-part specs in .kiro/specs/<feature>/: requirements.md (EARS notation), design.md (data flow, interfaces), tasks.md (auto-generated). Describe feature -> Kiro generates all three -> review -> execute.",
                "impact": "Front-loads planning. Reduces rework iterations significantly.",
                "detection_hint": "General",
                "setup_guide": "1. Open Kiro and describe your feature in natural language\n2. Kiro generates .kiro/specs/<feature>/requirements.md (EARS notation)\n3. Review requirements, then Kiro generates design.md (interfaces, data flow)\n4. Kiro auto-generates tasks.md from the design\n5. Execute tasks one by one — Kiro tracks progress",
                "prompt_tips": "GOOD: 'Build a user notification system that supports email, SMS, and in-app'\nBAD: 'Add notifications' (too vague for spec generation)\nTIP: The more specific your initial description, the better the generated specs. Include constraints, scale, and edge cases",
            },
            {
                "name": "Steering files with inclusion modes",
                "description": "In .kiro/steering/: always (every interaction), fileMatch (glob-triggered), auto (agent decides from description), manual (#name invocation). Auto-generates product.md, tech.md, structure.md.",
                "impact": "Scoped context = less waste. fileMatch/auto avoid loading irrelevant steering.",
                "detection_hint": "General",
                "setup_guide": "1. Kiro auto-generates .kiro/steering/product.md, tech.md, structure.md\n2. Add custom steering files in .kiro/steering/\n3. Use inclusion modes: always, fileMatch (glob), auto (AI decides), manual (#name)\n4. Example: api-conventions.md with 'fileMatch: src/api/**'\n5. Keep each file focused — don't dump everything in 'always'",
                "prompt_tips": "GOOD: Reference steering: '#api-conventions for this endpoint'\nBAD: Putting all conventions in 'always' mode (loads every interaction)\nTIP: Use fileMatch for most rules. Only truly universal rules should be 'always'",
            },
            {
                "name": "Hooks for event-driven automation",
                "description": "Trigger on file save/create/commit. Auto-update tests, refresh README, security scan. Subagent support for parallel execution.",
                "impact": "Deterministic tasks without AI token consumption.",
                "detection_hint": "General",
                "setup_guide": "1. Configure hooks in .kiro/hooks/ directory\n2. Trigger events: file save, file create, git commit\n3. Example: auto-run tests on save, refresh README on commit\n4. Supports subagent execution for parallel tasks\n5. Hooks are deterministic — no AI tokens consumed",
                "prompt_tips": "GOOD: Hook that runs 'npm test' on every file save in src/\nBAD: Asking Kiro to 'run tests after every change'\nTIP: Hooks handle the routine. Let AI focus on the creative work",
            },
        ],
        "anti_patterns": [
            "Skipping specs — jumping to agentic chat loses structured planning benefit",
            "Monolithic steering — use fileMatch and auto instead of always for everything",
            "Ignoring spec drift — specs must stay in sync with code changes",
        ],
    },
    "codex": {
        "display_name": "OpenAI Codex",
        "features": [
            {
                "name": "Profiles for model/mode switching",
                "description": "Define profiles in ~/.codex/config.toml: [profiles.deep-review] with model, reasoning_effort, approval_policy. Switch with --profile. Use 'fast' profile for routine, 'deep-review' for complex.",
                "impact": "Right model for right task. Huge cost savings on routine work.",
                "detection_hint": "General",
                "setup_guide": "1. Edit ~/.codex/config.toml\n2. Add profile sections: [profiles.fast], [profiles.deep-review]\n3. Each profile sets: model, reasoning_effort, approval_policy\n4. Switch with: codex --profile fast\n5. Example: fast profile uses o4-mini, deep-review uses o3 with high reasoning",
                "prompt_tips": "GOOD: 'codex --profile deep-review' for architecture decisions\nBAD: Using the default profile for everything\nTIP: Create at least 2 profiles: fast (routine) and deep (complex). Switch based on task",
            },
            {
                "name": "AGENTS.md instruction hierarchy",
                "description": "Global (~/.codex/AGENTS.md) -> project root (./AGENTS.md) -> per-directory. AGENTS.override.md supersedes at same level. Max 32 KiB combined (configurable).",
                "impact": "Scoped instructions improve output quality.",
                "detection_hint": "General",
                "setup_guide": "1. Create AGENTS.md at project root for project-specific instructions\n2. Add ~/.codex/AGENTS.md for global instructions\n3. Per-directory: src/api/AGENTS.md for API-specific rules\n4. Use AGENTS.override.md to supersede at same level\n5. Total size limit: 32 KiB combined (configurable)",
                "prompt_tips": "GOOD: AGENTS.md with 'Always use parameterized queries for SQL'\nBAD: AGENTS.md with entire API documentation (too long, gets ignored)\nTIP: Think of AGENTS.md as a cheat sheet, not a manual. Key rules only",
            },
            {
                "name": "Sandbox configuration",
                "description": "Three modes: auto (default), read-only, full-access. Configure writable_roots, network_access in config.toml. shell_environment_policy to prevent secret leaks.",
                "impact": "Security without blocking legitimate operations.",
                "detection_hint": "General",
                "setup_guide": "1. Edit ~/.codex/config.toml\n2. Set sandbox mode: auto (default), read-only, full-access\n3. Configure writable_roots for allowed write paths\n4. Set network_access rules\n5. Set shell_environment_policy to prevent secret leaks\n6. Never use --yolo in production repos",
                "prompt_tips": "GOOD: Configure writable_roots to limit where agent can write\nBAD: Using full-access sandbox for everything\nTIP: Start with read-only for exploration, switch to auto for implementation",
            },
        ],
        "anti_patterns": [
            "Using --yolo in production repos",
            "Not configuring shell_environment_policy — leaking env secrets",
            "Not using profiles — manually switching models",
        ],
    },
}

# Cross-tool universal best practices
UNIVERSAL_PRACTICES = [
    "Keep instruction files lean — every token competes with actual code context",
    "Use deterministic tools (linters, formatters) via hooks/scripts, not AI instructions",
    "Scope instructions with globs/file-matching instead of always-on loading",
    "Clear context between unrelated tasks — stale context degrades all AI tools",
    "Use cheap models for exploration, expensive models for architecture decisions",
    "Front-load planning (Plan mode, specs) to prevent expensive rework",
    "Batch feedback and corrections instead of one-at-a-time interactions",
]
