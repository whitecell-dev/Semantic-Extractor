#!/usr/bin/env python3
"""
CALYX-FLASK BUNDLER v6.0 - Context-Aware Web Framework IR
Treats Flask as a decorator-driven framework with request context and application factories
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
# CONFIGURATION: FLASK-SPECIFIC
# ============================================================================

CORE_DECORATORS = {
    "route",
    "before_request",
    "after_request",
    "teardown_request",
    "before_app_request",
    "after_app_request",
    "teardown_appcontext",
    "errorhandler",
    "template_filter",
    "template_global",
    "template_test",
    "context_processor",
}

CORE_CLASSES = {
    "Flask",
    "Blueprint",
    "Request",
    "Response",
    "Config",
    "AppContext",
    "RequestContext",
    "SessionInterface",
}

CONTEXT_LOCALS = {
    "request",  # Current HTTP request
    "session",  # Current session
    "g",  # Per-request globals
    "current_app",  # Current Flask app
}

HIGH_PRIORITY = {
    "app.py",
    "ctx.py",
    "blueprints.py",
    "globals.py",
    "wrappers.py",
    "scaffold.py",
}

LOW_PRIORITY_PATTERNS = {
    "tests/",
    "test_",
    "examples/",
    "docs/",
}

# ============================================================================
# V6: FLASK CONTEXT SYSTEM
# ============================================================================

CONTEXT_LAYERS = {
    "application_context": {
        "created_by": "app.app_context() or with app.app_context():",
        "provides": ["current_app", "g"],
        "lifetime": "Per application context",
        "use_case": "Background tasks, CLI commands",
    },
    "request_context": {
        "created_by": "Incoming request or app.test_request_context()",
        "provides": ["request", "session"],
        "lifetime": "Per HTTP request",
        "use_case": "View functions, request handlers",
        "note": "Automatically creates app context if needed",
    },
}

# ============================================================================
# V6: DECORATOR PLACEMENT RULES
# ============================================================================


class DecoratorConstraint(IntFlag):
    """Flask decorator placement rules"""

    NONE = 0
    FUNCTION = 1 << 0  # Decorates a function
    FLASK_APP = 1 << 1  # Must have Flask app instance
    BLUEPRINT = 1 << 2  # Can be on Blueprint
    VIEW_FUNCTION = 1 << 3  # Decorates view function
    ERROR_HANDLER = 1 << 4  # Error handling decorator
    SETUP_METHOD = 1 << 5  # Must be called before first request

    # Composite
    APP_OR_BLUEPRINT = FLASK_APP | BLUEPRINT
    REQUIRES_CONTEXT = VIEW_FUNCTION | FLASK_APP


DECORATOR_RULES = {
    "route": {
        "constraint": DecoratorConstraint.APP_OR_BLUEPRINT,
        "signature": ["rule", "**options"],
        "returns": "Callable",
        "creates": "url_rule",
        "pattern": r"@(?:app|bp)\.route\(",
    },
    "before_request": {
        "constraint": DecoratorConstraint.APP_OR_BLUEPRINT,
        "signature": [],
        "execution": "before_each_request",
        "pattern": r"@(?:app|bp)\.before_request",
    },
    "after_request": {
        "constraint": DecoratorConstraint.APP_OR_BLUEPRINT,
        "signature": ["response"],
        "returns": "Response",
        "execution": "after_each_request",
        "pattern": r"@(?:app|bp)\.after_request",
    },
    "errorhandler": {
        "constraint": DecoratorConstraint.ERROR_HANDLER,
        "signature": ["error_code_or_exception"],
        "returns": "Response",
        "pattern": r"@(?:app|bp)\.errorhandler\(",
    },
    "context_processor": {
        "constraint": DecoratorConstraint.APP_OR_BLUEPRINT,
        "signature": [],
        "returns": "dict",
        "injects_into": "template_context",
        "pattern": r"@(?:app|bp)\.context_processor",
    },
}

# ============================================================================
# V6: WERKZEUG INTEGRATION
# ============================================================================

WERKZEUG_CLASSES = {
    "Rule": "URL routing rule",
    "Map": "URL map",
    "MapAdapter": "URL matching adapter",
    "Request": "Base request class",
    "Response": "Base response class",
    "ImmutableDict": "Immutable dictionary",
    "Headers": "HTTP headers",
}

# ============================================================================
# V6: EXTENSION POINTS
# ============================================================================

EXTENSION_POINTS = {
    "before_request": "Called before request processing",
    "after_request": "Called after request processing",
    "teardown_request": "Called when request context tears down",
    "teardown_appcontext": "Called when app context tears down",
    "url_defaults": "Modify URL default values",
    "url_value_preprocessor": "Preprocess URL values",
    "template_filter": "Register Jinja2 filter",
    "template_global": "Register Jinja2 global",
    "template_test": "Register Jinja2 test",
    "context_processor": "Inject variables into template context",
    "shell_context_processor": "Add variables to shell context",
    "cli": "Register CLI commands",
}

# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class FlaskDecorator:
    """Flask decorator metadata"""

    name: str
    constraint: int
    signature: List[str]
    pattern: str = ""
    execution_phase: Optional[str] = None


@dataclass
class FlaskSignature:
    """Flask view function signature"""

    func_name: str
    decorators: List[int]  # Decorator symbol IDs
    params: List[str]
    has_context_access: bool  # Uses request, g, session, etc.
    is_async: bool
    route_rules: List[str] = field(default_factory=list)
    error_codes: List[int] = field(default_factory=list)


@dataclass
class ModuleV6:
    pri: int
    size: int
    exports: List[int]
    imports: List[int]
    decorator_usage: Dict[int, int] = field(default_factory=dict)
    signatures: Dict[int, FlaskSignature] = field(default_factory=dict)
    context_dependencies: Set[str] = field(default_factory=set)
    src: Optional[str] = None


# ============================================================================
# NODE ROLES
# ============================================================================


class NodeRole(IntFlag):
    """Flask component roles"""

    APP = 1 << 0  # Flask application
    BLUEPRINT = 1 << 1  # Blueprint
    VIEW = 1 << 2  # View function
    MIDDLEWARE = 1 << 3  # Before/after request hooks
    ERROR_HANDLER = 1 << 4  # Error handler
    CONTEXT = 1 << 5  # Context manager
    CONFIG = 1 << 6  # Configuration


# ============================================================================
# MAIN BUNDLER CLASS
# ============================================================================


class CalyxFlaskBundlerV6:
    def __init__(self, root: str = ".", max_lines: int = 30000):
        self.root = Path(root)
        self.max_lines = max_lines

        # Intern tables
        self.strs: List[str] = []
        self.str_id: Dict[str, int] = {}

        self.syms: List[str] = []
        self.sym_id: Dict[str, int] = {}

        # Decorator registry
        self.decorator_info: Dict[str, FlaskDecorator] = {}
        self._init_decorators()

        self.modules: List[ModuleV6] = []
        self.sym_to_mods: Dict[int, List[int]] = defaultdict(list)

        self.stats = {"c": 0, "h": 0, "n": 0, "l": 0, "s": 0, "lines": 0}

    def _init_decorators(self):
        """Initialize Flask decorator rules"""
        for name, rules in DECORATOR_RULES.items():
            self.decorator_info[name] = FlaskDecorator(
                name=name,
                constraint=rules.get("constraint", DecoratorConstraint.NONE),
                signature=rules.get("signature", []),
                pattern=rules.get("pattern", ""),
                execution_phase=rules.get("execution"),
            )
            self.intern_sym(name)

        # Also intern context locals
        for ctx_var in CONTEXT_LOCALS:
            self.intern_sym(ctx_var)

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
        """Python minification preserving structure"""
        # Remove docstrings
        src = re.sub(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', "", src)

        lines = []
        for line in src.split("\n"):
            # Remove comments
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

    def extract_flask_decorators(self, node: ast.FunctionDef) -> List[str]:
        """Extract Flask-specific decorators"""
        decorators = []
        for dec in node.decorator_list:
            # app.route() or bp.route()
            if isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Attribute):
                    if dec.func.attr in CORE_DECORATORS:
                        decorators.append(dec.func.attr)
            # @app.route without ()
            elif isinstance(dec, ast.Attribute):
                if dec.attr in CORE_DECORATORS:
                    decorators.append(dec.attr)
        return decorators

    def extract_route_rules(self, node: ast.FunctionDef) -> List[str]:
        """Extract route rules from @route decorators"""
        routes = []
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Attribute):
                    if dec.func.attr == "route":
                        # First argument is the rule
                        if dec.args and isinstance(dec.args[0], ast.Constant):
                            routes.append(dec.args[0].value)
        return routes

    def extract_context_usage(self, node: ast.FunctionDef) -> Set[str]:
        """Detect usage of Flask context locals (request, g, session, etc.)"""
        context_vars = set()

        # Walk the AST to find Name nodes
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                if child.id in CONTEXT_LOCALS:
                    context_vars.add(child.id)

        return context_vars

    def extract_flask_signature(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> FlaskSignature:
        """Extract Flask view function signature"""
        func_name = node.name
        decorators = self.extract_flask_decorators(node)
        decorator_ids = [self.intern_sym(d) for d in decorators]

        params = [arg.arg for arg in node.args.args]
        is_async = isinstance(node, ast.AsyncFunctionDef)

        route_rules = self.extract_route_rules(node)
        context_usage = self.extract_context_usage(node)
        has_context_access = len(context_usage) > 0

        return FlaskSignature(
            func_name=func_name,
            decorators=decorator_ids,
            params=params,
            has_context_access=has_context_access,
            is_async=is_async,
            route_rules=route_rules,
        )

    def extract_exports_v6(self, src: str) -> List[Tuple[str, str]]:
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
            # Fallback to regex
            patterns = [
                (r"^\s*class\s+(\w+)", "class"),
                (r"^\s*(?:async\s+)?def\s+(\w+)", "function"),
            ]
            for pattern, decl_type in patterns:
                matches = re.findall(pattern, src, re.MULTILINE)
                for match in matches[:20]:
                    exports.append((match, decl_type))

        return exports

    def extract_signatures_from_ast(self, src: str) -> Dict[str, FlaskSignature]:
        """Extract Flask view signatures"""
        signatures = {}

        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    decorators = self.extract_flask_decorators(node)
                    if decorators:  # Has Flask decorators
                        sig = self.extract_flask_signature(node)
                        signatures[node.name] = sig
        except SyntaxError:
            pass

        return signatures

    def extract_context_dependencies(self, src: str) -> Set[str]:
        """Extract Flask context dependencies from source"""
        deps = set()
        for ctx_var in CONTEXT_LOCALS:
            if re.search(rf"\b{ctx_var}\b", src):
                deps.add(ctx_var)
        return deps

    def extract_imports_v6(self, src: str) -> List[int]:
        """Extract imports"""
        imports = []

        for m in re.findall(r"^\s*import\s+(\w+)", src, re.MULTILINE)[:10]:
            imports.append(self.intern_str(m))

        for m in re.findall(r"^\s*from\s+(\S+)\s+import", src, re.MULTILINE)[:10]:
            imports.append(self.intern_str(m))

        return imports

    def priority(self, path: Path, src: str) -> int:
        p = str(path)

        # High priority for core Flask files
        if any(h in p for h in HIGH_PRIORITY):
            return 1

        # Check for Flask app class
        if re.search(r"class\s+Flask\b", src):
            return 1

        # Check for Blueprint
        if re.search(r"class\s+Blueprint\b", src):
            return 1

        # Many decorators = important
        decorator_count = sum(src.count(f"@{d}") for d in CORE_DECORATORS)
        if decorator_count > 5:
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

        # Skip tests and examples
        if "tests" in rel.parts or "examples" in rel.parts:
            return None

        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                src = f.read()
        except Exception:
            return None

        lines = len(src.split("\n"))
        pri = self.priority(rel, src)

        # Early skip
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

        # Extract Flask-specific data
        signatures_map = self.extract_signatures_from_ast(src)
        signatures_dict = {}
        for func_name, sig in signatures_map.items():
            func_id = self.intern_sym(func_name)
            signatures_dict[func_id] = sig

        context_deps = self.extract_context_dependencies(src)

        # Count decorator usage
        decorator_usage = {}
        for dec_name in CORE_DECORATORS:
            count = src.count(f"@{dec_name}") + src.count(f".{dec_name}(")
            if count > 0:
                dec_id = self.intern_sym(dec_name)
                decorator_usage[dec_id] = count

        return ModuleV6(
            pri=pri,
            size=lines,
            exports=exp_ids,
            imports=self.extract_imports_v6(src),
            decorator_usage=decorator_usage,
            signatures=signatures_dict,
            context_dependencies=context_deps,
            src=self.minify_python(src) if pri <= 2 else None,
        )

    def discover(self):
        all_mods = []

        # Find Flask source
        src_dir = self.root / "src" / "flask"
        if not src_dir.exists():
            src_dir = self.root / "flask"
        if not src_dir.exists():
            src_dir = self.root

        for path in src_dir.glob("**/*.py"):
            if any(x in str(path) for x in ["__pycache__", ".pytest", "tests"]):
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
        """Build dependency + context graph"""
        weights: Dict[int, Dict[int, int]] = {i: {} for i in range(len(self.modules))}
        context_graph: Dict[int, Dict[int, List[str]]] = {
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
                            weight = min(cnt, 3)
                            weights[mid][dep] = weights[mid].get(dep, 0) + weight

                            # Track context dependencies
                            if token in CONTEXT_LOCALS:
                                context_graph[mid][dep] = context_graph[mid].get(
                                    dep, []
                                ) + ["uses_context"]

        def bucket_weight(w: int) -> int:
            return 3 if w >= 10 else 2 if w >= 5 else 1

        wdg = [
            (f, [(t, bucket_weight(w)) for t, w in deps.items()])
            for f, deps in weights.items()
            if deps
        ]
        dg = [(f, [t for t, _ in deps]) for f, deps in wdg]

        return wdg, dg, context_graph

    def generate(self, output: str):
        wdg, dg, context_graph = self.build_graph_v6()

        # Build module map
        mods = []
        for m in self.modules:
            # Serialize signatures
            sigs_serializable = {}
            for func_id, sig in m.signatures.items():
                sigs_serializable[func_id] = {
                    "func_name": sig.func_name,
                    "decorators": sig.decorators,
                    "params": sig.params,
                    "has_context_access": sig.has_context_access,
                    "is_async": sig.is_async,
                    "route_rules": sig.route_rules,
                }

            mod_entry = (
                m.pri,
                m.size,
                m.exports,
                m.imports,
                m.decorator_usage,
                sigs_serializable,
                list(m.context_dependencies),
            )
            mods.append(mod_entry)

        # Build decorator rules
        decorator_rules = {}
        for dec_name, dec_info in self.decorator_info.items():
            dec_id = self.sym_id.get(dec_name)
            if dec_id is not None:
                decorator_rules[dec_id] = {
                    "constraint": int(dec_info.constraint),
                    "signature": dec_info.signature,
                    "pattern": dec_info.pattern,
                    "execution_phase": dec_info.execution_phase,
                }

        bundle = {
            "V": 6,
            "F": "flask",
            "S": self.strs,
            "Y": self.syms,
            "M": mods,
            "W": wdg,
            "D": dg,
            "C": {i: m.src for i, m in enumerate(self.modules) if m.src},
            "I": CONTEXT_LAYERS,
            "P": decorator_rules,
            "X": EXTENSION_POINTS,
            "R": context_graph,
            "t": {
                "f": len(self.modules),
                "l": self.stats["lines"],
                **{k: self.stats[k] for k in ["c", "h", "n", "l", "s"]},
                "version": 6,
                "framework": "flask",
                "decorators": len(decorator_rules),
            },
        }

        json_str = json.dumps(bundle, separators=(",", ":"))
        out = self.root / output
        out.write_text(json_str)

        raw = len(json_str)
        comp = len(zlib.compress(json_str.encode(), 9))

        print(f"\n{'=' * 50}")
        print(
            f"CALYX-FLASK v6.0: {len(self.modules)} modules, {self.stats['lines']} lines"
        )
        print(f"Symbols: {len(self.syms)} | Strings: {len(self.strs)}")
        print(f"Decorators: {len(decorator_rules)}")
        print(
            f"Raw: {raw / 1024:.1f} KB | Compressed: {comp / 1024:.1f} KB ({comp / raw * 100:.1f}%)"
        )
        print(f"{'=' * 50}")


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".")
    p.add_argument("--output", default="calyx_flask_v6.json")
    p.add_argument("--max-lines", type=int, default=30000)
    args = p.parse_args()

    b = CalyxFlaskBundlerV6(args.root, args.max_lines)
    b.discover()
    b.generate(args.output)


if __name__ == "__main__":
    main()
