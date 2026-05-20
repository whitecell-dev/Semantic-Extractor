#!/usr/bin/env python3
"""
CALYX-SWIFT BUNDLER v6.0 - Invariant-Aware Knowledge Graph
Adds: Placement Bitmasks, Invariants Table, Reactive Edges, Protocol Witness Templates
"""

import json
import re
import zlib
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import Counter, defaultdict
from enum import IntFlag

# ============================================================================
# CONFIGURATION
# ============================================================================

CORE_PROTOCOLS = {
    "View",
    "ViewModifier",
    "Scene",
    "App",
    "Shape",
    "Gesture",
    "Animatable",
    "Transition",
    "Layout",
    "PreferenceKey",
}

CORE_TYPES = {
    "Color",
    "Image",
    "Text",
    "Font",
    "Button",
    "Toggle",
    "Slider",
    "ZStack",
    "HStack",
    "VStack",
    "List",
    "GeometryReader",
}

HIGH_PRIORITY = {
    "View.swift",
    "ViewModifier.swift",
    "Scene.swift",
    "App.swift",
    "Button.swift",
    "Text.swift",
    "Animation.swift",
    "Layout.swift",
    "Binding.swift",
}

LOW_PRIORITY_PATTERNS = {
    "Tests/",
    "Test",
    "Macros",
    "Benchmark",
    "Debug",
    "SPI/",
    "Private",
}

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def bucket_weight(w: int) -> int:
    """Bucket weight for graph edges - defined at module level"""
    return 3 if w >= 10 else 2 if w >= 5 else 1


# ============================================================================
# V6: PLACEMENT BITMASKS (Scope Guard)
# ============================================================================


class ScopeConstraint(IntFlag):
    """Bitmask for legal declaration contexts"""

    NONE = 0
    STRUCT = 1 << 0
    CLASS = 1 << 1
    ENUM = 1 << 2
    PROTOCOL = 1 << 3
    EXTENSION = 1 << 4
    FUNC = 1 << 5
    COMPUTED_PROP = 1 << 6  # Computed property (forbidden for @State)
    TOP_LEVEL = 1 << 7

    # Composite constraints
    VIEW_BODY = STRUCT | FUNC  # View.body is struct method
    OBSERVABLE_OBJECT = CLASS
    VIEW_STRUCT = STRUCT  # Views are structs
    ANY_TYPE = STRUCT | CLASS | ENUM | PROTOCOL

    @classmethod
    def from_declaration(cls, decl_type: str) -> "ScopeConstraint":
        """Convert Swift declaration type to constraint"""
        mapping = {
            "struct": cls.STRUCT,
            "class": cls.CLASS,
            "enum": cls.ENUM,
            "protocol": cls.PROTOCOL,
            "extension": cls.EXTENSION,
            "func": cls.FUNC,
        }
        return mapping.get(decl_type, cls.NONE)


