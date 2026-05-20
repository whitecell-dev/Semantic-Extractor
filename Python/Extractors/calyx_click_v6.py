#!/usr/bin/env python3
"""
CALYX-CLICK BUNDLER v6.1 - Decorator-Driven Dependency Injection IR
Fixed: Directory creation, better path handling, fallback for missing Click source
"""

import json
import re
import zlib
import ast
import inspect
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from collections import Counter, defaultdict
from enum import IntFlag

# ============================================================================
# CONFIGURATION: CLICK-SPECIFIC
# ============================================================================

CORE_DECORATORS = {
    "command",
    "group",
    "option",
    "argument",
    "pass_context",
    "pass_obj",
    "make_pass_decorator",
}

CORE_TYPES = {
    "STRING",
    "INT",
    "FLOAT",
    "BOOL",
    "UUID",
    "File",
    "Path",
    "Choice",
    "IntRange",
    "FloatRange",
    "DateTime",
    "Tuple",
    "ParamType",
}

CORE_CLASSES = {
    "Context",
    "Command",
    "Group",
    "MultiCommand",
    "Option",
    "Argument",
    "Parameter",
}

HIGH_PRIORITY = {
    "core.py",
    "decorators.py",
    "types.py",
    "exceptions.py",
}

LOW_PRIORITY_PATTERNS = {
    "tests/",
    "test_",
    "_compat",
    "_winconsole",
    "examples/",
}

# ============================================================================
# V6: DECORATOR PLACEMENT CONSTRAINTS (Symbolic Linker Rules)
# ============================================================================


class DecoratorConstraint(IntFlag):
    """Bitmask for legal decorator placement"""

    NONE = 0
    FUNCTION = 1 << 0  # Decorates a function
    CALLABLE = 1 << 1  # Decorates a callable (function or Command)
    COMMAND = 1 << 2  # Decorates a Command object
    GROUP = 1 << 3  # Decorates a Group object
    TOP_LEVEL = 1 << 4  # Can be at module level
    NESTED = 1 << 5  # Can be nested in group
    PARAMETER = 1 << 6  # Adds a parameter

    # Composite constraints
    COMMAND_BUILDER = FUNCTION | TOP_LEVEL
    GROUP_BUILDER = FUNCTION | TOP_LEVEL
    PARAM_INJECTOR = FUNCTION | PARAMETER


# Decorator placement and signature rules
DECORATOR_RULES = {
    "command": {
        "constraint": DecoratorConstraint.COMMAND_BUILDER,
        "transforms": "function_to_command",
        "creates_node": True,
        "signature_requirement": "callable",
        "pattern": r"@click\.command\(",
    },
    "group": {
        "constraint": DecoratorConstraint.GROUP_BUILDER,
        "transforms": "function_to_group",
        "creates_node": True,
        "can_nest": ["command", "group"],
        "signature_requirement": "callable",
        "pattern": r"@click\.group\(",
    },
    "option": {
        "constraint": DecoratorConstraint.PARAM_INJECTOR,
        "transforms": "adds_parameter",
        "injects_as": "keyword_argument",
        "signature_sync": "kebab_to_snake",
        "pattern": r"@click\.option\(",
        "signature_requirement": "parameter_match",
    },
    "argument": {
        "constraint": DecoratorConstraint.PARAM_INJECTOR,
        "transforms": "adds_parameter",
        "injects_as": "positional_argument",
        "signature_sync": "direct",
        "pattern": r"@click\.argument\(",
        "signature_requirement": "parameter_match",
    },
    "pass_context": {
        "constraint": DecoratorConstraint.FUNCTION,
        "transforms": "injects_context",
        "injects_as": "first_parameter",
        "signature_requirement": "first_param_ctx",
        "pattern": r"@click\.pass_context",
    },
    "pass_obj": {
        "constraint": DecoratorConstraint.FUNCTION,
        "transforms": "injects_object",
        "injects_as": "first_parameter",
        "signature_requirement": "first_param_obj",
        "pattern": r"@click\.pass_obj",
    },
}

