#!/usr/bin/env python3
"""
CALYX-TEXTUAL BUNDLER v6.0 - Invariant-Aware Knowledge Graph for Textual TUI Framework
Adapted from CALYX-SWIFT for Python's async/message-passing reactive system
"""

import json
import re
import zlib
import ast
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import Counter, defaultdict
from enum import IntFlag

# ============================================================================
# CONFIGURATION: TEXTUAL-SPECIFIC
# ============================================================================

CORE_PROTOCOLS = {
    "Widget",
    "Screen",
    "App",
    "Message",
    "MessagePump",
    "DOMNode",
    "Binding",
    "Layout",
}

CORE_TYPES = {
    "Static",
    "Button",
    "Input",
    "Label",
    "DataTable",
    "Tree",
    "Header",
    "Footer",
    "Container",
    "Vertical",
    "Horizontal",
    "Grid",
    "ListView",
    "OptionList",
    "Select",
    "Switch",
    "Checkbox",
    "RadioButton",
    "ProgressBar",
    "Sparkline",
    "LoadingIndicator",
}

HIGH_PRIORITY = {
    "widget.py",
    "app.py",
    "screen.py",
    "reactive.py",
    "message.py",
    "dom.py",
    "events.py",
    "message_pump.py",
    "compose.py",
}

LOW_PRIORITY_PATTERNS = {
    "tests/",
    "test_",
    "_test",
    "benchmark",
    "demo/",
    "drivers/",
    "_debug",
}

# ============================================================================
# V6: PLACEMENT CONSTRAINTS (Python Context)
# ============================================================================


class ScopeConstraint(IntFlag):
    """Bitmask for legal declaration contexts in Python/Textual"""

    NONE = 0
    CLASS = 1 << 0  # Inside a class
    MODULE = 1 << 1  # Module-level
    FUNCTION = 1 << 2  # Inside a function
    ASYNC_FUNCTION = 1 << 3  # Inside async def
    WIDGET_CLASS = 1 << 4  # Widget subclass
    APP_CLASS = 1 << 5  # App subclass
    SCREEN_CLASS = 1 << 6  # Screen subclass
    MESSAGE_CLASS = 1 << 7  # Message subclass
    PROPERTY = 1 << 8  # As a property
    DESCRIPTOR = 1 << 9  # As a descriptor (reactive)

    # Composite constraints
    ANY_CLASS = CLASS | WIDGET_CLASS | APP_CLASS | SCREEN_CLASS
    REACTIVE_CONTEXT = WIDGET_CLASS | APP_CLASS | SCREEN_CLASS
    MESSAGE_HANDLER = ASYNC_FUNCTION | WIDGET_CLASS


# Reactive descriptor placement rules
REACTIVE_DESCRIPTOR_RULES = {
    "reactive": {
        "allowed_in": ScopeConstraint.REACTIVE_CONTEXT,
        "forbidden_in": ScopeConstraint.FUNCTION | ScopeConstraint.MODULE,
        "requires": ["class_attribute"],
        "triggers": ["watch_method", "validate_method", "compute_method"],
        "pattern": r"^\s*\w+\s*=\s*reactive\(",
    },
    "var": {
        "allowed_in": ScopeConstraint.REACTIVE_CONTEXT,
        "forbidden_in": ScopeConstraint.FUNCTION,
        "triggers": ["watch_method"],
        "pattern": r"^\s*\w+\s*=\s*var\(",
    },
}

# Decorator placement rules
DECORATOR_RULES = {
    "on": {
        "allowed_in": ScopeConstraint.MESSAGE_HANDLER,
        "forbidden_in": ScopeConstraint.MODULE,
        "requires": ["async_method"],
        "triggers": ["message_dispatch"],
        "pattern": r"@on\([\w.]+\)",
    },
    "work": {
        "allowed_in": ScopeConstraint.CLASS,
        "forbidden_in": ScopeConstraint.MODULE,
        "triggers": ["worker_creation"],
        "pattern": r"@work\b",
    },
}

# ============================================================================
# V6: INVARIANTS TABLE (Textual Semantic Rules)
# ============================================================================