# Property wrapper placement rules
PROPERTY_WRAPPER_RULES = {
    "State": {
        "allowed_in": ScopeConstraint.VIEW_STRUCT,
        "forbidden_in": ScopeConstraint.CLASS
        | ScopeConstraint.FUNC
        | ScopeConstraint.COMPUTED_PROP,
        "requires": ["stored_property"],
        "triggers": ["body_invalidation"],
    },
    "Binding": {
        "allowed_in": ScopeConstraint.VIEW_STRUCT,
        "forbidden_in": ScopeConstraint.CLASS | ScopeConstraint.FUNC,
        "triggers": ["body_invalidation"],
    },
    "Environment": {
        "allowed_in": ScopeConstraint.VIEW_STRUCT,
        "forbidden_in": ScopeConstraint.CLASS
        | ScopeConstraint.FUNC
        | ScopeConstraint.COMPUTED_PROP,
        "triggers": ["environment_injection"],
    },
    "EnvironmentObject": {
        "allowed_in": ScopeConstraint.VIEW_STRUCT,
        "forbidden_in": ScopeConstraint.CLASS | ScopeConstraint.FUNC,
        "triggers": ["environment_injection"],
    },
    "ObservedObject": {
        "allowed_in": ScopeConstraint.VIEW_STRUCT,
        "forbidden_in": ScopeConstraint.CLASS | ScopeConstraint.FUNC,
        "triggers": ["body_invalidation"],
    },
    "StateObject": {
        "allowed_in": ScopeConstraint.VIEW_STRUCT,
        "forbidden_in": ScopeConstraint.CLASS | ScopeConstraint.FUNC,
        "triggers": ["body_invalidation"],
    },
    "Published": {
        "allowed_in": ScopeConstraint.OBSERVABLE_OBJECT,
        "forbidden_in": ScopeConstraint.STRUCT | ScopeConstraint.FUNC,
        "requires": ["observable_object_conformance"],
        "triggers": ["object_will_change"],
    },
    "FocusState": {
        "allowed_in": ScopeConstraint.VIEW_STRUCT,
        "forbidden_in": ScopeConstraint.CLASS | ScopeConstraint.FUNC,
        "triggers": ["focus_invalidation"],
    },
    "GestureState": {
        "allowed_in": ScopeConstraint.VIEW_STRUCT,
        "forbidden_in": ScopeConstraint.CLASS | ScopeConstraint.FUNC,
        "triggers": ["gesture_update"],
    },
    "ScaledMetric": {
        "allowed_in": ScopeConstraint.VIEW_STRUCT,
        "forbidden_in": ScopeConstraint.CLASS | ScopeConstraint.FUNC,
        "triggers": ["dynamic_type_update"],
    },
    "AppStorage": {
        "allowed_in": ScopeConstraint.VIEW_STRUCT,
        "forbidden_in": ScopeConstraint.CLASS | ScopeConstraint.FUNC,
        "triggers": ["user_defaults_sync"],
    },
}

# ============================================================================
# V6: INVARIANTS TABLE (Semantic Rules)
# ============================================================================

PROTOCOL_INVARIANTS = {
    "View": {
        "required_methods": ["body"],
        "body_requirements": {
            "must_return": "some View",
            "must_be_computed": True,
        },
        "property_wrapper_effects": {
            "@State": "triggers_body",
            "@Binding": "triggers_body",
            "@ObservedObject": "triggers_body",
        },
    },
    "Layout": {
        "required_methods": ["sizeThatFits", "placeSubviews"],
        "method_constraints": {
            "sizeThatFits": {
                "must_return": "CGSize",
                "parameters": ["proposal", "subviews", "cache"],
            },
            "placeSubviews": {
                "must_call": ["subview.place"],
                "must_affect": ["all_subviews"],
            },
        },
        "optional_methods": [
            "spacing",
            "explicitAlignment",
            "makeCache",
            "updateCache",
        ],
    },
    "Animatable": {
        "required_properties": ["animatableData"],
        "animatableData_must_be": "VectorArithmetic",
    },
    "ObservableObject": {
        "implicit_behaviors": ["objectWillChange_automatic"],
        "property_effects": {"@Published": "triggers_objectWillChange"},
        "forbidden_patterns": ["manual_objectWillChange_send"],
    },
    "PreferenceKey": {
        "required_properties": ["defaultValue"],
        "required_methods": ["reduce"],
        "reduce_must_be": "associative",
    },
    "Shape": {
        "required_methods": ["path"],
        "optional_methods": ["sizeThatFits", "layoutDirectionBehavior"],
    },
    "Transition": {
        "required_methods": ["body"],
        "body_must_handle": ["phase"],
    },
    "Scene": {
        "required_properties": ["body"],
        "body_must_return": "some Scene",
    },
    "App": {
        "required_properties": ["body"],
        "body_must_return": "some Scene",
        "main_entry_point": True,
    },
    "Gesture": {
        "required_properties": ["body"],
        "associated_types": ["Value"],
    },
}

# ============================================================================
# V6: REACTIVE EDGE MODELING
# ============================================================================


