# Semantic Extractor

**Griffe + constraints, served over MCP.**

Ground truth about framework usage rules, not just API signatures.

---

## The Problem

Griffe tells you what a framework *has*. It doesn't tell you how the framework *forces you to use it*.

- Which decorators can nest?
- What signature transformations happen?
- What are the type constraints?
- Where can a decorator legally be placed?

**LLMs need these rules to generate correct code.**

---

## The Solution

Semantic Extractor compiles framework source code into a structured IR bundle that captures:

| Layer | What It Captures | Example |
|-------|-----------------|---------|
| **API signatures** | Functions, classes, methods (Griffe-compatible) | `def command(...)` |
| **Decorator placement** | Where decorators can legally appear | `COMMAND_BUILDER = FUNCTION | TOP_LEVEL` |
| **Signature invariants** | How decorators transform function signatures | `--kebab-case` → `snake_case` parameter |
| **Type constraints** | Validation rules for parameters | `Path` constraints: `exists`, `file_okay`, `writable` |
| **Graph edges** | Parent-child relationships | `group` → `command` (contains_command) |
| **Node roles** | Multi-role bitmask | `COMMAND | CALLBACK | PARAMETER` |

**Then serves it over MCP for token-efficient, on-demand retrieval.**

---

## The Pattern

```
Framework Source Code
        ↓
[Semantic Extractor] → Static Analysis → IR Bundle (JSON)
        ↓
[MCP Server] → Queryable Knowledge for LLMs
        ↓
LLM asks: "What are the constraints on @click.option?"
MCP replies: "Must be FUNCTION. Transforms kebab-case to snake_case. Injects as keyword argument."
```

**Griffe gives you the mirror. Semantic Extractor gives you the compiler.**

---

## What It Offers That Traditional MCP Tools Don't

| | Traditional MCP | Semantic Extractor |
|--|----------------|-------------------|
| **Knowledge source** | Documentation (stale, incomplete) | Source code (ground truth) |
| **What it knows** | What the framework does | **How the framework must be used** |
| **Granularity** | Function-level | **Constraint-level** |
| **Output** | Natural language descriptions | **Structured invariants + rules** |
| **Guarantees** | "Probably correct" | **Ground truth from source** |

---

## Supported Frameworks (Validated)

### Python

- Click (decorator constraints, signature invariants)
- Loguru (lazy evaluation, binding, sinks)
- Flask (routes, methods, blueprints)
- HTTPX (client, request/response)
- SQLModel (models, relationships)
- Textual (widgets, bindings, messages)
- Starlette (routes, middleware)
- Dishka (dependency injection)
- Griffe (API extraction)
- Snoop (debugging)

### Lua/Luau

- Luau (Roblox) (type system, constraints)
- Lua (bundle)

### Swift

- SwiftUI (view modifiers, state, bindings)

---

## MCP Tools (Planned)

| Tool | Description |
|------|-------------|
| `get_framework_info` | Framework metadata, version, capabilities |
| `get_decorator_constraint` | Placement rules for a decorator |
| `get_signature_invariant` | Signature transformation rules |
| `get_type_constraint` | Type validation rules |
| `get_command_edges` | Parent-child relationship graph |
| `get_node_role` | Role bitmask for a symbol |

**The LLM doesn't guess. It retrieves ground truth.**

---

## Example: Click Decorator Constraints

```python
# Without Semantic Extractor
LLM: "I'll nest a @click.command inside another @click.command"
# → Wrong. Only groups can nest commands.

# With Semantic Extractor
LLM → MCP: get_decorator_constraint("command")
MCP → LLM: "COMMAND_BUILDER = FUNCTION | TOP_LEVEL. Cannot be nested."
LLM: "I must use @click.group to nest commands."
```

**The LLM retrieves the rule before generating incorrect code.**

---

## Repository Structure

```
semantic-extractor/
├── extractors/
│   ├── python/
│   │   ├── calyx_click_v6.py
│   │   ├── calyx_loguru.py
│   │   ├── calyx_flask_v6.py
│   │   └── ...
│   ├── lua/
│   └── swift/
├── bundles/
│   ├── calyx_click_v6.json
│   ├── calyx_loguru_v6.json
│   └── ...
├── mcp/
│   └── server.py (coming soon)
└── README.md
```

---

## License

MIT

---

**Griffe tells you what exists. Semantic Extractor tells you how it must be used.**