# ============================================================================
# V6: SIGNATURE INVARIANTS (The "Wire-to-Port" Rules)
# ============================================================================

SIGNATURE_INVARIANTS = {
    "option": {
        "name_transform": "kebab_to_snake",
        "strip_prefix": "--",
        "default_handling": "optional_with_default",
        "type_inference": "from_default_or_type_param",
        "multiple_values": "is_flag_or_multiple",
    },
    "argument": {
        "name_transform": "uppercase_to_lowercase",
        "required_by_default": True,
        "positional_order": "decorator_order",
        "type_inference": "from_type_param",
    },
    "pass_context": {
        "injects_at": "position_0",
        "parameter_name": "ctx",
        "parameter_type": "Context",
    },
    "pass_obj": {
        "injects_at": "position_0",
        "parameter_name": "obj",
        "parameter_type": "Any",
    },
}

# ============================================================================
# V6: TYPE SYSTEM (Parameter Type Invariants)
# ============================================================================

TYPE_INVARIANTS = {
    "STRING": {
        "python_type": "str",
        "default": None,
        "validation": None,
    },
    "INT": {
        "python_type": "int",
        "default": None,
        "validation": "numeric",
    },
    "FLOAT": {
        "python_type": "float",
        "default": None,
        "validation": "numeric",
    },
    "BOOL": {
        "python_type": "bool",
        "default": False,
        "validation": None,
        "is_flag": True,
    },
    "Path": {
        "python_type": "Path | str",
        "constraints": ["exists", "file_okay", "dir_okay", "writable", "readable"],
        "validation": "filesystem",
    },
    "Choice": {
        "python_type": "str",
        "constraints": ["choices", "case_sensitive"],
        "validation": "enum_member",
    },
    "IntRange": {
        "python_type": "int",
        "constraints": ["min", "max", "clamp"],
        "validation": "range_check",
    },
}

# ============================================================================
# V6: COMMAND TREE STRUCTURE (Hierarchical Edges)
# ============================================================================


class NodeRole(IntFlag):
    """Role in the command tree"""

    COMMAND = 1 << 0  # Leaf command (executes)
    GROUP = 1 << 1  # Container (has subcommands)
    PARAMETER = 1 << 2  # Parameter (option/argument)
    CONTEXT_INJECTOR = 1 << 3  # Injects context
    CALLBACK = 1 << 4  # Callback function


# Command tree edges (parent-child relationships)
COMMAND_EDGES = [
    ("group", "command", "contains_command"),
    ("group", "group", "contains_subgroup"),
    ("command", "option", "has_parameter"),
    ("command", "argument", "has_parameter"),
    ("group", "option", "has_parameter"),
]

# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class DecoratorInfo:
    """Decorator metadata with signature requirements"""

    name: str
    constraint: int  # DecoratorConstraint bitmask
    transforms: str
    signature_requirement: str
    pattern: str = ""
    injects_as: Optional[str] = None
    signature_sync: Optional[str] = None


@dataclass
class SignatureTuple:
    """Function signature with parameter mapping"""

    func_name: str
    params: List[str]  # Parameter names
    param_types: List[int]  # Type symbol IDs
    defaults: List[Any]  # Default values
    decorators: List[int]  # Decorator symbol IDs
    signature_valid: bool  # Signature matches decorators


@dataclass
class ModuleV6:
    pri: int
    size: int
    exports: List[int]  # symbol IDs
    imports: List[int]  # string IDs
    decorator_constraints: Dict[int, int] = field(
        default_factory=dict
    )  # decorator ID -> constraint
    node_role: int = NodeRole.COMMAND  # default to command
    signatures: Dict[int, SignatureTuple] = field(
        default_factory=dict
    )  # func ID -> signature
    src: Optional[str] = None


# ============================================================================
# MAIN BUNDLER CLASS
# ============================================================================