PROTOCOL_INVARIANTS = {
    "Widget": {
        "required_methods": [],  # compose is optional, render is optional
        "optional_methods": ["compose", "render", "on_mount", "on_unmount"],
        "method_constraints": {
            "compose": {
                "must_yield": "Widget | ComposeResult",
                "can_be_generator": True,
            },
            "render": {
                "must_return": "RenderableType | str",
            },
            "on_mount": {
                "must_be_async": True,
            },
        },
        "reactive_effects": {
            "reactive": "triggers_watch",
            "var": "triggers_watch",
        },
        "css_bindable": True,
    },
    "App": {
        "required_methods": [],
        "optional_methods": ["compose", "on_mount", "on_ready"],
        "css_property": "CSS",
        "css_path_property": "CSS_PATH",
        "main_entry_point": True,
    },
    "Screen": {
        "required_methods": [],
        "optional_methods": ["compose", "on_mount"],
        "bindings_property": "BINDINGS",
        "can_stack": True,
    },
    "Message": {
        "required_properties": [],
        "optional_properties": ["bubble", "verbose"],
        "event_bubbling": True,
        "can_prevent_default": True,
    },
    "MessagePump": {
        "required_methods": ["post_message"],
        "message_queue": True,
        "async_message_handlers": True,
    },
    "DOMNode": {
        "required_properties": ["children", "id", "classes"],
        "tree_structure": True,
        "css_cascade": True,
    },
    "Binding": {
        "required_properties": ["key", "action"],
        "optional_properties": ["description", "show", "priority"],
    },
    "Layout": {
        "required_methods": ["arrange"],
        "optional_methods": ["get_content_width", "get_content_height"],
    },
}

# ============================================================================
# V6: REACTIVE EDGE MODELING (Message Passing)
# ============================================================================


class ReactiveNodeType(IntFlag):
    """Classification for reactive graph nodes in Textual"""

    SOURCE = 1 << 0  # Produces values (reactive, var)
    SINK = 1 << 1  # Consumes values (watch_, compose, render)
    HANDLER = 1 << 2  # Handles messages (@on, on_*)
    EMITTER = 1 << 3  # Emits messages (post_message)
    TRANSFORMER = 1 << 4  # Transforms data (compute_)
    OBSERVER = 1 << 5  # Observes without side effects


# Message-passing reactive edges
REACTIVE_EDGES = [
    # Reactive source → watch sink edges
    ("reactive", "watch_", "triggers_watcher"),
    ("var", "watch_", "triggers_watcher"),
    ("reactive", "compute_", "triggers_compute"),
    # Message emission → handler edges
    ("post_message", "on_", "message_dispatch"),
    ("post_message", "@on", "decorator_dispatch"),
    # DOM tree edges
    ("mount", "compose", "dom_construction"),
    ("mount", "on_mount", "lifecycle_callback"),
    ("remove", "on_unmount", "lifecycle_callback"),
    # CSS reactive edges
    ("css", "refresh", "style_recompute"),
    ("classes", "refresh", "style_recompute"),
    # Worker edges
    ("@work", "worker", "async_task_creation"),
    # Timer edges
    ("set_timer", "timer_callback", "scheduled_callback"),
    ("set_interval", "timer_callback", "scheduled_callback"),
]

# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class ReactiveInfo:
    """Extended info for reactive descriptors with constraints"""

    name: str
    constraint: int  # ScopeConstraint bitmask
    triggers: List[str] = field(default_factory=list)
    requires: List[str] = field(default_factory=list)
    pattern: str = ""


@dataclass
class ModuleV6:
    pri: int
    size: int
    exports: List[int]  # symbol IDs
    imports: List[int]  # string IDs
    scope_constraints: Dict[int, int] = field(
        default_factory=dict
    )  # symbol ID -> constraint
    reactive_role: int = ReactiveNodeType.HANDLER  # default to handler
    protocol_invariants: Dict[int, List[str]] = field(
        default_factory=dict
    )  # symbol ID -> invariants
    src: Optional[str] = None


# ============================================================================
# MAIN BUNDLER CLASS
# ============================================================================