class ReactiveNodeType(IntFlag):
    """Classification for reactive graph nodes"""

    SOURCE = 1 << 0  # Produces values (State, Published)
    SINK = 1 << 1  # Consumes values (body, updateUIView)
    TRANSFORM = 1 << 2  # Transforms values (map, combine)
    OBSERVER = 1 << 3  # Observes but doesn't affect (onReceive)


REACTIVE_EDGES = [
    # Source → Sink edges
    ("@State", "body", "triggers_invalidation"),
    ("@Binding", "body", "triggers_invalidation"),
    ("@ObservedObject", "body", "triggers_invalidation"),
    ("@Published", "ObservableObject.objectWillChange", "triggers_publisher"),
    # Environment edges
    ("@Environment", "body", "environment_injection"),
    ("@EnvironmentObject", "body", "environment_injection"),
    # Gesture edges
    ("@GestureState", "gesture", "gesture_state_update"),
    # Focus edges
    ("@FocusState", "focus", "focus_invalidation"),
    # Dynamic type edges
    ("@ScaledMetric", "dynamic_type", "triggers_update"),
    # Storage edges
    ("@AppStorage", "user_defaults", "triggers_update"),
]

# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class PropertyWrapperInfo:
    """Extended info for property wrappers with constraints"""

    name: str
    constraint: int  # ScopeConstraint bitmask
    triggers: List[str] = field(default_factory=list)
    requires: List[str] = field(default_factory=list)


@dataclass
class ModuleV6:
    pri: int
    size: int
    exports: List[int]  # symbol IDs
    imports: List[int]  # string IDs
    scope_constraints: Dict[int, int] = field(
        default_factory=dict
    )  # symbol ID -> constraint
    reactive_role: int = ReactiveNodeType.SINK  # default to sink
    protocol_invariants: Dict[int, List[str]] = field(
        default_factory=dict
    )  # symbol ID -> invariants
    src: Optional[str] = None


# ============================================================================
# MAIN BUNDLER CLASS
# ============================================================================


