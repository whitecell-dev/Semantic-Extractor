#!/usr/bin/env python3
"""
CALYX-DISHKA BUNDLER v7.0 - Dependency Injection Framework IR
Treats Dishka as a runtime DI system with providers, scopes, and
lifecycle management
"""

import json
import re
import zlib
import ast
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from collections import Counter, defaultdict
from enum import IntFlag

# ============================================================================
# CONFIGURATION: DISHKA-SPECIFIC
# ============================================================================

CORE_CLASSES = {
    "Provider",  # Base provider class
    "AsyncContainer",  # Async DI container
    "Container",  # Sync DI container
    "Scope",  # Lifecycle scope
    "Registry",  # Component registry
    "Dependency",  # Dependency descriptor
    "Factory",  # Factory wrapper
    "Config",  # Configuration provider
    "FromContext",  # Context extraction
    "Alias",  # Type alias
    "Delegate",  # Delegate provider
}

# Dishka lifecycle scopes
SCOPES = {
    "APP": "Application-level singleton (entire app lifetime)",
    "REQUEST": "Per-request/operation scope",
    "SESSION": "User session level",
    "ACTION": "Per-action/transaction scope",
    "STEP": "Single execution step",
}

# Provider types
PROVIDER_TYPES = {
    "factory": "Factory method creating instance",
    "singleton": "Single instance across scope",
    "context": "Context-dependent value",
    "alias": "Type alias mapping",
    "delegate": "Delegated to another provider",
}

HIGH_PRIORITY = {
    "provider.py",
    "container.py",
    "registry.py",
    "dependency_source.py",
    "scope.py",
    "factory.py",
    "__init__.py",
}

LOW_PRIORITY_PATTERNS = {
    "tests/",
    "test_",
    "docs/",
    "examples/",
}

# ============================================================================
# V7: DISHKA AGENT PATTERNS
# ============================================================================

DISHKA_AGENTS = {
    "static_resolver": {
        "method": "AST Discovery",
        "input": "Source code with @provide decorators",
        "process": "Find @provide → Parse signatures → Map dependency graph",
        "pros": ["Fast", "No runtime", "Explicit graph"],
        "cons": [
            "Can't resolve conditional providers",
            "Misses runtime registration",
        ],
        "use_case": "Visualizing DI graph without executing code",
    },
    "runtime_container": {
        "method": "Container.get()",
        "input": "Container instance + type request",
        "process": "Traverse registry → Resolve dependencies → Instantiate → Manage lifecycle",
        "pros": [
            "Complete resolution",
            "Catches scope mismatches",
            "Validates circular deps",
        ],
        "cons": ["Requires execution", "Platform-specific"],
        "use_case": "Verifying runtime correctness and scope safety",
    },
    "hybrid": {
        "strategy": "Static discovery for structure, runtime for validation",
        "controlled_by": "allow_runtime=True, resolve_deps=False",
    },
}

# ============================================================================
# V7: DEPENDENCY GRAPH STRUCTURE
# ============================================================================

DEPENDENCY_GRAPH = {
    "providers": {
        "factory": "Function that creates instance",
        "singleton": "Cached single instance",
        "context": "Request-scoped value",
    },
    "scopes": {
        "hierarchy": ["APP", "SESSION", "REQUEST", "ACTION", "STEP"],
        "rule": "Can only inject wider or same scope, never narrower",
    },
    "injection": {
        "constructor": "__init__ parameters",
        "field": "Class attributes",
        "method": "Method call injection",
    },
}

# ============================================================================
# V7: RESOLUTION CONSTRAINTS
# ============================================================================

RESOLUTION_RULES = {
    "scope_compatibility": {
        "APP": ["APP"],
        "SESSION": ["APP", "SESSION"],
        "REQUEST": ["APP", "SESSION", "REQUEST"],
        "ACTION": ["APP", "SESSION", "REQUEST", "ACTION"],
        "STEP": ["APP", "SESSION", "REQUEST", "ACTION", "STEP"],
    },
    "circular_detection": "DFS-based cycle detection in dependency graph",
    "missing_dependency": "Check that all required types have providers",
    "async_propagation": "Async factories require async resolution chain",
}

# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class DishkaComponent:
    """Represents a dependency provided in Dishka"""

    name: str
    scope: str  # APP, REQUEST, SESSION, ACTION, STEP
    provides_type: str
    is_async: bool
    is_factory: bool
    is_singleton: bool
    dependencies: List[str] = field(default_factory=list)
    source_line: Optional[int] = None