class CalyxTextualBundlerV6:
    def __init__(self, root: str = ".", max_lines: int = 50000):
        self.root = Path(root)
        self.max_lines = max_lines

        # Intern tables
        self.strs: List[str] = []
        self.str_id: Dict[str, int] = {}

        self.syms: List[str] = []
        self.sym_id: Dict[str, int] = {}

        # Reactive descriptor registry
        self.reactive_info: Dict[str, ReactiveInfo] = {}
        self._init_reactive_descriptors()

        self.modules: List[ModuleV6] = []
        self.sym_to_mods: Dict[int, List[int]] = defaultdict(list)

        self.stats = {"c": 0, "h": 0, "n": 0, "l": 0, "s": 0, "lines": 0}

        # V6: Invariants storage
        self.invariants: Dict[str, Dict] = PROTOCOL_INVARIANTS.copy()
        self.reactive_edges = REACTIVE_EDGES

    def _init_reactive_descriptors(self):
        """Initialize reactive descriptor rules"""
        for name, rules in REACTIVE_DESCRIPTOR_RULES.items():
            self.reactive_info[name] = ReactiveInfo(
                name=name,
                constraint=rules.get("allowed_in", ScopeConstraint.NONE),
                triggers=rules.get("triggers", []),
                requires=rules.get("requires", []),
                pattern=rules.get("pattern", ""),
            )
            self.intern_sym(name)

        for name, rules in DECORATOR_RULES.items():
            self.reactive_info[name] = ReactiveInfo(
                name=name,
                constraint=rules.get("allowed_in", ScopeConstraint.NONE),
                triggers=rules.get("triggers", []),
                requires=rules.get("requires", []),
                pattern=rules.get("pattern", ""),
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
        """
        V6: Python-aware minification preserving indentation
        """
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
            if line.strip():  # Keep lines with content
                lines.append(line)

        return "\n".join(lines)

    def extract_scope_constraints(
        self, src: str, exports: List[Tuple[str, str]]
    ) -> Dict[int, int]:
        """
        V6: Extract placement constraints for reactive descriptors
        """
        constraints = {}
        context = self._detect_python_context(src)

        for export_name, export_type in exports:
            if export_name in self.reactive_info:
                sym_id = self.sym_id[export_name]
                constraints[sym_id] = context

        return constraints

    def _detect_python_context(self, src: str) -> int:
        """Detect Python context (class, async, etc.)"""
        context = ScopeConstraint.NONE

        # Parse with AST for accurate detection
        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    context |= ScopeConstraint.CLASS
                    # Check for Widget/App/Screen/Message subclass
                    for base in node.bases:
                        if isinstance(base, ast.Name):
                            if base.id == "Widget":
                                context |= ScopeConstraint.WIDGET_CLASS
                            elif base.id == "App":
                                context |= ScopeConstraint.APP_CLASS
                            elif base.id == "Screen":
                                context |= ScopeConstraint.SCREEN_CLASS
                            elif base.id == "Message":
                                context |= ScopeConstraint.MESSAGE_CLASS

                elif isinstance(node, ast.AsyncFunctionDef):
                    context |= ScopeConstraint.ASYNC_FUNCTION
                elif isinstance(node, ast.FunctionDef):
                    context |= ScopeConstraint.FUNCTION
        except SyntaxError:
            # Fallback to regex if AST fails
            if re.search(r"^\s*class\s+\w+", src, re.MULTILINE):
                context |= ScopeConstraint.CLASS
            if re.search(r"class\s+\w+.*Widget", src):
                context |= ScopeConstraint.WIDGET_CLASS
            if re.search(r"class\s+\w+.*App", src):
                context |= ScopeConstraint.APP_CLASS

        return context

    def extract_protocol_invariants(
        self, src: str, exports: List[Tuple[str, str]]
    ) -> Dict[int, List[str]]:
        """
        V6: Extract protocol conformance invariants
        """
        invariants = {}

        for export_name, export_type in exports:
            if export_name in self.invariants:
                # Check if this class inherits from the protocol
                pattern = rf"class\s+\w+.*{export_name}"
                if re.search(pattern, src):
                    inv_list = []
                    protocol_data = self.invariants[export_name]

                    if "required_methods" in protocol_data:
                        inv_list.extend(protocol_data["required_methods"])
                    if "optional_methods" in protocol_data:
                        inv_list.extend(
                            [f"optional:{m}" for m in protocol_data["optional_methods"]]
                        )
                    if "method_constraints" in protocol_data:
                        for method, constraints in protocol_data[
                            "method_constraints"
                        ].items():
                            inv_list.append(f"{method}:{constraints}")

                    if inv_list:
                        sym_id = self.sym_id.get(export_name)
                        if sym_id is not None:
                            invariants[sym_id] = inv_list

        return invariants

    def extract_reactive_role(self, src: str, exports: List[Tuple[str, str]]) -> int:
        """
        V6: Determine reactive role (source/sink/handler/emitter)
        """
        role = ReactiveNodeType.HANDLER  # Default

        # Check for reactive descriptors (sources)
        if re.search(r"\w+\s*=\s*reactive\(", src):
            role |= ReactiveNodeType.SOURCE
        if re.search(r"\w+\s*=\s*var\(", src):
            role |= ReactiveNodeType.SOURCE

        # Check for watch methods (sinks)
        if re.search(r"def\s+watch_\w+", src):
            role |= ReactiveNodeType.SINK
        if re.search(r"def\s+compute_\w+", src):
            role |= ReactiveNodeType.TRANSFORMER

        # Check for message handlers
        if re.search(r"@on\(", src):
            role |= ReactiveNodeType.HANDLER
        if re.search(r"def\s+on_\w+", src):
            role |= ReactiveNodeType.HANDLER

        # Check for message emission (emitters)
        if re.search(r"\.post_message\(", src):
            role |= ReactiveNodeType.EMITTER

        # Check for compose/render (sinks)
        if re.search(r"def\s+compose\(", src):
            role |= ReactiveNodeType.SINK
        if re.search(r"def\s+render\(", src):
            role |= ReactiveNodeType.SINK

        return role

    def extract_exports_v6(self, src: str) -> List[Tuple[str, str]]:
        """
        V6: Extract exports with their declaration type using AST
        """
        exports = []

        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    exports.append((node.name, "class"))
                elif isinstance(node, ast.FunctionDef):
                    # Only top-level functions
                    if isinstance(getattr(node, "parent", None), ast.Module):
                        exports.append((node.name, "function"))
                elif isinstance(node, ast.AsyncFunctionDef):
                    if isinstance(getattr(node, "parent", None), ast.Module):
                        exports.append((node.name, "async_function"))
        except SyntaxError:
            # Fallback to regex
            patterns = [
                (r"^\s*class\s+(\w+)", "class"),
                (r"^\s*def\s+(\w+)", "function"),
                (r"^\s*async\s+def\s+(\w+)", "async_function"),
            ]

            for pattern, decl_type in patterns:
                matches = re.findall(pattern, src, re.MULTILINE)
                for match in matches[:20]:  # Limit per type
                    exports.append((match, decl_type))

        return exports

    def extract_imports_v6(self, src: str) -> List[int]:
        """Extract imports including from-imports"""
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

        # Check for core protocols
        for proto in CORE_PROTOCOLS:
            if re.search(rf"class\s+{proto}\b", src):
                return 1

        # Check for core types
        for typ in CORE_TYPES:
            if re.search(rf"class\s+{typ}\(", src):
                return 2

        # High export count = important
        if src.count("class ") + src.count("def ") > 10:
            return 2

        # Low priority patterns
        for pat in LOW_PRIORITY_PATTERNS:
            if pat.lower() in p.lower():
                return 4

        return 3

    def analyze(self, path: Path) -> Optional[ModuleV6]:
        try:
            rel = path.relative_to(self.root)
        except ValueError:
            return None

        # Skip tests and demos
        if "tests" in rel.parts or "test_" in path.name:
            return None

        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                src = f.read()
        except Exception:
            return None

        lines = len(src.split("\n"))
        pri = self.priority(rel, src)

        # Early skip for low priority when near limit
        if pri >= 4 and self.stats["lines"] > self.max_lines * 0.5:
            self.stats["s"] += 1
            return None

        exports = self.extract_exports_v6(src)
        exp_ids = []

        # Register exports
        mod_idx = len(self.modules)
        for exp_name, exp_type in exports:
            sym_id = self.intern_sym(exp_name)
            exp_ids.append(sym_id)
            self.sym_to_mods[sym_id].append(mod_idx)

        self.stats["lines"] += lines
        self.stats[
            "c" if pri == 1 else "h" if pri == 2 else "n" if pri == 3 else "l"
        ] += 1

        # V6: Extract constraints and invariants
        scope_constraints = self.extract_scope_constraints(src, exports)
        protocol_invariants = self.extract_protocol_invariants(src, exports)
        reactive_role = self.extract_reactive_role(src, exports)

        return ModuleV6(
            pri=pri,
            size=lines,
            exports=exp_ids,
            imports=self.extract_imports_v6(src),
            scope_constraints=scope_constraints,
            reactive_role=reactive_role,
            protocol_invariants=protocol_invariants,
            src=self.minify_python(src) if pri <= 2 else None,
        )

    def discover(self):
        all_mods = []

        # Find all Python files in src
        src_dir = self.root / "src" / "textual"
        if not src_dir.exists():
            src_dir = self.root / "textual"
        if not src_dir.exists():
            src_dir = self.root

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

    def build_graph_v6(self) -> Tuple[List, List, Dict]:
        """
        V6: Build weighted graph with reactive edge classification
        """
        weights: Dict[int, Dict[int, int]] = {i: {} for i in range(len(self.modules))}
        reactive_graph: Dict[int, Dict[int, List[str]]] = {
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

                            # V6: Classify reactive edges
                            if token in self.reactive_info:
                                triggers = self.reactive_info[token].triggers
                                reactive_graph[mid][dep] = (
                                    reactive_graph[mid].get(dep, []) + triggers
                                )

        # Bucket weights
        def bucket_weight(w: int) -> int:
            return 3 if w >= 10 else 2 if w >= 5 else 1

        wdg = [
            (f, [(t, bucket_weight(w)) for t, w in deps.items()])
            for f, deps in weights.items()
            if deps
        ]
        dg = [(f, [t for t, _ in deps]) for f, deps in wdg]

        return wdg, dg, reactive_graph

    def generate(self, output: str):
        wdg, dg, reactive_graph = self.build_graph_v6()

        # V6: Build enhanced module map
        mods = []
        for m in self.modules:
            mod_entry = (
                m.pri,
                m.size,
                m.exports,
                m.imports,
                m.scope_constraints,
                m.reactive_role,
                m.protocol_invariants,
            )
            mods.append(mod_entry)

        # V6: Build invariants table
        invariants_table = {}
        for proto_name, proto_data in self.invariants.items():
            proto_id = self.sym_id.get(proto_name)
            if proto_id is not None:
                invariants_table[proto_id] = proto_data

        # V6: Build reactive descriptor rules table
        reactive_rules = {}
        for reactive_name, reactive_info in self.reactive_info.items():
            reactive_id = self.sym_id.get(reactive_name)
            if reactive_id is not None:
                reactive_rules[reactive_id] = {
                    "constraint": int(reactive_info.constraint),
                    "triggers": reactive_info.triggers,
                    "requires": reactive_info.requires,
                    "pattern": reactive_info.pattern,
                }

        bundle = {
            "V": 6,  # Version 6 - Invariant-Aware (Textual)
            "F": "textual",  # Framework
            "S": self.strs,
            "Y": self.syms,
            "M": mods,
            "W": wdg,
            "D": dg,
            "C": {i: m.src for i, m in enumerate(self.modules) if m.src},
            "I": invariants_table,  # V6: Protocol invariants
            "P": reactive_rules,  # V6: Reactive descriptor placement rules
            "R": reactive_graph,  # V6: Reactive edge graph
            "t": {
                "f": len(self.modules),
                "l": self.stats["lines"],
                **{k: self.stats[k] for k in ["c", "h", "n", "l", "s"]},
                "version": 6,
                "framework": "textual",
                "invariants": len(invariants_table),
                "reactive_rules": len(reactive_rules),
            },
        }

        json_str = json.dumps(bundle, separators=(",", ":"))
        out = self.root / output
        out.write_text(json_str)

        raw = len(json_str)
        comp = len(zlib.compress(json_str.encode(), 9))

        print(f"\n{'=' * 50}")
        print(
            f"CALYX-TEXTUAL v6.0: {len(self.modules)} modules, {self.stats['lines']} lines"
        )
        print(f"Symbols: {len(self.syms)} | Strings: {len(self.strs)}")
        print(
            f"Invariants: {len(invariants_table)} | Reactive Rules: {len(reactive_rules)}"
        )
        print(
            f"Raw: {raw / 1024:.1f} KB | Compressed: {comp / 1024:.1f} KB ({comp / raw * 100:.1f}%)"
        )
        print(f"{'=' * 50}")


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--root", default="/tmp/textual")
    p.add_argument("--output", default="calyx_textual_v6.json")
    p.add_argument("--max-lines", type=int, default=50000)
    args = p.parse_args()

    b = CalyxTextualBundlerV6(args.root, args.max_lines)
    b.discover()
    b.generate(args.output)


if __name__ == "__main__":
    main()
