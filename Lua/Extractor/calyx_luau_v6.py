#!/usr/bin/env python3
"""
CALYX-LUAU BUNDLER v6.0 - Type-Aware Bytecode IR
Adapted from Lua 5.1.5 for Luau's C++ codebase, type system, and modified VM
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from collections import Counter, defaultdict

# ============================================================================
# LUAU OPCODES (from Bytecode.h - Luau-specific)
# ============================================================================

# Luau opcodes differ from Lua 5.1
LUAU_OPCODES = [
    # Basics
    ("LOP_NOP", "No operation"),
    ("LOP_LOADNIL", "R(A) := nil"),
    ("LOP_LOADB", "R(A) := boolean literal"),
    ("LOP_LOADN", "R(A) := number constant"),
    ("LOP_LOADK", "R(A) := constant"),
    # Variables and upvalues
    ("LOP_MOVE", "R(A) := R(B)"),
    ("LOP_GETGLOBAL", "R(A) := global[constant]"),
    ("LOP_SETGLOBAL", "global[constant] := R(A)"),
    ("LOP_GETUPVAL", "R(A) := upvalue[B]"),
    ("LOP_SETUPVAL", "upvalue[B] := R(A)"),
    ("LOP_CLOSEUPVALS", "Close upvalues up to R(A)"),
    # Imports (Luau-specific)
    ("LOP_GETIMPORT", "R(A) := import(constants[D])"),
    # Table operations
    ("LOP_GETTABLEKS", "R(A) := R(B)[constant string]"),
    ("LOP_SETTABLEKS", "R(B)[constant string] := R(A)"),
    ("LOP_GETTABLE", "R(A) := R(B)[R(C)]"),
    ("LOP_SETTABLE", "R(A)[R(B)] := R(C)"),
    ("LOP_GETTABLEN", "R(A) := R(B)[C]"),
    ("LOP_SETTABLEN", "R(B)[C] := R(A)"),
    ("LOP_NEWTABLE", "R(A) := {} (table constructor)"),
    ("LOP_DUPTABLE", "R(A) := duplicate template table"),
    ("LOP_SETLIST", "R(A)[C+i] := R(A+i), 1 <= i <= B"),
    # Closures
    ("LOP_NEWCLOSURE", "R(A) := closure(proto)"),
    # Method calls (Luau-specific optimization)
    ("LOP_NAMECALL", "R(A) := R(B); R(A+1) := R(B)[namecall index]"),
    # Calls and returns
    ("LOP_CALL", "R(A), ..., R(A+C-2) := R(A)(R(A+1), ..., R(A+B-1))"),
    ("LOP_RETURN", "return R(A), ..., R(A+B-2)"),
    # Jumps
    ("LOP_JUMP", "pc += D"),
    ("LOP_JUMPIF", "if R(A) then pc += D"),
    ("LOP_JUMPIFNOT", "if not R(A) then pc += D"),
    ("LOP_JUMPIFEQ", "if R(A) == R(D) then pc += E"),
    ("LOP_JUMPIFLE", "if R(A) <= R(D) then pc += E"),
    ("LOP_JUMPIFLT", "if R(A) < R(D) then pc += E"),
    ("LOP_JUMPIFNOTEQ", "if R(A) != R(D) then pc += E"),
    ("LOP_JUMPIFNOTLE", "if not (R(A) <= R(D)) then pc += E"),
    ("LOP_JUMPIFNOTLT", "if not (R(A) < R(D)) then pc += E"),
    # Arithmetic
    ("LOP_ADD", "R(A) := R(B) + R(C)"),
    ("LOP_SUB", "R(A) := R(B) - R(C)"),
    ("LOP_MUL", "R(A) := R(B) * R(C)"),
    ("LOP_DIV", "R(A) := R(B) / R(C)"),
    ("LOP_MOD", "R(A) := R(B) % R(C)"),
    ("LOP_POW", "R(A) := R(B) ^ R(C)"),
    ("LOP_ADDK", "R(A) := R(B) + K(C)"),
    ("LOP_SUBK", "R(A) := R(B) - K(C)"),
    ("LOP_MULK", "R(A) := R(B) * K(C)"),
    ("LOP_DIVK", "R(A) := R(B) / K(C)"),
    ("LOP_MODK", "R(A) := R(B) % K(C)"),
    ("LOP_POWK", "R(A) := R(B) ^ K(C)"),
    # Unary operations
    ("LOP_NOT", "R(A) := not R(B)"),
    ("LOP_MINUS", "R(A) := -R(B)"),
    ("LOP_LENGTH", "R(A) := #R(B)"),
    # Loops
    ("LOP_FORNPREP", "Numeric for loop prep"),
    ("LOP_FORNLOOP", "Numeric for loop"),
    ("LOP_FORGPREP", "Generic for loop prep (Luau-specific)"),
    ("LOP_FORGLOOP", "Generic for loop body"),
    ("LOP_FORGPREP_NEXT", "Optimized pairs() prep"),
    ("LOP_FORGPREP_INEXT", "Optimized ipairs() prep"),
    # Concatenation
    ("LOP_CONCAT", "R(A) := R(B) .. ... .. R(C)"),
    # Type checks (Luau-specific)
    ("LOP_LOADKX", "R(A) := K(extra)"),
    ("LOP_JUMPX", "pc += E (extended range)"),
    ("LOP_FASTCALL", "Optimized call for known functions"),
    ("LOP_FASTCALL1", "Fast call with 1 arg"),
    ("LOP_FASTCALL2", "Fast call with 2 args"),
    ("LOP_FASTCALL2K", "Fast call with 2 args (one constant)"),
    # Coverage (Luau-specific)
    ("LOP_COVERAGE", "Coverage tracking"),
    # Captures
    ("LOP_CAPTURE", "Capture variable for closure"),
    # And/Or jumps
    ("LOP_JUMPXEQKNIL", "Extended jump if == nil"),
    ("LOP_JUMPXEQKB", "Extended jump if == boolean"),
    ("LOP_JUMPXEQKN", "Extended jump if == number"),
    ("LOP_JUMPXEQKS", "Extended jump if == string"),
]

# ============================================================================
# LUAU TYPE SYSTEM
# ============================================================================

LUAU_TYPE_PRIMITIVES = {
    "nil": "Absence of value",
    "boolean": "true or false",
    "number": "Double-precision float",
    "string": "Immutable byte sequence",
    "function": "Callable",
    "table": "Associative array",
    "userdata": "Opaque C data",
    "thread": "Coroutine",
}

LUAU_TYPE_OPERATORS = {
    "|": "Union type (A | B)",
    "&": "Intersection type (A & B)",
    "?": "Optional type (T?)",
    "...": "Variadic type pack",
    "<T>": "Generic type parameter",
}

LUAU_TYPE_ANNOTATIONS = {
    "variable": "local x: number",
    "parameter": "function f(x: string)",
    "return": "function f(): boolean",
    "table": "{ x: number, y: string }",
    "function_type": "(number, string) -> boolean",
    "generic": "function<T>(x: T): T",
    "type_alias": "type Point = { x: number, y: number }",
}

# ============================================================================
# LIBRARY DIFFERENCES (Lua 5.1 vs Luau)
# ============================================================================

REMOVED_LIBRARIES = {
    "io": "File I/O removed (sandboxed)",
    "os": "Most OS functions removed (only clock/date/difftime/time)",
    "debug": "Debug library removed (security)",
    "package": "Module system replaced with require()",
    "loadstring": "Replaced with loadstring(source, chunkname)",
}

ADDED_LIBRARIES = {
    "bit32": "Bitwise operations",
    "utf8": "UTF-8 string operations",
    "buffer": "Binary buffer operations (Luau-specific)",
}

MODIFIED_FUNCTIONS = {
    "string.split": "Added (convenience)",
    "table.move": "Added",
    "table.freeze": "Added (make table immutable)",
    "table.isfrozen": "Added",
    "table.clone": "Added (shallow copy)",
    "table.clear": "Added (remove all elements)",
    "math.clamp": "Added",
    "math.sign": "Added",
    "math.round": "Added",
}

# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class LuauOpcode:
    name: str
    meaning: str
    implementation: str = ""
    key_functions: List[str] = field(default_factory=list)


@dataclass
class LuauTypeInfo:
    name: str
    category: str  # "primitive", "composite", "union", "intersection", "generic"
    definition: str
    constraints: List[str] = field(default_factory=list)


@dataclass
class LuauModule:
    name: str
    category: str  # "VM", "Analysis", "Compiler", "AST", "CodeGen"
    exports: List[str]
    imports: List[str]
    type_annotations: List[str] = field(default_factory=list)
    opcodes_implemented: List[str] = field(default_factory=list)


# ============================================================================
# MAIN BUNDLER CLASS
# ============================================================================


class CalyxLuauBundlerV6:
    def __init__(self, root: str = ".", verbose: bool = False):
        self.root = Path(root)
        self.verbose = verbose
        self.files: Dict[str, str] = {}
        self.headers: Dict[str, str] = {}
        self.modules: Dict[str, LuauModule] = {}
        self.opcodes: Dict[str, LuauOpcode] = {}
        self.type_info: Dict[str, LuauTypeInfo] = {}

    def log(self, msg: str):
        if self.verbose:
            print(f"[LUAU-CALYX] {msg}")

    def read_file(self, path: Path) -> Optional[str]:
        """Read file safely"""
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception as e:
            self.log(f"Error reading {path}: {e}")
            return None

    def discover(self) -> None:
        """Discover Luau source files (C++ structure)"""
        # Luau directories
        luau_dirs = ["VM", "Analysis", "Compiler", "AST", "CodeGen", "Common"]

        self.log(f"Searching in: {self.root}")

        for dirname in luau_dirs:
            dir_path = self.root / dirname
            if not dir_path.exists():
                continue

            self.log(f"Processing {dirname}/")

            # Process src/ subdirectory
            src_dir = dir_path / "src"
            if src_dir.exists():
                for ext in ["*.cpp", "*.h"]:
                    for path in src_dir.glob(ext):
                        content = self.read_file(path)
                        if content:
                            name = f"{dirname}/{path.name}"
                            self.files[name] = content
                            if path.name.endswith(".h"):
                                self.headers[name] = content
                            self.log(f"  Loaded: {name}")

            # Process include/ subdirectory
            inc_dir = dir_path / "include"
            if inc_dir.exists():
                for path in inc_dir.glob("**/*.h"):
                    content = self.read_file(path)
                    if content:
                        name = f"{dirname}/include/{path.name}"
                        self.files[name] = content
                        self.headers[name] = content
                        self.log(f"  Loaded: {name}")

        self.log(f"Total files loaded: {len(self.files)}")

    def extract_opcodes_from_vm(self, vm_source: str) -> Dict[str, LuauOpcode]:
        """Extract opcode implementations from lvmexecute.cpp"""
        opcodes = {}

        # Find VM_CASE statements
        case_pattern = r"VM_CASE\((LOP_\w+)\)\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}"

        for match in re.finditer(case_pattern, vm_source, re.DOTALL):
            op_name = match.group(1)
            op_body = match.group(2)

            # Extract key function calls
            key_funcs = self._extract_key_functions(op_body)

            # Find meaning from LUAU_OPCODES
            meaning = next((m for n, m in LUAU_OPCODES if n == op_name), "")

            opcodes[op_name] = LuauOpcode(
                name=op_name,
                meaning=meaning,
                implementation=op_body[:500],  # First 500 chars
                key_functions=key_funcs,
            )

        return opcodes

    def _extract_key_functions(self, code: str) -> List[str]:
        """Extract important function calls from opcode implementation"""
        funcs = []

        patterns = [
            r"\b(luau_\w+)\s*\(",
            r"\b(luaV_\w+)\s*\(",
            r"\b(luaH_\w+)\s*\(",
            r"\b(luaD_\w+)\s*\(",
            r"\b(luaC_\w+)\s*\(",
            r"\b(luaT_\w+)\s*\(",
            r"\b(luaF_\w+)\s*\(",
            r"\b(VM_\w+)\s*\(",
        ]

        for pattern in patterns:
            for match in re.findall(pattern, code):
                if isinstance(match, str):
                    funcs.append(match)

        return list(set(funcs))

    def extract_type_system(self) -> Dict[str, LuauTypeInfo]:
        """Extract type system from Analysis directory"""
        type_info = {}

        # Look for type definitions in Analysis headers
        for name, content in self.files.items():
            if "Analysis" not in name:
                continue

            # Extract struct/class type definitions
            struct_pattern = r"struct\s+(\w+Type)\s*(?::\s*public\s+(\w+))?"
            for match in re.finditer(struct_pattern, content):
                type_name = match.group(1)
                base_type = match.group(2) or "Type"

                type_info[type_name] = LuauTypeInfo(
                    name=type_name,
                    category="composite",
                    definition=f"struct {type_name} : {base_type}",
                )

        # Add primitives
        for prim, desc in LUAU_TYPE_PRIMITIVES.items():
            type_info[prim] = LuauTypeInfo(
                name=prim,
                category="primitive",
                definition=desc,
            )

        return type_info

    def analyze_modules(self) -> Dict[str, LuauModule]:
        """Categorize files into functional modules"""
        modules = {}

        for name, content in self.files.items():
            # Determine category from path
            category = name.split("/")[0] if "/" in name else "Other"

            # Extract exports (public functions/classes)
            exports = self._extract_exports(content)

            # Extract imports (includes)
            imports = self._extract_includes(content)

            # Extract type annotations (if Luau source, not C++)
            type_annotations = self._extract_type_annotations(content)

            modules[name] = LuauModule(
                name=name,
                category=category,
                exports=exports,
                imports=imports,
                type_annotations=type_annotations,
            )

        return modules

    def _extract_exports(self, content: str) -> List[str]:
        """Extract public symbols from C++ file"""
        exports = []

        # Public functions
        func_pattern = r"^(?:LUAI_FUNC|LUAU_FASTFLAG|LUA_API)\s+\w+\s+(\w+)\s*\("
        for match in re.finditer(func_pattern, content, re.MULTILINE):
            exports.append(match.group(1))

        # Public structs/classes
        struct_pattern = r"^struct\s+(\w+)\s*\{"
        for match in re.finditer(struct_pattern, content, re.MULTILINE):
            exports.append(match.group(1))

        return exports[:20]  # Limit

    def _extract_includes(self, content: str) -> List[str]:
        """Extract #include statements"""
        includes = []
        include_pattern = r'#include\s+["<]([^">]+)[">]'
        for match in re.findall(include_pattern, content):
            includes.append(match)
        return includes[:15]  # Limit

    def _extract_type_annotations(self, content: str) -> List[str]:
        """Extract Luau type annotations if present"""
        annotations = []

        # This would parse .luau files, not C++
        # For C++ files, we look for type-related code
        type_patterns = [
            r"TypeVar\s+(\w+)",
            r"TypeId\s+(\w+)",
            r"TypePackId\s+(\w+)",
        ]

        for pattern in type_patterns:
            for match in re.findall(pattern, content):
                annotations.append(match)

        return annotations[:10]  # Limit

    def generate_opcode_map(self) -> str:
        """Generate comprehensive opcode map"""
        lines = []
        lines.append("/*")
        lines.append("=" * 78)
        lines.append("LUAU OPCODE MAP (Modified from Lua 5.1)")
        lines.append("=" * 78)
        lines.append("")
        lines.append("Luau's VM is in VM/src/lvmexecute.cpp")
        lines.append("Dispatch uses VM_CASE() macros with computed goto or switch")
        lines.append("")
        lines.append("KEY DIFFERENCES FROM LUA 5.1:")
        lines.append(
            "  - Removed: OP_GETGLOBAL/SETGLOBAL (replaced with optimized versions)"
        )
        lines.append("  - Added: LOP_GETIMPORT (fast imports)")
        lines.append("  - Added: LOP_NAMECALL (method call optimization)")
        lines.append("  - Added: LOP_FASTCALL* (type-stable fast paths)")
        lines.append("  - Modified: Jump instructions support longer ranges")
        lines.append("  - Added: Arithmetic with constants (*K variants)")
        lines.append("")

        for op_name, meaning in LUAU_OPCODES:
            lines.append(f"  {op_name}:")
            lines.append(f"    {meaning}")

            if op_name in self.opcodes:
                opcode = self.opcodes[op_name]
                if opcode.key_functions:
                    lines.append(f"    Calls: {', '.join(opcode.key_functions[:5])}")
            lines.append("")

        lines.append("*/")
        return "\n".join(lines)

    def generate_type_system_doc(self) -> str:
        """Generate type system documentation"""
        lines = []
        lines.append("/*")
        lines.append("=" * 78)
        lines.append("LUAU TYPE SYSTEM")
        lines.append("=" * 78)
        lines.append("")
        lines.append("Luau is a GRADUALLY TYPED language:")
        lines.append("  - Types are optional but checked when present")
        lines.append("  - Type inference fills in missing annotations")
        lines.append("  - Runtime is type-erased (types don't affect execution)")
        lines.append("")
        lines.append("PRIMITIVE TYPES:")
        for prim, desc in LUAU_TYPE_PRIMITIVES.items():
            lines.append(f"  {prim}: {desc}")
        lines.append("")
        lines.append("TYPE OPERATORS:")
        for op, desc in LUAU_TYPE_OPERATORS.items():
            lines.append(f"  {op}: {desc}")
        lines.append("")
        lines.append("TYPE ANNOTATIONS:")
        for context, example in LUAU_TYPE_ANNOTATIONS.items():
            lines.append(f"  {context}: {example}")
        lines.append("")
        lines.append("TYPE CHECKING:")
        lines.append("  - Happens in Analysis/ directory")
        lines.append("  - Unification-based inference")
        lines.append("  - Bidirectional type checking")
        lines.append("  - Generic type instantiation")
        lines.append("")
        lines.append("*/")
        return "\n".join(lines)

    def generate_library_changes(self) -> str:
        """Document library differences from Lua 5.1"""
        lines = []
        lines.append("/*")
        lines.append("=" * 78)
        lines.append("LIBRARY CHANGES (Lua 5.1 → Luau)")
        lines.append("=" * 78)
        lines.append("")
        lines.append("REMOVED (for sandboxing):")
        for lib, reason in REMOVED_LIBRARIES.items():
            lines.append(f"  {lib}: {reason}")
        lines.append("")
        lines.append("ADDED:")
        for lib, desc in ADDED_LIBRARIES.items():
            lines.append(f"  {lib}: {desc}")
        lines.append("")
        lines.append("MODIFIED FUNCTIONS:")
        for func, change in MODIFIED_FUNCTIONS.items():
            lines.append(f"  {func}: {change}")
        lines.append("")
        lines.append("*/")
        return "\n".join(lines)

    def generate_bundle(self, output_path: str) -> str:
        """Generate complete Luau IR bundle"""

        self.log("Analyzing modules...")
        self.modules = self.analyze_modules()

        self.log("Extracting opcodes...")
        vm_execute = self.files.get("VM/lvmexecute.cpp", "")
        if vm_execute:
            self.opcodes = self.extract_opcodes_from_vm(vm_execute)
            self.log(f"Found {len(self.opcodes)} opcodes")

        self.log("Extracting type system...")
        self.type_info = self.extract_type_system()
        self.log(f"Found {len(self.type_info)} type definitions")

        lines = []

        # Header
        lines.append("/*" + "=" * 78 + "*/")
        lines.append("/* CALYX-LUAU BUNDLE v6.0 - Type-Aware Bytecode IR */")
        lines.append("/* Target: Luau (Roblox's Lua) - C++ Implementation */")
        lines.append("/* " + "=" * 78 + "*/")
        lines.append("")

        # Reading guide
        lines.append("/*")
        lines.append("READING GUIDE - LUAU ARCHITECTURE")
        lines.append("")
        lines.append("Luau is organized into distinct subsystems:")
        lines.append("  VM/        - Execution engine (C++)")
        lines.append("  Analysis/  - Type checking and inference")
        lines.append("  Compiler/  - Bytecode generation")
        lines.append("  AST/       - Abstract syntax tree")
        lines.append("  CodeGen/   - Native code generation (x64, ARM64)")
        lines.append("")
        lines.append("KEY CHANGES FROM LUA 5.1:")
        lines.append("  1. Written in C++ (not C)")
        lines.append("  2. Gradual type system")
        lines.append("  3. Modified bytecode with optimizations")
        lines.append("  4. Sandboxed standard library")
        lines.append("  5. Native code generation")
        lines.append("*/")
        lines.append("")

        # Opcode map
        lines.append(self.generate_opcode_map())
        lines.append("")

        # Type system
        lines.append(self.generate_type_system_doc())
        lines.append("")

        # Library changes
        lines.append(self.generate_library_changes())
        lines.append("")

        # Module organization
        lines.append("/*")
        lines.append("=" * 78)
        lines.append("MODULE ORGANIZATION")
        lines.append("=" * 78)
        lines.append("")

        # Group by category
        categories = defaultdict(list)
        for name, module in self.modules.items():
            categories[module.category].append(name)

        for category, files in sorted(categories.items()):
            lines.append(f"{category}/ ({len(files)} files)")
            for f in sorted(files)[:10]:  # Limit display
                lines.append(f"  - {f}")
            lines.append("")

        lines.append("*/")
        lines.append("")

        # Source files (headers first)
        lines.append("/*")
        lines.append("=" * 78)
        lines.append("HEADER FILES")
        lines.append("=" * 78)
        lines.append("*/")
        lines.append("")

        for name in sorted(self.headers.keys()):
            lines.append(f"/* === {name} === */")
            lines.append(self.headers[name])
            lines.append("")

        # Source files
        lines.append("/*")
        lines.append("=" * 78)
        lines.append("SOURCE FILES")
        lines.append("=" * 78)
        lines.append("*/")
        lines.append("")

        for name in sorted(self.files.keys()):
            if name not in self.headers:
                lines.append(f"/* === {name} === */")
                lines.append(self.files[name])
                lines.append("")

        # Write output
        output_path = Path(output_path)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        # Stats
        print(f"\n{'=' * 60}")
        print("CALYX-LUAU BUNDLE v6.0 COMPLETE")
        print(f"{'=' * 60}")
        print(f"Output: {output_path}")
        print(f"Size: {output_path.stat().st_size / 1024:.1f} KB")
        print(f"Files bundled: {len(self.files)}")
        print(f"Opcodes mapped: {len(self.opcodes)}")
        print(f"Type definitions: {len(self.type_info)}")
        print(f"Modules: {len(self.modules)}")
        print(f"{'=' * 60}")

        return str(output_path)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="CALYX-LUAU Bundler v6.0 - Type-Aware Bytecode IR"
    )
    parser.add_argument("--root", "-r", default=".", help="Luau source root")
    parser.add_argument(
        "--output", "-o", default="calyx_luau_v6.cpp", help="Output file"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    bundler = CalyxLuauBundlerV6(root=args.root, verbose=args.verbose)
    bundler.discover()

    if not bundler.files:
        print("Error: No source files found!")
        print(f"Checked in: {Path(args.root).resolve()}")
        import sys

        sys.exit(1)

    bundler.generate_bundle(args.output)


if __name__ == "__main__":
    main()