@dataclass
class ProviderInfo:
    """Provider metadata"""

    name: str
    provider_type: str  # factory, singleton, context, alias, delegate
    scope: str
    provided_types: List[str]
    dependencies: List[str]
    is_async: bool
    source_file: str
    source_line: Optional[int] = None


@dataclass
class ContainerInfo:
    """Container configuration"""

    is_async: bool
    providers: List[str]
    parent_container: Optional[str] = None


@dataclass
class ModuleV7:
    pri: int
    size: int
    exports: List[int]
    imports: List[int]
    dishka_components: Dict[int, DishkaComponent] = field(default_factory=dict)
    providers: Dict[int, ProviderInfo] = field(default_factory=dict)
    containers: Dict[int, ContainerInfo] = field(default_factory=dict)
    has_static_resolution: bool = False
    has_runtime_container: bool = False
    has_scope_validation: bool = False
    src: Optional[str] = None


# ============================================================================
# NODE ROLES
# ============================================================================


class NodeRole(IntFlag):
    """Dishka component roles"""

    PROVIDER = 1 << 0  # Provider definitions
    CONTAINER = 1 << 1  # Container implementations
    SCOPE = 1 << 2  # Scope management
    REGISTRY = 1 << 3  # Component registry
    RESOLVER = 1 << 4  # Dependency resolution
    FACTORY = 1 << 5  # Factory creation


# ============================================================================
# MAIN BUNDLER CLASS
# ============================================================================


