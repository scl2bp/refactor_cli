## Low-LLM Deterministic Refactoring Concept

### Goal
Use an LLM only for lightweight planning and routing decisions, while deterministic tools perform the actual code transformation.

### Why this approach
- Reduces syntax and formatting risks from raw LLM-generated edits.
- Lowers token usage, cost, and runtime by limiting LLM output to small decisions.
- Produces repeatable, scriptable refactors suitable for larger codebases.

### Core pattern
1. LLM planner step:
   - Input: signatures, symbols, metadata, or short code context.
   - Output: a small structured command (for example JSON) describing what to move and where.
2. Deterministic transformer step:
   - Execute the move with syntax-aware tools (CST/AST based).
   - Update imports and preserve formatting/comments.
3. Verification step:
   - Run tests and static checks.
   - Accept only behaviorally valid changes.

### Recommended tools
- LibCST:
  - Best default for Python concrete-syntax-safe rewrites.
  - Preserves comments, whitespace, and formatting.
- Bowler:
  - Useful for scripted Python refactoring campaigns.
- Comby:
  - Strong structural search/replace across many languages.
  - Best for broad pattern rewrites, not full symbol-semantic refactors.

### Practical guidance
- Keep LLM output minimal: classification labels, destination module, move map.
- Avoid asking LLMs to generate full-file rewrites when a deterministic transform is possible.
- Encode transformation requests in machine-readable format:

```json
{
  "action": "move_symbol",
  "symbol": "parse_status",
  "from": "main.py",
  "to": "src/mobiliti/status_parser.py"
}
```

### Typical use cases
- Split a large module into cohesive submodules.
- Move helper functions into utility modules.
- Re-home classes based on bounded context.
- Apply consistent structural rewrites across many files.

### Risks and mitigations
- Risk: syntactically valid but behaviorally wrong refactor.
  - Mitigation: require pytest and lint gates before merge.
- Risk: import cycles after symbol moves.
  - Mitigation: transformer pass for import updates plus dependency checks.
- Risk: over-automation without architecture boundaries.
  - Mitigation: use ADRs and module ownership rules as input constraints.

### Team policy proposal
- Treat LLMs as planners, not code emitters, for mechanical refactors.
- Require deterministic transformation scripts for repeated refactor classes.
- Require test evidence for every automated structural change.

### Relation to SWE principles
This approach supports the principles in swe.md:
- Cohesion: easier extraction into focused modules.
- Decoupling: mechanical moves with explicit dependencies.
- Composition: encourages smaller, reusable building blocks.
- Maintainability and reliability: deterministic changes plus verification gates.