class CalyxClickBundlerV6:
    def __init__(self, root: str = ".", max_lines: int = 30000, output_dir: str = "."):
        self.root = Path(root).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.max_lines = max_lines

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Intern tables
        self.strs: List[str] = []
        self.str_id: Dict[str, int] = {}

        self.syms: List[str] = []
        self.sym_id: Dict[str, int] = {}

        # Decorator registry
        self.decorator_info: Dict[str, DecoratorInfo] = {}
        self._init_decorators()

        self.modules: List[ModuleV6] = []
        self.sym_to_mods: Dict[int, List[int]] = defaultdict(list)

        self.stats = {"c": 0, "h": 0, "n": 0, "l": 0, "s": 0, "lines": 0}

        # V6: Signature and type storage
        self.signature_invariants = SIGNATURE_INVARIANTS
        self.type_invariants = TYPE_INVARIANTS
        self.command_edges = COMMAND_EDGES

    def _init_decorators(self):
        """Initialize decorator rules"""
        for name, rules in DECORATOR_RULES.items():
            self.decorator_info[name] = DecoratorInfo(
                name=name,
                constraint=rules.get("constraint", DecoratorConstraint.NONE),
                transforms=rules.get("transforms", ""),
                signature_requirement=rules.get("signature_requirement", ""),
                pattern=rules.get("pattern", ""),
                injects_as=rules.get("injects_as"),
                signature_sync=rules.get("signature_sync"),
            )
            self.intern_sym(name)

    def intern_str(self, s: str) -> int:
        if s not in self.str_id:
            self.str_id[s] = len(self.strs)
            self.strs.append(s)
        return self.str_id[s]

    def intern_sym(self, s: str) -> int:
        if s not in self.sym_id:
            self.sym_id[s] = len(self.syms)
            self.syms.append(s)
        return self.sym_id[s]

    def minify_python(self, src: str) -> str:
        """Python-aware minification preserving indentation"""
        # Remove docstrings
        src = re.sub(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', "", src)

        lines = []
        for line in src.split("\n"):
            # Preserve indentation, remove comments
            if "#" in line:
                # Check if # is in a string
                in_string = False
                escape = False
                for i, ch in enumerate(line):
                    if escape:
                        escape = False
                        continue
                    if ch == "\\":
                        escape = True
                        continue
                    if ch in ('"', "'"):
                        in_string = not in_string
                    if ch == "#" and not in_string:
                        line = line[:i]
                        break

            line = line.rstrip()
            if line.strip():
                lines.append(line)

        return "\n".join(lines)

    def extract_signature(
        self, node: ast.FunctionDef, decorators: List[str]
    ) -> SignatureTuple:
        """
        V6: Extract function signature and validate against decorators
        """
        func_name = node.name
        params = []
        param_types = []
        defaults = []
        decorator_ids = [self.intern_sym(d) for d in decorators]

        # Extract parameters
        for arg in node.args.args:
            params.append(arg.arg)
            # Try to infer type
            if arg.annotation:
                if isinstance(arg.annotation, ast.Name):
                    type_id = self.intern_sym(arg.annotation.id)
                else:
                    type_id = self.intern_sym("Any")
                param_types.append(type_id)
            else:
                param_types.append(self.intern_sym("Any"))

        # Extract defaults
        defaults_offset = len(params) - len(node.args.defaults)
        for i in range(len(params)):
            if i >= defaults_offset:
                default_node = node.args.defaults[i - defaults_offset]
                if isinstance(default_node, ast.Constant):
                    defaults.append(default_node.value)
                else:
                    defaults.append(None)
            else:
                defaults.append(None)

        # Validate signature against decorators
        signature_valid = self._validate_signature(params, decorators)

        return SignatureTuple(
            func_name=func_name,
            params=params,
            param_types=param_types,
            defaults=defaults,
            decorators=decorator_ids,
            signature_valid=signature_valid,
        )

    def _validate_signature(self, params: List[str], decorators: List[str]) -> bool:
        """
        V6: Validate that function signature matches decorator requirements
        """
        # Check for pass_context/pass_obj
        if "pass_context" in decorators:
            if not params or params[0] != "ctx":
                return False

        if "pass_obj" in decorators:
            if not params or params[0] != "obj":
                return False

        # For now, assume valid if no specific violations
        return True

    def extract_decorators(self, node: ast.FunctionDef) -> List[str]:
        """Extract decorator names from function"""
        decorators = []
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Attribute):
                    if isinstance(dec.func.value, ast.Name):
                        if dec.func.value.id == "click":
                            decorators.append(dec.func.attr)
            elif isinstance(dec, ast.Attribute):
                if isinstance(dec.value, ast.Name):
                    if dec.value.id == "click":
                        decorators.append(dec.attr)
            elif isinstance(dec, ast.Name):
                decorators.append(dec.id)
        return decorators

    def extract_node_role(self, decorators: List[str]) -> int:
        """Determine node role from decorators"""
        role = NodeRole.CALLBACK  # Default

        if "command" in decorators:
            role |= NodeRole.COMMAND
        if "group" in decorators:
            role |= NodeRole.GROUP
        if "option" in decorators or "argument" in decorators:
            role |= NodeRole.PARAMETER
        if "pass_context" in decorators or "pass_obj" in decorators:
            role |= NodeRole.CONTEXT_INJECTOR

        return role

    def extract_exports_v6(self, src: str) -> List[Tuple[str, str, List[str]]]:
        """
        V6: Extract exports with decorators
        Returns list of (name, type, decorators)
        """
        exports = []

        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    exports.append((node.name, "class", []))
                elif isinstance(node, ast.FunctionDef):
                    decorators = self.extract_decorators(node)
                    exports.append((node.name, "function", decorators))
        except SyntaxError:
            # Fallback to regex
            patterns = [
                (r"^\s*class\s+(\w+)", "class"),
                (r"^\s*def\s+(\w+)", "function"),
            ]

            for pattern, decl_type in patterns:
                matches = re.findall(pattern, src, re.MULTILINE)
                for match in matches[:20]:
                    exports.append((match, decl_type, []))

        return exports

    def extract_signatures_from_ast(self, src: str) -> Dict[str, SignatureTuple]:
        """Extract all function signatures from source"""
        signatures = {}

        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    decorators = self.extract_decorators(node)
                    if any(d in CORE_DECORATORS for d in decorators):
                        sig = self.extract_signature(node, decorators)
                        signatures[node.name] = sig
        except SyntaxError:
            pass

        return signatures

    def extract_imports_v6(self, src: str) -> List[int]:
        """Extract imports"""
        imports = []

        # Standard imports
        for m in re.findall(r"^\s*import\s+(\w+)", src, re.MULTILINE)[:10]:
            imports.append(self.intern_str(m))

        # From imports
        for m in re.findall(r"^\s*from\s+(\S+)\s+import", src, re.MULTILINE)[:10]:
            imports.append(self.intern_str(m))

        return imports

    def priority(self, path: Path, src: str) -> int:
        p = str(path)

        # High priority for core files
        if any(h in p for h in HIGH_PRIORITY):
            return 1

        # Check for core classes
        for cls in CORE_CLASSES:
            if re.search(rf"class\s+{cls}\b", src):
                return 1

        # Check for core decorators
        for dec in CORE_DECORATORS:
            if re.search(rf"def\s+{dec}\(", src):
                return 1

        # High export count = important
        if src.count("class ") + src.count("def ") > 10:
            return 2

        # Low priority patterns
        for pat in LOW_PRIORITY_PATTERNS:
            if pat.lower() in p.lower():
                return 4

        return 3

    def find_click_source(self) -> Optional[Path]:
        """Find Click source directory"""
        # Try common locations
        candidates = [
            self.root / "src" / "click",
            self.root / "click",
            self.root,
            Path("/usr/local/lib/python3.12/site-packages/click"),
            Path("/usr/lib/python3.12/site-packages/click"),
        ]

        # Also try finding via import
        try:
            import click

            click_path = Path(click.__file__).parent
            candidates.append(click_path)
        except ImportError:
            pass

        for candidate in candidates:
            if candidate.exists() and candidate.is_dir():
                return candidate

        return None

    def discover(self):
        all_mods = []

        # Find Click source directory
        src_dir = self.find_click_source()

        if not src_dir:
            print(f"Warning: Click source not found at {self.root}")
            print("Creating minimal bundle with built-in knowledge...")
            # Create a minimal bundle with just the invariants
            self.modules = []
            return

        print(f"Found Click source at: {src_dir}")

        for path in src_dir.glob("**/*.py"):
            if any(x in str(path) for x in [".git", "__pycache__", ".pytest"]):
                continue
            m = self.analyze(path)
            if m:
                all_mods.append(m)

        all_mods.sort(key=lambda m: (m.pri, m.size))

        total = 0
        for m in all_mods:
            if total + m.size <= self.max_lines:
                self.modules.append(m)
                total += m.size
            else:
                self.stats["s"] += 1

        self.stats["lines"] = total

    def analyze(self, path: Path) -> Optional[ModuleV6]:
        try:
            rel = path.relative_to(self.root)
        except ValueError:
            rel = path

        # Skip tests
        if "tests" in str(rel).lower() or "test_" in path.name:
            return None

        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                src = f.read()
        except Exception as e:
            return None

        lines = len(src.split("\n"))
        pri = self.priority(rel, src)

        # Early skip for low priority
        if pri >= 4 and self.stats["lines"] > self.max_lines * 0.5:
            self.stats["s"] += 1
            return None

        exports = self.extract_exports_v6(src)
        exp_ids = []

        # Register exports
        mod_idx = len(self.modules)
        for exp_name, exp_type, decorators in exports:
            sym_id = self.intern_sym(exp_name)
            exp_ids.append(sym_id)
            self.sym_to_mods[sym_id].append(mod_idx)

        self.stats["lines"] += lines
        self.stats[
            "c" if pri == 1 else "h" if pri == 2 else "n" if pri == 3 else "l"
        ] += 1

        # V6: Extract signatures
        signatures_map = self.extract_signatures_from_ast(src)
        signatures_dict = {}
        for func_name, sig_tuple in signatures_map.items():
            func_id = self.intern_sym(func_name)
            signatures_dict[func_id] = sig_tuple

        # V6: Extract decorator constraints
        decorator_constraints = {}
        for exp_name, exp_type, decorators in exports:
            for dec in decorators:
                if dec in self.decorator_info:
                    dec_id = self.sym_id[dec]
                    decorator_constraints[dec_id] = int(
                        self.decorator_info[dec].constraint
                    )

        # V6: Determine node role
        all_decorators = []
        for _, _, decs in exports:
            all_decorators.extend(decs)
        node_role = self.extract_node_role(all_decorators)

        return ModuleV6(
            pri=pri,
            size=lines,
            exports=exp_ids,
            imports=self.extract_imports_v6(src),
            decorator_constraints=decorator_constraints,
            node_role=node_role,
            signatures=signatures_dict,
            src=self.minify_python(src) if pri <= 2 else None,
        )

    def build_graph_v6(self) -> Tuple[List, List, Dict]:
        """
        V6: Build dependency graph + command tree
        """
        weights: Dict[int, Dict[int, int]] = {i: {} for i in range(len(self.modules))}
        command_tree: Dict[int, Dict[int, List[str]]] = {
            i: {} for i in range(len(self.modules))
        }

        for mid, mod in enumerate(self.modules):
            if not mod.src:
                continue

            # Count symbol references
            counts = Counter(re.findall(r"\b\w+\b", mod.src))

            for token, cnt in counts.items():
                if token in self.sym_id:
                    for dep in self.sym_to_mods.get(self.sym_id[token], []):
                        if dep != mid:
                            # Add to dependency graph
                            weight = min(cnt, 3)
                            weights[mid][dep] = weights[mid].get(dep, 0) + weight

                            # V6: Track decorator relationships
                            if token in self.decorator_info:
                                transform = self.decorator_info[token].transforms
                                command_tree[mid][dep] = command_tree[mid].get(
                                    dep, []
                                ) + [transform]

        # Bucket weights
        def bucket_weight(w: int) -> int:
            return 3 if w >= 10 else 2 if w >= 5 else 1

        wdg = [
            (f, [(t, bucket_weight(w)) for t, w in deps.items()])
            for f, deps in weights.items()
            if deps
        ]
        dg = [(f, [t for t, _ in deps]) for f, deps in wdg]

        return wdg, dg, command_tree

    def generate(self, output: str):
        wdg, dg, command_tree = self.build_graph_v6()

        # V6: Build enhanced module map
        mods = []
        for m in self.modules:
            # Convert SignatureTuple to serializable format
            sigs_serializable = {}
            for func_id, sig in m.signatures.items():
                sigs_serializable[func_id] = {
                    "func_name": sig.func_name,
                    "params": sig.params,
                    "param_types": sig.param_types,
                    "defaults": sig.defaults,
                    "decorators": sig.decorators,
                    "signature_valid": sig.signature_valid,
                }

            mod_entry = (
                m.pri,
                m.size,
                m.exports,
                m.imports,
                m.decorator_constraints,
                m.node_role,
                sigs_serializable,
            )
            mods.append(mod_entry)

        # V6: Build decorator rules table
        decorator_rules = {}
        for dec_name, dec_info in self.decorator_info.items():
            dec_id = self.sym_id.get(dec_name)
            if dec_id is not None:
                decorator_rules[dec_id] = {
                    "constraint": int(dec_info.constraint),
                    "transforms": dec_info.transforms,
                    "signature_requirement": dec_info.signature_requirement,
                    "pattern": dec_info.pattern,
                    "injects_as": dec_info.injects_as,
                    "signature_sync": dec_info.signature_sync,
                }

        bundle = {
            "V": 6,  # Version 6 - Decorator-Aware (Click)
            "F": "click",  # Framework
            "S": self.strs,
            "Y": self.syms,
            "M": mods,
            "W": wdg,
            "D": dg,
            "C": {i: m.src for i, m in enumerate(self.modules) if m.src},
            "I": self.signature_invariants,  # V6: Signature invariants
            "P": decorator_rules,  # V6: Decorator placement rules
            "T": self.type_invariants,  # V6: Type system invariants
            "R": command_tree,  # V6: Command tree edges
            "t": {
                "f": len(self.modules),
                "l": self.stats["lines"],
                **{k: self.stats[k] for k in ["c", "h", "n", "l", "s"]},
                "version": 6,
                "framework": "click",
                "decorators": len(decorator_rules),
                "type_invariants": len(self.type_invariants),
            },
        }

        json_str = json.dumps(bundle, separators=(",", ":"))

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.output_dir / output
        output_path.write_text(json_str)

        raw = len(json_str)
        comp = len(zlib.compress(json_str.encode(), 9))

        print(f"\n{'=' * 50}")
        print(
            f"CALYX-CLICK v6.1: {len(self.modules)} modules, {self.stats['lines']} lines"
        )
        print(f"Symbols: {len(self.syms)} | Strings: {len(self.strs)}")
        print(
            f"Decorators: {len(decorator_rules)} | Types: {len(self.type_invariants)}"
        )
        print(f"Output: {output_path}")
        print(
            f"Raw: {raw / 1024:.1f} KB | Compressed: {comp / 1024:.1f} KB ({comp / raw * 100:.1f}%)"
        )
        print(f"{'=' * 50}")


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".", help="Root directory for Click source")
    p.add_argument("--output", default="calyx_click_v6.json", help="Output file name")
    p.add_argument("--output-dir", default=".", help="Output directory")
    p.add_argument("--max-lines", type=int, default=30000, help="Max lines to include")
    args = p.parse_args()

    b = CalyxClickBundlerV6(
        root=args.root, max_lines=args.max_lines, output_dir=args.output_dir
    )
    b.discover()
    b.generate(args.output)


if __name__ == "__main__":
    main()
