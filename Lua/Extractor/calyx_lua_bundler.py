#!/usr/bin/env python3
"""
CALYX-LUA BUNDLER v2 - With Opcode Mapping (Fixed)
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime


# ============================================================================
# LUA OPCODES (from lopcodes.h)
# ============================================================================

# Each opcode: (name, mode, meaning)
LUA_OPCODES = [
    # Arithmetic
    ("OP_ADD", "iABC", "R(A) := RK(B) + RK(C)"),
    ("OP_SUB", "iABC", "R(A) := RK(B) - RK(C)"),
    ("OP_MUL", "iABC", "R(A) := RK(B) * RK(C)"),
    ("OP_DIV", "iABC", "R(A) := RK(B) / RK(C)"),
    ("OP_MOD", "iABC", "R(A) := RK(B) % RK(C)"),
    ("OP_POW", "iABC", "R(A) := RK(B) ^ RK(C)"),
    ("OP_UNM", "iABC", "R(A) := -R(B)"),
    ("OP_NOT", "iABC", "R(A) := not R(B)"),
    ("OP_LEN", "iABC", "R(A) := length of R(B)"),
    # Comparisons
    ("OP_EQ", "iABC", "if ((RK(B) == RK(C)) ~= A) then pc++"),
    ("OP_LT", "iABC", "if ((RK(B) <  RK(C)) ~= A) then pc++"),
    ("OP_LE", "iABC", "if ((RK(B) <= RK(C)) ~= A) then pc++"),
    # Constants and variables
    ("OP_TEST", "iABC", "if not (R(B) <=> C) then pc++"),
    ("OP_TESTSET", "iABC", "if (R(B) <=> C) then R(A) := R(B) else pc++"),
    ("OP_MOVE", "iABC", "R(A) := R(B)"),
    ("OP_LOADK", "iABx", "R(A) := Kst(Bx)"),
    ("OP_LOADBOOL", "iABC", "R(A) := (Bool)B; if (C) pc++"),
    ("OP_LOADNIL", "iABC", "R(A) := ... := R(B) := nil"),
    ("OP_GETUPVAL", "iABC", "R(A) := UpValue[B]"),
    ("OP_SETUPVAL", "iABC", "UpValue[B] := R(A)"),
    ("OP_GETTABLE", "iABC", "R(A) := R(B)[RK(C)]"),
    ("OP_SETTABLE", "iABC", "R(A)[RK(B)] := RK(C)"),
    # Jumps
    ("OP_JMP", "iAsBx", "pc+=sBx"),
    # Closures and calls
    ("OP_CLOSURE", "iABx", "R(A) := closure(KPROTO[Bx], R(A), ...)"),
    ("OP_CALL", "iABC", "R(A), ... ,R(A+C-2) := R(A)(R(A+1), ... ,R(A+B-1))"),
    ("OP_TAILCALL", "iABC", "return R(A)(R(A+1), ... ,R(A+B-1))"),
    ("OP_RETURN", "iABC", "return R(A), ... ,R(A+B-2)"),
    (
        "OP_FORLOOP",
        "iAsBx",
        "R(A)+=R(A+2); if R(A) <= R(A+1) then { pc+=sBx; R(A+3)=R(A) }",
    ),
    ("OP_FORPREP", "iAsBx", "R(A)-=R(A+2); pc+=sBx"),
    (
        "OP_TFORLOOP",
        "iABC",
        "R(A+3), ... ,R(A+2+C) := R(A)(R(A+1), R(A+2)); if R(A+3) ~= nil then pc++",
    ),
    ("OP_TFORPREP", "iAsBx", "create upvalue for R(A+3); pc+=sBx"),
    ("OP_SETLIST", "iABC", "R(A)[(C-1)*FPF+i] := R(A+i), 1 <= i <= B"),
    ("OP_CLOSE", "iABC", "close all upvalues up to R(A)"),
    ("OP_VARARG", "iABC", "R(A), R(A+1), ..., R(A+B-1) = vararg"),
]


class LuaOpcodeMap:
    """Maps opcodes to their implementation locations"""

    def __init__(self):
        self.opcodes = {}
        self.implementations = {}  # opcode -> list of (line, code_snippet)
        self.macro_definitions = {}  # store macro expansions

    def extract_macros(self, source: str) -> Dict[str, str]:
        """Extract macro definitions from source"""
        macros = {}

        # Match #define MACRO(args) body
        macro_pattern = r"#define\s+(\w+)\s*(?:\([^)]*\))?\s*(.*?)(?=\n\s*#|\n\n|$)"

        for match in re.finditer(macro_pattern, source, re.DOTALL):
            name = match.group(1)
            body = match.group(2).strip()
            # Remove trailing backslashes and join lines
            body = re.sub(r"\\\n\s*", " ", body)
            macros[name] = body

        return macros

    def expand_macro(self, name: str, macros: Dict[str, str], depth: int = 0) -> str:
        """Expand a macro recursively"""
        if depth > 10:  # Prevent infinite recursion
            return f"/* RECURSIVE MACRO: {name} */"

        if name not in macros:
            return name

        body = macros[name]

        # Find and expand nested macros
        nested_macros = re.findall(r"\b([A-Z][A-Z0-9_]+)\b", body)
        for nested in nested_macros:
            if nested != name:  # Avoid self-reference
                expanded = self.expand_macro(nested, macros, depth + 1)
                body = body.replace(nested, expanded)

        return body

    def build_from_lvm(self, lvm_source: str) -> Dict:
        """Parse lvm.c to find opcode implementations - Lua 5.1.5 specific"""

        # 1. Locate the main opcode switch
        # Look for the specific switch on GET_OPCODE(i)
        switch_start = re.search(r"switch\s*\(\s*GET_OPCODE\(i\)\s*\)\s*\{", lvm_source)
        if not switch_start:
            print("Warning: Could not find the main opcode switch statement")
            return {}

        # 2. Extract the body of the switch using brace counting
        start_pos = switch_start.end() - 1  # Position of the opening '{'
        brace_count = 0
        body_end = -1

        for i in range(start_pos, len(lvm_source)):
            if lvm_source[i] == "{":
                brace_count += 1
            elif lvm_source[i] == "}":
                brace_count -= 1
                if brace_count == 0:
                    body_end = i
                    break

        if body_end == -1:
            print("Warning: Could not find closing brace for switch statement")
            return {}

        switch_body = lvm_source[start_pos + 1 : body_end]  # Exclude the opening '{'

        # 3. Extract opcode implementations
        # Pattern matches: case OP_NAME: { ... continue; }
        # The non-greedy [\s\S]*? captures everything until the continue
        case_pattern = r"case\s+(OP_\w+):\s*\{([\s\S]*?)\s+continue;\s*\}"

        found_opcodes = {}
        for match in re.finditer(case_pattern, switch_body):
            op_name = match.group(1)
            op_code_body = match.group(2).strip()

            # Extract key operations from the implementation
            key_ops = self._extract_key_ops_from_body(op_code_body)

            found_opcodes[op_name] = {
                "code": op_code_body[:500],  # First 500 chars
                "lines": len(op_code_body.split("\n")),
                "key_operations": key_ops,
            }

        print(f"Successfully mapped {len(found_opcodes)} opcodes")
        return found_opcodes

    def _extract_key_ops_from_body(self, body: str) -> List[str]:
        """Extract key function/macro calls from opcode implementation body"""
        ops = []

        # Patterns to look for
        patterns = [
            r"\b(Arith)\s*\(",  # Arithmetic fallback
            r"\b(luaV_\w+)\s*\(",  # luaV_* functions
            r"\b(luaH_\w+)\s*\(",  # luaH_* functions
            r"\b(luaD_\w+)\s*\(",  # luaD_* functions
            r"\b(luaG_\w+)\s*\(",  # luaG_* functions
            r"\b(luaC_\w+)\s*\(",  # luaC_* functions
            r"\b(luaM_\w+)\s*\(",  # luaM_* functions
            r"\b(luai_num\w+)\s*\(",  # Arithmetic macros
            r"\b(call_(?:bin|order)TM)\s*\(",  # Tag method calls
            r"\b(equalobj)\s*\(",  # Object equality
            r"\b(l_isfalse)\s*\(",  # Boolean check
            r"\b(tostring)\s*\(",  # String conversion
            r"\b(tonumber)\s*\(",  # Number conversion
        ]

        for pattern in patterns:
            for match in re.findall(pattern, body):
                if isinstance(match, tuple):
                    ops.extend(match)
                else:
                    ops.append(match)

        return list(set(ops))

    def expand_implementation(self, impl: str) -> str:
        """Expand macros in implementation code"""
        # Find macro calls (uppercase identifiers)
        macro_pattern = r"\b([A-Z][A-Z0-9_]+)\b"

        expanded = impl
        for macro_name in re.findall(macro_pattern, impl):
            if macro_name in self.macro_definitions:
                macro_body = self.macro_definitions[macro_name]
                # Simple expansion (doesn't handle arguments)
                expanded = expanded.replace(
                    macro_name, f"/* {macro_name} */ {macro_body}"
                )

        return expanded

    def _extract_macro_calls(self, code: str) -> List[str]:
        """Extract macro names from implementation"""
        macros = []
        macro_pattern = r"\b([A-Z][A-Z0-9_]+)\b"
        for match in re.findall(macro_pattern, code):
            if match not in ["OP_ADD", "OP_SUB", "L", "TM_ADD"]:  # Filter noise
                macros.append(match)
        return list(set(macros))

    def _extract_key_ops(self, code: str) -> List[str]:
        """Extract key function calls from implementation"""
        ops = []
        patterns = [
            r"luaV_(\w+)\(",
            r"luaH_(\w+)\(",
            r"luaD_(\w+)\(",
            r"luaG_(\w+)\(",
            r"luaC_(\w+)\(",
            r"luaM_(\w+)\(",
            r"api_(\w+)\(",
            r"Arith\(",  # The Arith function call
            r"luai_num(\w+)\(",  # Arithmetic macros
            r"call_(?:bin|order)TM",  # Tag method calls
        ]
        for pattern in patterns:
            for match in re.findall(pattern, code):
                ops.append(match if isinstance(match, str) else match[0])
        return list(set(ops))

    def generate_map_table(self) -> str:
        """Generate the opcode mapping table as C comment"""
        lines = []
        lines.append("/*")
        lines.append("=" * 78)
        lines.append("OPCODE-TO-IMPLEMENTATION MAP (Lua 5.1.5)")
        lines.append("=" * 78)
        lines.append("")
        lines.append("Bytecode dispatch happens in luaV_execute() (lvm.c)")
        lines.append("Each opcode maps to a case label in the main switch.")
        lines.append("The VM uses 'continue' to jump to the next instruction.")
        lines.append("")

        for opcode_name, mode, meaning in LUA_OPCODES:
            lines.append(f"  {opcode_name}:")
            lines.append(f"    Format: {mode}")
            lines.append(f"    Meaning: {meaning}")

            # Add implementation details if found
            if opcode_name in self.implementations:
                impl = self.implementations[opcode_name]
                lines.append(f"    Implementation: {impl['lines']} lines")
                if impl["key_operations"]:
                    lines.append(
                        f"    Key operations: {', '.join(impl['key_operations'][:5])}"
                    )

                # Show the actual code snippet (first 150 chars)
                code = impl["code"].replace("\n", "\n    ")
                if len(code) > 150:
                    code = code[:150] + "..."
                lines.append(f"    Code: {code}")
            else:
                lines.append(f"    Implementation: (not captured - see lvm.c directly)")
            lines.append("")

        lines.append("")
        lines.append("VM Execution Flow:")
        lines.append("  luaV_execute() [lvm.c]")
        lines.append("    ├── for(;;) loop")
        lines.append("    │   ├── GET_OPCODE(i) → switch")
        lines.append(
            "    │   │   ├── case OP_ADD: arith_op(luai_numadd) → direct arithmetic"
        )
        lines.append("    │   │   ├── case OP_CALL: luaD_precall → luaD_call")
        lines.append("    │   │   ├── case OP_RETURN: luaD_poscall")
        lines.append("    │   │   ├── case OP_GETTABLE: luaV_gettable → luaH_get")
        lines.append("    │   │   └── case OP_SETTABLE: luaV_settable → luaH_set")
        lines.append("    │   └── continue; (next instruction)")
        lines.append("    └── return; (function returns)")
        lines.append("")
        lines.append("Key Helper Functions:")
        lines.append(
            "  arith_op(luai_numadd, TM_ADD) → arithmetic with metatable fallback"
        )
        lines.append(
            "  luaV_gettable / luaV_settable → table access with __index/__newindex"
        )
        lines.append("  luaD_precall / luaD_poscall → function call setup/teardown")
        lines.append("  luaV_concat → string concatenation")
        lines.append(
            "  luaV_lessthan / luaV_equalval → comparisons with __lt/__le/__eq"
        )
        lines.append("  luaF_close → close upvalues (for OP_CLOSE)")
        lines.append("*/")

        return "\n".join(lines)


# ============================================================================
# ENHANCED LUA BUNDLER
# ============================================================================


class LuaBundlerV2:
    """Lua bundler with opcode mapping and vertical slicing"""

    def __init__(self, root: str = ".", verbose: bool = False):
        self.root = Path(root)
        self.verbose = verbose
        self.files: Dict[str, str] = {}
        self.headers: Dict[str, str] = {}
        self.opcode_map = LuaOpcodeMap()

    def log(self, msg: str):
        if self.verbose:
            print(f"[LUA-CALYX] {msg}")

    def read_file(self, path: Path) -> Optional[str]:
        """Read file safely"""
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception as e:
            self.log(f"Error reading {path}: {e}")
            return None

    def discover(self) -> None:
        """Discover all C/H files"""
        # Try src/ first (Lua 5.1.5 standard layout)
        src_dir = self.root / "src"
        if src_dir.exists():
            search_dir = src_dir
        else:
            search_dir = self.root

        self.log(f"Searching in: {search_dir}")

        for ext in ["*.c", "*.h"]:
            for path in search_dir.glob(ext):
                content = self.read_file(path)
                if content:
                    name = path.name
                    self.files[name] = content
                    if name.endswith(".h"):
                        self.headers[name] = content
                    self.log(f"Loaded: {name}")

        self.log(f"Total files loaded: {len(self.files)}")

    def build_opcode_map(self) -> Dict:
        """Build opcode mapping from lvm.c"""
        if "lvm.c" in self.files:
            self.log("Building opcode map from lvm.c...")
            return self.opcode_map.build_from_lvm(self.files["lvm.c"])
        else:
            self.log("Warning: lvm.c not found in bundle")
            return {}

    def generate_tag_invariants(self) -> str:
        """Generate TValue type tag truth table"""
        lines = []
        lines.append("/*")
        lines.append("=" * 78)
        lines.append("TYPE TAG INVARIANTS (TValue in lobject.h)")
        lines.append("=" * 78)
        lines.append("*/")
        lines.append("/*")
        lines.append("")
        lines.append(
            "Lua uses a tagged union for all values. The tag (tt) is stored in"
        )
        lines.append("the low bits of the value union. Understanding these bits is")
        lines.append("critical for debugging GC and the API.")
        lines.append("")
        lines.append("Basic Types (from lua.h):")
        lines.append("  #define LUA_TNIL          0")
        lines.append("  #define LUA_TBOOLEAN      1")
        lines.append("  #define LUA_TLIGHTUSERDATA 2")
        lines.append("  #define LUA_TNUMBER       3")
        lines.append("  #define LUA_TSTRING       4")
        lines.append("  #define LUA_TTABLE        5")
        lines.append("  #define LUA_TFUNCTION     6")
        lines.append("  #define LUA_TUSERDATA     7")
        lines.append("  #define LUA_TTHREAD       8")
        lines.append("")
        lines.append("GC-Related (from lobject.h):")
        lines.append("  #define BIT_ISCOLLECTABLE (1<<5)")
        lines.append("  #define BIT_ISCOLLECTABLE_MASK (BIT_ISCOLLECTABLE)")
        lines.append("")
        lines.append("Collectable types have BIT_ISCOLLECTABLE set:")
        lines.append("  LUA_TSTRING   (4 | 0x20 = 36)  // collectable")
        lines.append("  LUA_TTABLE    (5 | 0x20 = 37)  // collectable")
        lines.append("  LUA_TFUNCTION (6 | 0x20 = 38)  // collectable")
        lines.append("  LUA_TUSERDATA (7 | 0x20 = 39)  // collectable")
        lines.append("  LUA_TTHREAD   (8 | 0x20 = 40)  // collectable")
        lines.append("")
        lines.append("This bit is used by the GC to know what to traverse.")
        lines.append("*/")
        return "\n".join(lines)

    def generate_stack_diagram(self) -> str:
        """Generate ASCII stack frame diagram"""
        return """/*
================================================================================
STACK FRAME DIAGRAM (lua_State)
================================================================================

A lua_State contains the stack and call frames. Understanding this layout is
essential for following C API code.

```
+-------------------+  <- L->stack
|                   |
|  ...              |
|                   |
+-------------------+  <- L->base (current function's base)
|  local variables  |
|                   |
+-------------------+  <- L->top (top of stack)
|  free space       |
|                   |
+-------------------+  <- L->stack_last
```

When a function is called, a new CallInfo is pushed:

```
CallInfo (L->ci)                    Stack
+-------------------+               +-------------------+
| func              | ------------->| function value    |
| top               | ------------->| (parameters...)  |
| base              | ------------->| (locals start)   |
| savedpc           |               +-------------------+
+-------------------+               | ...               |
                                    +-------------------+
```

Key macros (from lua.h):

  lua_gettop(L)    → (L->top - L->base)  // number of stack slots
  lua_settop(L, n) → L->top = L->base + n
  lua_pushvalue(L, idx) → *L->top = *index2addr(L, idx); L->top++

The API index convention:
  Positive indices = absolute (1..n)
  Negative indices = relative to top (-1 = top, -2 = below, etc.)

*/
"""

    def generate_vertical_slices(self) -> str:
        """Generate file grouping by functional vertical"""

        verticals = {
            "GC_SUBSYSTEM": ["lgc.c", "lmem.c", "lstate.c"],
            "STRING_SUBSYSTEM": ["lstring.c"],
            "TABLE_SUBSYSTEM": ["ltable.c", "lobject.c"],
            "VM_EXECUTION": ["lvm.c", "lopcodes.c", "ldo.c"],
            "PARSER_SUBSYSTEM": ["llex.c", "lparser.c", "lcode.c"],
            "API_LAYER": ["lapi.c", "lauxlib.c"],
            "DEBUG_SUBSYSTEM": ["ldebug.c"],
        }

        lines = []
        lines.append("/*")
        lines.append("=" * 78)
        lines.append("VERTICAL SLICES (Functional Subsystems)")
        lines.append("=" * 78)
        lines.append("*/")
        lines.append("/*")

        for subsystem, files in verticals.items():
            lines.append(f"\n  {subsystem}:")
            for f in files:
                if f in self.files:
                    # Get function count from file
                    content = self.files[f]
                    funcs = re.findall(r"^\s*\w+\s+\w+\s*\(", content, re.MULTILINE)
                    lines.append(f"    - {f} ({len(funcs)} functions)")
                else:
                    lines.append(f"    - {f} (NOT FOUND)")

        lines.append("")
        lines.append(
            "Navigation: When debugging a specific issue, focus on the relevant vertical."
        )
        lines.append("  - Memory leak? → GC_SUBSYSTEM + STRING_SUBSYSTEM")
        lines.append("  - Table lookup slow? → TABLE_SUBSYSTEM")
        lines.append("  - Parsing error? → PARSER_SUBSYSTEM")
        lines.append("  - API crash? → API_LAYER + VM_EXECUTION")
        lines.append("*/")

        return "\n".join(lines)

    def generate_bundle(self, output_path: str) -> str:
        """Generate complete LLM-optimized bundle"""

        self.log("Building opcode map with macro expansion...")

        # Load lvm.c first for macro extraction
        lvm_content = self.files.get("lvm.c", "")
        if lvm_content:
            # Also need to load headers for macro definitions
            macro_sources = [lvm_content]
            for header in ["lobject.h", "lua.h", "lopcodes.h", "ldo.h"]:
                if header in self.files:
                    macro_sources.append(self.files[header])

            # Combine macro sources
            combined = "\n".join(macro_sources)
            self.opcode_map.macro_definitions.update(
                self.opcode_map.extract_macros(combined)
            )

            opcode_impl = self.opcode_map.build_from_lvm(lvm_content)
            self.log(f"Found {len(opcode_impl)} opcode implementations")
            for op, impl in list(opcode_impl.items())[:5]:
                self.log(
                    f"  {op}: {impl['lines']} lines, calls {impl['key_operations'][:3]}"
                )
        else:
            opcode_impl = {}
            self.log("Warning: lvm.c not found in bundle")

        lines = []

        # Header
        lines.append("/*" + "=" * 78 + "*/")
        lines.append("/* CALYX-LUA BUNDLE v2 - With Opcode Mapping */")
        lines.append("/* Target: Lua 5.1.5 - Full Mechanical Context */")
        lines.append("/* " + "=" * 78 + "*/")
        lines.append("")

        # Reading Guide (enhanced)
        lines.append("/*")
        lines.append("READING GUIDE - HOW TO REASON ABOUT LUA")
        lines.append("")
        lines.append(
            "This bundle provides BOTH source code AND the mental model of the author."
        )
        lines.append("")
        lines.append("LAYERS OF UNDERSTANDING:")
        lines.append("  1. OPCODE MAP - What bytecode instructions exist")
        lines.append("  2. IMPLEMENTATION MAP - Where each opcode is implemented")
        lines.append("  3. TYPE INVARIANTS - How TValue tags work")
        lines.append("  4. STACK MODEL - How lua_State and stack pointers work")
        lines.append("  5. VERTICAL SLICES - Which files belong together")
        lines.append("")
        lines.append("To answer a question, trace the path:")
        lines.append("  Bytecode → Implementation → Stack effect → API call")
        lines.append("*/")
        lines.append("")

        # SECTION: OPCODE MAP
        lines.append(self.opcode_map.generate_map_table())
        lines.append("")

        # SECTION: TYPE INVARIANTS
        lines.append(self.generate_tag_invariants())
        lines.append("")

        # SECTION: STACK DIAGRAM
        lines.append(self.generate_stack_diagram())
        lines.append("")

        # SECTION: VERTICAL SLICES
        lines.append(self.generate_vertical_slices())
        lines.append("")

        # SECTION: HEADERS (in order)
        lines.append("/*")
        lines.append("=" * 78)
        lines.append("HEADER FILES (In Dependency Order)")
        lines.append("=" * 78)
        lines.append("*/")

        header_order = ["luaconf.h", "lua.h", "lauxlib.h", "lualib.h"]
        for h in header_order:
            if h in self.files:
                lines.append(f"\n/* === {h} === */")
                lines.append(self.files[h])

        # Remaining headers
        for name, content in self.files.items():
            if name.endswith(".h") and name not in header_order:
                lines.append(f"\n/* === {name} === */")
                lines.append(content)

        # SECTION: SOURCE FILES (by vertical)
        lines.append("/*")
        lines.append("=" * 78)
        lines.append("SOURCE FILES (Grouped by Functional Vertical)")
        lines.append("=" * 78)
        lines.append("*/")

        # Define order of verticals
        vertical_order = [
            "GC_SUBSYSTEM",
            "STRING_SUBSYSTEM",
            "TABLE_SUBSYSTEM",
            "VM_EXECUTION",
            "PARSER_SUBSYSTEM",
            "API_LAYER",
            "DEBUG_SUBSYSTEM",
        ]

        verticals = {
            "GC_SUBSYSTEM": ["lgc.c", "lmem.c", "lstate.c"],
            "STRING_SUBSYSTEM": ["lstring.c"],
            "TABLE_SUBSYSTEM": ["ltable.c", "lobject.c"],
            "VM_EXECUTION": ["lvm.c", "lopcodes.c", "ldo.c"],
            "PARSER_SUBSYSTEM": ["llex.c", "lparser.c", "lcode.c"],
            "API_LAYER": ["lapi.c", "lauxlib.c"],
            "DEBUG_SUBSYSTEM": ["ldebug.c"],
        }

        for vertical in vertical_order:
            lines.append(f"\n/* --- {vertical} --- */")
            for filename in verticals.get(vertical, []):
                if filename in self.files:
                    lines.append(f"\n/* === {filename} === */")
                    lines.append(self.files[filename])

        # Remaining C files
        lines.append("\n/* --- OTHER FILES --- */")
        for name, content in self.files.items():
            if name.endswith(".c") and not any(
                name in files for files in verticals.values()
            ):
                lines.append(f"\n/* === {name} === */")
                lines.append(content)

        # Write file
        output_path = Path(output_path)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        # Stats
        print(f"\n{'=' * 60}")
        print("CALYX-LUA BUNDLE v2 COMPLETE")
        print(f"{'=' * 60}")
        print(f"Output: {output_path}")
        print(f"Size: {output_path.stat().st_size / 1024:.1f} KB")
        print(f"Files bundled: {len(self.files)}")
        print(f"Opcodes mapped: {len([i for i in opcode_impl if i])}")
        print(f"Verticals: {len(verticals)}")
        print(f"{'=' * 60}")

        return str(output_path)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="CALYX-LUA Bundler v2 - With Opcode Mapping"
    )
    parser.add_argument("--root", "-r", default=".", help="Lua source root")
    parser.add_argument("--output", "-o", default="calyx_lua_v2.c", help="Output file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    bundler = LuaBundlerV2(root=args.root, verbose=args.verbose)
    bundler.discover()

    if not bundler.files:
        print("Error: No source files found!")
        print(f"Checked in: {Path(args.root).resolve()}")
        sys.exit(1)

    bundler.generate_bundle(args.output)


if __name__ == "__main__":
    import sys

    main()