class CalyxDishkaBundlerV7:
    def __init__(self, root: str = ".", max_lines: int = 30000):
        self.root = Path(root)
        self.max_lines = max_lines

        # Intern tables
        self.strs: List[str] = []
        self.str_id: Dict[str, int] = {}

        self.syms: List[str] = []
        self.sym_id: Dict[str, int] = {}

        # Initialize core symbols
        self._init_symbols()

        self.modules: List[ModuleV7] = []
        self.sym_to_mods: Dict[int, List[int]] = defaultdict(list)

        self.stats = {"c": 0, "h": 0, "n": 0, "l": 0, "s": 0, "lines": 0}

    def _init_symbols(self):
        """Initialize Dishka core symbols"""
        for cls in CORE_CLASSES:
            self.intern_sym(cls)
        for scope in SCOPES.keys():
            self.intern_sym(scope)
        for ptype in PROVIDER_TYPES.keys():
            self.intern_sym(ptype)

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
        """Python minification"""
        src = re.sub(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', "", src)

        lines = []
        for line in src.split("\n"):
            if "#" in line:
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

    def extract_dishka_components(
        self, src: str
    ) -> Dict[str, DishkaComponent]:
        """Extract Dishka components from @provide decorators"""
        components = {}

        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for decorator in node.decorator_list:
                        if self._is_provide_decorator(decorator):
                            scope = self._extract_scope(decorator)
                            is_singleton = (
                                scope == "APP"
                                or self._has_singleton_hint(decorator)
                            )

                            # Extract dependencies from parameters
                            deps = [
                                arg.arg
                                for arg in node.args.args
                                if arg.arg not in ("self", "cls")
                            ]

                            # Get return type
                            return_type = "Any"
                            if node.returns:
                                return_type = self._extract_type_name(
                                    node.returns
                                )

                            components[node.name] = DishkaComponent(
                                name=node.name,
                                scope=scope,
                                provides_type=return_type,
                                is_async=isinstance(
                                    node, ast.AsyncFunctionDef
                                ),
                                is_factory=True,
                                is_singleton=is_singleton,
                                dependencies=deps,
                                source_line=node.lineno,
                            )
        except SyntaxError:
            pass

        return components

    def extract_providers(self, src: str) -> Dict[str, ProviderInfo]:
        """Extract Provider classes and their configuration"""
        providers = {}

        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    # Check if it inherits from Provider
                    for base in node.bases:
                        base_name = self._extract_type_name(base)
                        if base_name == "Provider":
                            provider_info = self._parse_provider_class(
                                node, src
                            )
                            if provider_info:
                                providers[node.name] = provider_info
        except SyntaxError:
            pass

        return providers

    def extract_containers(self, src: str) -> Dict[str, ContainerInfo]:
        """Extract Container instances and configurations"""
        containers = {}

        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            if self._is_container_creation(node.value):
                                containers[target.id] = ContainerInfo(
                                    is_async=self._is_async_container(
                                        node.value
                                    ),
                                    providers=self._extract_provider_refs(
                                        node.value
                                    ),
                                    parent_container=None,
                                )
        except SyntaxError:
            pass

        return containers

    def _is_provide_decorator(self, decorator: ast.AST) -> bool:
        """Check if decorator is @provide"""
        if isinstance(decorator, ast.Name) and decorator.id == "provide":
            return True
        if isinstance(decorator, ast.Call):
            if (
                isinstance(decorator.func, ast.Name)
                and decorator.func.id == "provide"
            ):
                return True
        return False

    def _extract_scope(self, decorator: ast.AST) -> str:
        """Extract scope from @provide decorator"""
        if isinstance(decorator, ast.Call):
            for kw in decorator.keywords:
                if kw.arg == "scope":
                    if isinstance(kw.value, ast.Attribute):
                        return kw.value.attr
                    elif isinstance(kw.value, ast.Name):
                        return kw.value.id
        return "REQUEST"  # Default scope

    def _has_singleton_hint(self, decorator: ast.AST) -> bool:
        """Check if provider is marked as singleton"""
        if isinstance(decorator, ast.Call):
            for kw in decorator.keywords:
                if kw.arg == "singleton":
                    return True
        return False

    def _extract_type_name(self, node: ast.AST) -> str:
        """Extract type name from AST node"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._extract_type_name(node.value)}.{node.attr}"
        elif isinstance(node, ast.Subscript):
            return self._extract_type_name(node.value)
        elif isinstance(node, ast.Constant):
            return str(node.value)
        return "Any"

    def _parse_provider_class(
        self, node: ast.ClassDef, src: str
    ) -> Optional[ProviderInfo]:
        """Parse Provider class to extract its configuration"""
        provider_type = "factory"
        scope = "REQUEST"
        provided_types = []
        dependencies = []

        for item in node.body:
            if isinstance(item, ast.AnnAssign):
                # Class attribute = provided type
                if isinstance(item.target, ast.Name):
                    provided_types.append(item.target.id)
            elif isinstance(item, ast.FunctionDef):
                if item.name == "__init__":
                    deps = [
                        arg.arg
                        for arg in item.args.args
                        if arg.arg not in ("self", "cls")
                    ]
                    dependencies.extend(deps)

        return ProviderInfo(
            name=node.name,
            provider_type=provider_type,
            scope=scope,
            provided_types=provided_types,
            dependencies=dependencies,
            is_async=False,
            source_file="",
            source_line=node.lineno,
        )

    def _is_container_creation(self, node: ast.AST) -> bool:
        """Check if node creates a Container"""
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in (
                "Container",
                "AsyncContainer",
            ):
                return True
        return False

    def _is_async_container(self, node: ast.AST) -> bool:
        """Check if container is async"""
        if isinstance(node, ast.Call):
            if (
                isinstance(node.func, ast.Name)
                and node.func.id == "AsyncContainer"
            ):
                return True
        return False

    def _extract_provider_refs(self, node: ast.AST) -> List[str]:
        """Extract provider references from container creation"""
        providers = []
        if isinstance(node, ast.Call):
            for arg in node.args:
                if isinstance(arg, ast.Name):
                    providers.append(arg.id)
        return providers

    def detect_static_resolution(self, src: str) -> bool:
        """Detect static dependency resolution (AST-based)"""
        markers = ["Provider", "provide", "scope=", "from_context"]
        return any(marker in src for marker in markers)

    def detect_runtime_container(self, src: str) -> bool:
        """Detect runtime container usage"""
        markers = ["container.get(", "container.resolve(", "Container("]
        return any(marker in src for marker in markers)

    def detect_scope_validation(self, src: str) -> bool:
        """Detect scope validation logic"""
        markers = ["validate_scope", "scope_compatible", "Scope."]
        return any(marker in src for marker in markers)

    def extract_exports_v7(self, src: str) -> List[Tuple[str, str]]:
        """Extract exports"""
        exports = []

        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    exports.append((node.name, "class"))
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    exports.append((node.name, "function"))
        except SyntaxError:
            patterns = [
                (r"^\s*class\s+(\w+)", "class"),
                (r"^\s*(?:async\s+)?def\s+(\w+)", "function"),
            ]
            for pattern, decl_type in patterns:
                matches = re.findall(pattern, src, re.MULTILINE)
                for match in matches[:20]:
                    exports.append((match, decl_type))

        return exports

    def extract_imports_v7(self, src: str) -> List[int]:
        """Extract imports"""
        imports = []

        for m in re.findall(r"^\s*import\s+(\w+)", src, re.MULTILINE)[:10]:
            imports.append(self.intern_str(m))

        for m in re.findall(r"^\s*from\s+(\S+)\s+import", src, re.MULTILINE)[
            :10
        ]:
            imports.append(self.intern_str(m))

        return imports

    def priority(self, path: Path, src: str) -> int:
        p = str(path)

        if any(h in p for h in HIGH_PRIORITY):
            return 1

        for cls in CORE_CLASSES:
            if re.search(rf"class\s+{cls}\b", src):
                return 1

        if "provider" in p or "container" in p:
            return 1

        for pat in LOW_PRIORITY_PATTERNS:
            if pat.lower() in p.lower():
                return 4

        return 3

    def analyze(self, path: Path) -> Optional[ModuleV7]:
        try:
            rel = path.relative_to(self.root)
        except ValueError:
            return None

        if "tests" in rel.parts or "docs" in rel.parts:
            return None

        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                src = f.read()
        except Exception:
            return None

        lines = len(src.split("\n"))
        pri = self.priority(rel, src)

        if pri >= 4 and self.stats["lines"] > self.max_lines * 0.5:
            self.stats["s"] += 1
            return None

        exports = self.extract_exports_v7(src)
        exp_ids = []

        mod_idx = len(self.modules)
        for exp_name, exp_type in exports:
            sym_id = self.intern_sym(exp_name)
            exp_ids.append(sym_id)
            self.sym_to_mods[sym_id].append(mod_idx)

        self.stats["lines"] += lines
        self.stats[
            "c" if pri == 1 else "h" if pri == 2 else "n" if pri == 3 else "l"
        ] += 1

        # Extract Dishka-specific data
        dishka_components_map = self.extract_dishka_components(src)
        dishka_components_dict = {}
        for comp_name, comp_info in dishka_components_map.items():
            comp_id = self.intern_sym(comp_name)
            dishka_components_dict[comp_id] = comp_info

        providers_map = self.extract_providers(src)
        providers_dict = {}
        for prov_name, prov_info in providers_map.items():
            prov_id = self.intern_sym(prov_name)
            providers_dict[prov_id] = prov_info

        containers_map = self.extract_containers(src)
        containers_dict = {}
        for cont_name, cont_info in containers_map.items():
            cont_id = self.intern_sym(cont_name)
            containers_dict[cont_id] = cont_info

        has_static = self.detect_static_resolution(src)
        has_runtime = self.detect_runtime_container(src)
        has_scope = self.detect_scope_validation(src)

        return ModuleV7(
            pri=pri,
            size=lines,
            exports=exp_ids,
            imports=self.extract_imports_v7(src),
            dishka_components=dishka_components_dict,
            providers=providers_dict,
            containers=containers_dict,
            has_static_resolution=has_static,
            has_runtime_container=has_runtime,
            has_scope_validation=has_scope,
            src=self.minify_python(src) if pri <= 2 else None,
        )

    def discover(self):
        all_mods = []

        src_dir = self.root / "src" / "dishka"
        if not src_dir.exists():
            src_dir = self.root / "dishka"
        if not src_dir.exists():
            src_dir = self.root

        for path in src_dir.glob("**/*.py"):
            if any(
                x in str(path) for x in ["__pycache__", ".pytest", "tests"]
            ):
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

    def build_graph_v7(self) -> Tuple[List, List, Dict]:
        """Build dependency + injection graph"""
        weights: Dict[int, Dict[int, int]] = {
            i: {} for i in range(len(self.modules))
        }
        injection_graph: Dict[int, Dict[int, List[str]]] = {
            i: {} for i in range(len(self.modules))
        }

        for mid, mod in enumerate(self.modules):
            if not mod.src:
                continue

            counts = Counter(re.findall(r"\b\w+\b", mod.src))

            for token, cnt in counts.items():
                if token in self.sym_id:
                    for dep in self.sym_to_mods.get(self.sym_id[token], []):
                        if dep != mid:
                            weight = min(cnt, 3)
                            weights[mid][dep] = (
                                weights[mid].get(dep, 0) + weight
                            )

                            if token in CORE_CLASSES:
                                injection_graph[mid][dep] = injection_graph[
                                    mid
                                ].get(dep, []) + ["uses_dishka_core"]
                            elif token in SCOPES:
                                injection_graph[mid][dep] = injection_graph[
                                    mid
                                ].get(dep, []) + ["uses_scope"]

        def bucket_weight(w: int) -> int:
            return 3 if w >= 10 else 2 if w >= 5 else 1

        wdg = [
            (f, [(t, bucket_weight(w)) for t, w in deps.items()])
            for f, deps in weights.items()
            if deps
        ]
        dg = [(f, [t for t, _ in deps]) for f, deps in wdg]

        return wdg, dg, injection_graph

    def generate(self, output: str):
        wdg, dg, injection_graph = self.build_graph_v7()

        mods = []
        for m in self.modules:
            components_serializable = {}
            for comp_id, comp_info in m.dishka_components.items():
                components_serializable[comp_id] = {
                    "name": comp_info.name,
                    "scope": comp_info.scope,
                    "provides_type": comp_info.provides_type,
                    "is_async": comp_info.is_async,
                    "is_factory": comp_info.is_factory,
                    "is_singleton": comp_info.is_singleton,
                    "dependencies": comp_info.dependencies,
                    "source_line": comp_info.source_line,
                }

            providers_serializable = {}
            for prov_id, prov_info in m.providers.items():
                providers_serializable[prov_id] = {
                    "name": prov_info.name,
                    "provider_type": prov_info.provider_type,
                    "scope": prov_info.scope,
                    "provided_types": prov_info.provided_types,
                    "dependencies": prov_info.dependencies,
                    "is_async": prov_info.is_async,
                }

            containers_serializable = {}
            for cont_id, cont_info in m.containers.items():
                containers_serializable[cont_id] = {
                    "name": cont_id,
                    "is_async": cont_info.is_async,
                    "providers": cont_info.providers,
                }

            mod_entry = (
                m.pri,
                m.size,
                m.exports,
                m.imports,
                components_serializable,
                providers_serializable,
                containers_serializable,
                m.has_static_resolution,
                m.has_runtime_container,
                m.has_scope_validation,
            )
            mods.append(mod_entry)

        bundle = {
            "V": 7,
            "F": "dishka",
            "S": self.strs,
            "Y": self.syms,
            "M": mods,
            "W": wdg,
            "D": dg,
            "C": {i: m.src for i, m in enumerate(self.modules) if m.src},
            "AGT": DISHKA_AGENTS,
            "DEP": DEPENDENCY_GRAPH,
            "RULES": RESOLUTION_RULES,
            "R": injection_graph,
            "t": {
                "f": len(self.modules),
                "l": self.stats["lines"],
                **{k: self.stats[k] for k in ["c", "h", "n", "l", "s"]},
                "version": 7,
                "framework": "dishka",
                "dual_agent": True,
                "scopes_supported": list(SCOPES.keys()),
            },
        }

        json_str = json.dumps(bundle, separators=(",", ":"))
        out = self.root / output
        out.write_text(json_str)

        raw = len(json_str)
        comp = len(zlib.compress(json_str.encode(), 9))

        print(f"\n{'=' * 50}")
        print(
            f"CALYX-DISHKA v7.0: {len(self.modules)} modules, {self.stats['lines']} lines"
        )
        print(f"Symbols: {len(self.syms)} | Strings: {len(self.strs)}")
        print(f"DI System: Static Resolution + Runtime Container")
        print(f"Scopes Tracked: {list(SCOPES.keys())}")
        print(
            f"Raw: {raw / 1024:.1f} KB | Compressed: {comp / 1024:.1f} KB ({comp / raw * 100:.1f}%)"
        )
        print(f"{'=' * 50}")


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--root", default="./dishka")
    p.add_argument("--output", default="calyx_dishka_v7.json")
    p.add_argument("--max-lines", type=int, default=30000)
    args = p.parse_args()

    b = CalyxDishkaBundlerV7(args.root, args.max_lines)
    b.discover()
    b.generate(args.output)


if __name__ == "__main__":
    main()