class CalyxBundlerV6:
    def __init__(self, root: str = ".", max_lines: int = 50000):
        self.root = Path(root)
        self.max_lines = max_lines

        # Intern tables
        self.strs: List[str] = []
        self.str_id: Dict[str, int] = {}

        self.syms: List[str] = []
        self.sym_id: Dict[str, int] = {}

        # Property wrapper registry
        self.pw_info: Dict[str, PropertyWrapperInfo] = {}
        self._init_property_wrappers()

        self.modules: List[ModuleV6] = []
        self.sym_to_mods: Dict[int, List[int]] = defaultdict(list)

        self.stats = {"c": 0, "h": 0, "n": 0, "l": 0, "s": 0, "lines": 0}

        # V6: Invariants storage
        self.invariants: Dict[str, Dict] = PROTOCOL_INVARIANTS.copy()
        self.reactive_edges = REACTIVE_EDGES

    def _init_property_wrappers(self):
        """Initialize property wrapper rules"""
        for name, rules in PROPERTY_WRAPPER_RULES.items():
            self.pw_info[name] = PropertyWrapperInfo(
                name=name,
                constraint=rules.get("allowed_in", ScopeConstraint.NONE),
                triggers=rules.get("triggers", []),
                requires=rules.get("requires", []),
            )
            # Intern the wrapper name
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

    def minify_v6(self, src: str) -> str:
        """
        V6: Aggressive minification that preserves @attributes and critical tokens
        """
        lines = []
        in_block = False

        for line in src.split("\n"):
            # Handle block comments
            if in_block:
                if "*/" in line:
                    in_block = False
                    line = line.split("*/", 1)[1]
                else:
                    continue

            # Handle inline comments
            if "//" in line and not self._is_in_string(line, "//"):
                line = line.split("//", 1)[0]

            # Handle block comment start
            if "/*" in line:
                line, rest = line.split("/*", 1)
                in_block = True
                if "*/" in rest:
                    in_block = False
                    line += rest.split("*/", 1)[1]

            line = line.strip()
            if line:
                # Preserve @attributes and critical tokens
                if line.startswith("@") or re.match(r"^\w+:", line):
                    lines.append(line)
                else:
                    # Compress whitespace but keep structure
                    compressed = re.sub(r"\s+", " ", line)
                    lines.append(compressed)

        return "\n".join(lines)  # Keep newlines for readability

    def _is_in_string(self, line: str, marker: str) -> bool:
        """Check if marker is inside a string literal"""
        in_string = False
        escape = False
        for i, ch in enumerate(line):
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if not in_string and line[i : i + len(marker)] == marker:
                return False
        return True

    def extract_scope_constraints(self, src: str, exports: List[str]) -> Dict[int, int]:
        """
        V6: Extract placement constraints for property wrappers
        Returns dict of symbol ID -> ScopeConstraint bitmask
        """
        constraints = {}

        # Detect current context
        context = self._detect_context(src)

        for export in exports:
            # Check if this export is a property wrapper
            if export in self.pw_info:
                # Find declaration line - pattern for property wrapper usage
                pattern = rf"@{export}\s+var\s+\w+"
                if re.search(pattern, src):
                    # It's a property wrapper usage, not declaration
                    constraints[self.sym_id[export]] = context

        return constraints

    def _detect_context(self, src: str) -> int:
        """Detect the Swift context (struct, class, func, etc.)"""
        context = ScopeConstraint.NONE

        # Check for struct/class/enum/protocol context
        struct_match = re.search(r"^\s*struct\s+\w+", src, re.MULTILINE)
        class_match = re.search(r"^\s*class\s+\w+", src, re.MULTILINE)
        enum_match = re.search(r"^\s*enum\s+\w+", src, re.MULTILINE)
        protocol_match = re.search(r"^\s*protocol\s+\w+", src, re.MULTILINE)
        func_match = re.search(r"^\s*func\s+\w+", src, re.MULTILINE)

        if struct_match:
            context |= ScopeConstraint.STRUCT
            # Check if it's View.body
            if re.search(r"var\s+body:\s+some\s+View", src):
                context |= ScopeConstraint.VIEW_BODY
        if class_match:
            context |= ScopeConstraint.CLASS
            # Check for ObservableObject conformance
            if re.search(r":\s*ObservableObject", src):
                context |= ScopeConstraint.OBSERVABLE_OBJECT
        if enum_match:
            context |= ScopeConstraint.ENUM
        if protocol_match:
            context |= ScopeConstraint.PROTOCOL
        if func_match:
            context |= ScopeConstraint.FUNC

        # Check for computed property
        if re.search(r"var\s+\w+\s*:\s*\w+\s*{\s*get\s*{", src, re.DOTALL):
            context |= ScopeConstraint.COMPUTED_PROP

        return context

    def extract_protocol_invariants(
        self, src: str, exports: List[str]
    ) -> Dict[int, List[str]]:
        """
        V6: Extract protocol conformance invariants
        """
        invariants = {}

        for export in exports:
            if export in self.invariants:
                # Check if this type conforms to the protocol
                pattern = rf":\s*{export}\b"
                if re.search(pattern, src):
                    # Record which invariants apply
                    inv_list = []
                    protocol_data = self.invariants[export]

                    if "required_methods" in protocol_data:
                        inv_list.extend(protocol_data["required_methods"])
                    if "required_properties" in protocol_data:
                        inv_list.extend(protocol_data["required_properties"])
                    if "method_constraints" in protocol_data:
                        for method, constraints in protocol_data[
                            "method_constraints"
                        ].items():
                            inv_list.append(f"{method}:{constraints}")
                    if "implicit_behaviors" in protocol_data:
                        inv_list.extend(protocol_data["implicit_behaviors"])

                    if inv_list:
                        invariants[self.sym_id[export]] = inv_list

        return invariants

    def extract_reactive_role(self, src: str, exports: List[str]) -> int:
        """
        V6: Determine if this module is a reactive source or sink
        """
        role = ReactiveNodeType.SINK  # Default

        # Check for property wrappers that are sources
        for wrapper in self.pw_info:
            if re.search(rf"@{wrapper}\s+var\s+\w+", src):
                role |= ReactiveNodeType.SOURCE

        # Check for body property (sink)
        if re.search(r"var\s+body:\s+some\s+View", src):
            role |= ReactiveNodeType.SINK

        # Check for transform patterns
        if re.search(r"\.map\(|\.combine\(|\.merge\(", src):
            role |= ReactiveNodeType.TRANSFORM

        # Check for onReceive (observer)
        if re.search(r"\.onReceive\(", src):
            role |= ReactiveNodeType.OBSERVER

        return role

    def extract_exports_v6(self, src: str) -> List[Tuple[str, str]]:
        """
        V6: Extract exports with their declaration type
        Returns list of (name, decl_type)
        """
        exports = []
        patterns = [
            (r"^\s*(?:public|open)\s+struct\s+(\w+)", "struct"),
            (r"^\s*(?:public|open)\s+class\s+(\w+)", "class"),
            (r"^\s*(?:public|open)\s+enum\s+(\w+)", "enum"),
            (r"^\s*(?:public|open)\s+protocol\s+(\w+)", "protocol"),
            (r"^\s*(?:public|open)\s+func\s+(\w+)", "func"),
            (r"^\s*(?:public|open)\s+var\s+(\w+)", "var"),
            (r"^\s*(?:public|open)\s+let\s+(\w+)", "let"),
            (r"@\w+\s+var\s+(\w+)", "property_wrapper"),
        ]

        for pattern, decl_type in patterns:
            matches = re.findall(pattern, src, re.MULTILINE)
            for match in matches[:20]:  # Limit per type
                exports.append((match, decl_type))

        return exports

    def extract_imports_v6(self, src: str) -> List[int]:
        """Extract imports with platform detection"""
        imports = []
        for m in re.findall(r"^\s*import\s+(\w+)", src, re.MULTILINE)[:10]:
            imports.append(self.intern_str(m))

        # Also extract conditional imports
        for m in re.findall(r"#if\s+(?:canImport|os)\(([^)]+)\)", src):
            imports.append(self.intern_str(f"#if_{m}"))

        return imports

    def priority(self, path: Path, src: str) -> int:
        p = str(path)
        if any(h in p for h in HIGH_PRIORITY):
            return 1
        for proto in CORE_PROTOCOLS:
            if re.search(rf"(public|open)\s+protocol\s+{proto}\b", src):
                return 1
        for typ in CORE_TYPES:
            if re.search(rf"(public|open)\s+(struct|class|enum)\s+{typ}\b", src):
                return 2
        if src.count("public") + src.count("open") > 10:
            return 2
        for pat in LOW_PRIORITY_PATTERNS:
            if pat.lower() in p.lower():
                return 4
        return 3

    def analyze(self, path: Path) -> Optional[ModuleV6]:
        rel = path.relative_to(self.root)
        if len(rel.parts) < 2 or rel.parts[0] != "Sources":
            return None
        if "Tests" in rel.parts:
            return None

        with open(path, encoding="utf-8", errors="ignore") as f:
            src = f.read()

        lines = len(src.split("\n"))
        pri = self.priority(rel, src)

        # Early skip for low priority when near limit
        if pri >= 4 and self.stats["lines"] > self.max_lines * 0.5:
            self.stats["s"] += 1
            return None

        exports = self.extract_exports_v6(src)
        exp_ids = []

        # Register exports with their types
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
        scope_constraints = self.extract_scope_constraints(src, [e[0] for e in exports])
        protocol_invariants = self.extract_protocol_invariants(
            src, [e[0] for e in exports]
        )
        reactive_role = self.extract_reactive_role(src, [e[0] for e in exports])

        return ModuleV6(
            pri=pri,
            size=lines,
            exports=exp_ids,
            imports=self.extract_imports_v6(src),
            scope_constraints=scope_constraints,
            reactive_role=reactive_role,
            protocol_invariants=protocol_invariants,
            src=self.minify_v6(src) if pri <= 2 else None,
        )

    def discover(self):
        all_mods = []
        for path in self.root.glob("Sources/**/*.swift"):
            if any(x in str(path) for x in [".build", ".git"]):
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
        Returns (weighted_deps, simple_deps, reactive_graph)
        """
        weights: Dict[int, Dict[int, int]] = {i: {} for i in range(len(self.modules))}
        reactive_graph: Dict[int, Dict[int, List[str]]] = {
            i: {} for i in range(len(self.modules))
        }

        for mid, mod in enumerate(self.modules):
            if not mod.src:
                continue

            # Count tokens with symbol weighting
            counts = Counter(re.findall(r"\b\w+\b", mod.src))

            for token, cnt in counts.items():
                if token in self.sym_id:
                    for dep in self.sym_to_mods.get(self.sym_id[token], []):
                        if dep != mid:
                            # Add to dependency graph
                            weight = min(cnt, 3)
                            weights[mid][dep] = weights[mid].get(dep, 0) + weight

                            # V6: Classify reactive edges
                            if token in self.pw_info:
                                triggers = self.pw_info[token].triggers
                                reactive_graph[mid][dep] = (
                                    reactive_graph[mid].get(dep, []) + triggers
                                )

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

        # V6: Build invariants table as positional encoding
        invariants_table = {}
        for proto_name, proto_data in self.invariants.items():
            proto_id = self.sym_id.get(proto_name)
            if proto_id is not None:
                invariants_table[proto_id] = proto_data

        # V6: Build property wrapper rules table
        pw_rules = {}
        for pw_name, pw_info in self.pw_info.items():
            pw_id = self.sym_id.get(pw_name)
            if pw_id is not None:
                pw_rules[pw_id] = {
                    "constraint": int(pw_info.constraint),
                    "triggers": pw_info.triggers,
                    "requires": pw_info.requires,
                }

        bundle = {
            "V": 6,  # Version 6 - Invariant-Aware
            "S": self.strs,
            "Y": self.syms,
            "M": mods,
            "W": wdg,
            "D": dg,
            "C": {i: m.src for i, m in enumerate(self.modules) if m.src},
            "I": invariants_table,  # V6: Protocol invariants
            "P": pw_rules,  # V6: Property wrapper placement rules
            "R": reactive_graph,  # V6: Reactive edge graph
            "t": {
                "f": len(self.modules),
                "l": self.stats["lines"],
                **{k: self.stats[k] for k in ["c", "h", "n", "l", "s"]},
                "version": 6,
                "invariants": len(invariants_table),
                "pw_rules": len(pw_rules),
            },
        }

        json_str = json.dumps(bundle, separators=(",", ":"))
        out = self.root / output
        out.write_text(json_str)

        raw = len(json_str)
        comp = len(zlib.compress(json_str.encode(), 9))

        print(f"\n{'=' * 50}")
        print(f"CALYX v6.0: {len(self.modules)} modules, {self.stats['lines']} lines")
        print(f"Symbols: {len(self.syms)} | Strings: {len(self.strs)}")
        print(f"Invariants: {len(invariants_table)} | PW Rules: {len(pw_rules)}")
        print(
            f"Raw: {raw / 1024:.1f} KB | Compressed: {comp / 1024:.1f} KB ({comp / raw * 100:.1f}%)"
        )
        print(f"{'=' * 50}")


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".")
    p.add_argument("--output", default="calyx_v6.json")
    p.add_argument("--max-lines", type=int, default=50000)
    args = p.parse_args()

    b = CalyxBundlerV6(args.root, args.max_lines)
    b.discover()
    b.generate(args.output)


if __name__ == "__main__":
    main()
