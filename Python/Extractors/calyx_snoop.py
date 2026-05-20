#!/usr/bin/env python3
"""
CALYX-SNOOP BUNDLER v1.0 - Execution Tracing Framework IR
Treats Snoop as a runtime trace logger with variable inspection and stack depth control
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
# CONFIGURATION: SNOOP-SPECIFIC
# ============================================================================

CORE_CLASSES = {
    "Snoop",  # Main tracer class
    "Config",  # Configuration class
    "Watch",  # Watch expression handler
}

SNOOP_LEVELS = {
    "TRACE": 5,  # Full execution trace
    "CALL": 10,  # Function entry/exit only
    "WATCH": 20,  # Variable changes only
    "LINE": 30,  # Line-by-line execution
}

# Core Snoop methods and their behavior
CORE_METHODS = {
    "snoop": {  # Main decorator/context manager
        "category": "tracer",
        "returns_tracer": True,
        "is_decorator": True,
    },
    "pp": {  # "Print Picky" - standalone variable inspector
        "category": "inspection",
        "returns_tracer": False,
        "is_decorator": False,
    },
    "spy": {  # Trace specific objects/functions
        "category": "tracer",
        "returns_tracer": True,
        "is_decorator": True,
    },
    "install": {  # Global configuration
        "category": "config",
        "returns_tracer": False,
        "is_decorator": False,
    },
}

SNOOP_FEATURES = {
    "watch": "Monitor specific expressions or variables",
    "depth": "How deep to follow function calls",
    "prefix": "Label for specific trace blocks",
    "columns": "Control display of time, thread, etc.",
    "out": "Direct output to file or custom stream",
    "color": "Enable/disable colored output",
}

# Snoop-specific configuration options
TRACE_CONFIGURATION = {
    "simple": {
        "signature": "@snoop",
        "purpose": "Trace entire function with defaults",
        "output": "Shows lines, variables, and return values",
    },
    "deep": {
        "signature": "@snoop(depth=2)",
        "purpose": "Trace into nested function calls",
        "output": "Shows execution flow across function boundaries",
    },
    "watch": {
        "signature": "@snoop(watch=('user.balance', 'transaction.amount'))",
        "purpose": "Monitor specific variables/expressions",
        "output": "Shows when watched values change",
    },
    "custom_output": {
        "signature": "@snoop(out=file.write)",
        "purpose": "Direct trace output to custom sink",
        "output": "Writes to file, network, or custom handler",
    },
}

# Contextual watch patterns (similar to Loguru's bind)
VARIABLE_WATCHING = {
    "simple_watch": {
        "creates": "Watch on simple variable name",
        "example": "@snoop(watch='user_id')",
        "usage": "Tracks changes to user_id in scope",
        "output": "user_id = 123 → 456 | Line 42",
    },
    "expression_watch": {
        "creates": "Watch on computed expression",
        "example": "@snoop(watch=('len(items)', 'items[0] if items else None'))",
        "usage": "Tracks derived values",
        "output": "len(items) = 5 → 6 | Line 47",
    },
    "deep_watch": {
        "creates": "Watch on nested attributes",
        "example": "@snoop(watch='user.profile.email')",
        "usage": "Tracks deep object changes",
        "output": "user.profile.email = 'a@b.com' → 'c@d.com'",
    },
}

# Execution depth patterns (similar to Loguru's level filtering)
DEPTH_CONTROL = {
    "surface": {
        "depth": 0,
        "tracks": "Only decorated function",
        "use_case": "Simple functions without calls",
    },
    "shallow": {
        "depth": 1,
        "tracks": "Immediate child calls",
        "use_case": "Moderate complexity",
    },
    "deep": {
        "depth": 2,
        "tracks": "Grandchild calls",
        "use_case": "Complex recursion or call chains",
    },
    "full": {
        "depth": -1,
        "tracks": "All nested calls",
        "use_case": "Debugging deep call stacks",
    },
}

# Exception handling in trace mode
EXCEPTION_TRACING = {
    "catch_decorator": {
        "usage": "@snoop(catch=True)",
        "purpose": "Trace exceptions when they occur",
        "example": "@snoop(catch=True)\ndef risky(): raise ValueError()",
        "output": "Shows exception location and values",
    },
    "pp_exception": {
        "usage": "pp(exception, depth=2)",
        "purpose": "Pretty print exception with context",
        "captures": "Exception value, traceback, and locals",
    },
    "trace_on_error": {
        "feature": "Auto-trace on exception",
        "shows": "Variable values at error point",
        "controlled_by": "on_error='trace' parameter",
    },
}


# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class SnoopMethod:
    """Snoop method metadata"""

    name: str
    category: str  # "tracer", "inspection", "config"
    returns_tracer: bool
    is_decorator: bool = False
    supports_depth: bool = False
    supports_watch: bool = False


@dataclass
class TraceConfiguration:
    """Trace configuration for a snoop call"""

    depth: int = -1  # -1 = all, 0 = current only, >0 = depth limit
    watches: List[str] = field(default_factory=list)
    prefix: Optional[str] = None
    output_stream: Optional[str] = None  # "stdout", "stderr", or file path
    color: bool = True
    catch_exceptions: bool = False


@dataclass
class ModuleSnoop:
    pri: int
    size: int
    exports: List[int]
    imports: List[int]
    snoop_methods: Dict[int, SnoopMethod] = field(default_factory=dict)
    trace_configs: List[TraceConfiguration] = field(default_factory=list)
    has_depth_tracing: bool = False
    has_watch_expressions: bool = False
    has_exception_tracing: bool = False
    src: Optional[str] = None


# ============================================================================
# NODE ROLES
# ============================================================================


class NodeRole(IntFlag):
    """Snoop component roles"""

    TRACER = 1 << 0  # Main snoop decorator
    WATCH = 1 << 1  # Watch expression handler
    DEPTH = 1 << 2  # Depth control logic
    FRAME = 1 << 3  # Frame inspection
    OUTPUT = 1 << 4  # Output formatting
    EXCEPTION = 1 << 5  # Exception tracing


# ============================================================================
# MAIN BUNDLER CLASS
# ============================================================================


class CalyxSnoopBundlerV1:
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

        self.modules: List[ModuleSnoop] = []
        self.sym_to_mods: Dict[int, List[int]] = defaultdict(list)

        self.stats = {"c": 0, "h": 0, "n": 0, "l": 0, "s": 0, "lines": 0}

    def _init_symbols(self):
        """Initialize Snoop core symbols"""
        for cls in CORE_CLASSES:
            self.intern_sym(cls)
        for method in CORE_METHODS.keys():
            self.intern_sym(method)
        for level in SNOOP_LEVELS.keys():
            self.intern_sym(level)

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

    def extract_snoop_methods(self, src: str) -> Dict[str, SnoopMethod]:
        """Extract Snoop method definitions"""
        methods = {}

        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                # Look for snoop class definition
                if isinstance(node, ast.ClassDef) and node.name in ["Snoop", "Config"]:
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            method_name = item.name

                            # Check if it's a known snoop method
                            if method_name in CORE_METHODS:
                                core_method = CORE_METHODS[method_name]

                                # Detect if method supports depth/watches
                                supports_depth = (
                                    "depth" in src or "depth" in method_name
                                )
                                supports_watch = (
                                    "watch" in src or "watch" in method_name
                                )

                                methods[method_name] = SnoopMethod(
                                    name=method_name,
                                    category=core_method["category"],
                                    returns_tracer=core_method["returns_tracer"],
                                    is_decorator=core_method["is_decorator"],
                                    supports_depth=supports_depth,
                                    supports_watch=supports_watch,
                                )
        except SyntaxError:
            pass

        return methods

    def extract_trace_configs(self, src: str) -> List[TraceConfiguration]:
        """Extract trace configurations from snoop decorators"""
        configs = []

        # Pattern: @snoop(...)
        pattern = r"@snoop\(([^)]+)\)"
        matches = re.findall(pattern, src)

        for match in matches:
            depth = -1
            watches = []
            prefix = None
            output_stream = None
            color = True
            catch = False

            # Parse depth
            depth_match = re.search(r"depth\s*=\s*(\d+|-\d+)", match)
            if depth_match:
                depth = int(depth_match.group(1))

            # Parse watches
            watch_match = re.search(r"watch\s*=\s*\(([^)]+)\)", match)
            if watch_match:
                watches_raw = watch_match.group(1).split(",")
                watches = [w.strip().strip("'\"") for w in watches_raw]

            # Parse prefix
            prefix_match = re.search(r'prefix\s*=\s*[\'"]([^\'"]+)[\'"]', match)
            if prefix_match:
                prefix = prefix_match.group(1)

            # Parse output
            out_match = re.search(r"out\s*=\s*(\w+)", match)
            if out_match:
                output_stream = out_match.group(1)

            # Parse color
            if "color=False" in match:
                color = False

            # Parse catch
            if "catch=True" in match:
                catch = True

            configs.append(
                TraceConfiguration(
                    depth=depth,
                    watches=watches,
                    prefix=prefix,
                    output_stream=output_stream,
                    color=color,
                    catch_exceptions=catch,
                )
            )

        return configs

    def detect_depth_tracing(self, src: str) -> bool:
        """Detect depth-based tracing usage"""
        markers = ["depth=", "depth=-1", "snoop(depth", "spy(depth"]
        return any(marker in src for marker in markers)

    def detect_watch_expressions(self, src: str) -> bool:
        """Detect watch expression usage"""
        markers = ["watch=", "watch=(", "pp(", "spy("]
        return any(marker in src for marker in markers)

    def detect_exception_tracing(self, src: str) -> bool:
        """Detect exception tracing features"""
        markers = ["catch=True", "on_error=", "pp(exception", "trace_on_error"]
        return any(marker in src for marker in markers)

    def extract_exports_v1(self, src: str) -> List[Tuple[str, str]]:
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

    def extract_imports_v1(self, src: str) -> List[int]:
        """Extract imports"""
        imports = []

        for m in re.findall(r"^\s*import\s+(\w+)", src, re.MULTILINE)[:10]:
            imports.append(self.intern_str(m))

        for m in re.findall(r"^\s*from\s+(\S+)\s+import", src, re.MULTILINE)[:10]:
            imports.append(self.intern_str(m))

        return imports

    def priority(self, path: Path, src: str) -> int:
        p = str(path)

        # High priority for core files
        if any(h in p for h in ["snoop.py", "configuration.py", "formatting.py"]):
            return 1

        # Check for main Snoop class
        if re.search(r"class\s+Snoop\b", src):
            return 1

        # Check for watch expression handling
        if "watch" in p or "watch" in src.lower():
            return 2

        # Check for frame inspection
        if "frame" in p or "inspect" in p:
            return 2

        # Low priority patterns
        LOW_PRIORITY_PATTERNS = {"tests/", "test_", "docs/", "examples/"}
        for pat in LOW_PRIORITY_PATTERNS:
            if pat.lower() in p.lower():
                return 4

        return 3

    def analyze(self, path: Path) -> Optional[ModuleSnoop]:
        try:
            rel = path.relative_to(self.root)
        except ValueError:
            return None

        # Skip tests and docs
        if "tests" in rel.parts or "docs" in rel.parts:
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

        exports = self.extract_exports_v1(src)
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

        # Extract Snoop-specific data
        snoop_methods_map = self.extract_snoop_methods(src)
        snoop_methods_dict = {}
        for method_name, method_info in snoop_methods_map.items():
            method_id = self.intern_sym(method_name)
            snoop_methods_dict[method_id] = method_info

        trace_configs = self.extract_trace_configs(src)
        has_depth = self.detect_depth_tracing(src)
        has_watch = self.detect_watch_expressions(src)
        has_exception = self.detect_exception_tracing(src)

        return ModuleSnoop(
            pri=pri,
            size=lines,
            exports=exp_ids,
            imports=self.extract_imports_v1(src),
            snoop_methods=snoop_methods_dict,
            trace_configs=trace_configs,
            has_depth_tracing=has_depth,
            has_watch_expressions=has_watch,
            has_exception_tracing=has_exception,
            src=self.minify_python(src) if pri <= 2 else None,
        )

    def discover(self):
        all_mods = []

        # Find Snoop source
        src_dir = self.root / "snoop"
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

    def build_graph_v1(self) -> Tuple[List, List, Dict]:
        """Build dependency + feature graph for Snoop"""
        weights: Dict[int, Dict[int, int]] = {i: {} for i in range(len(self.modules))}
        feature_graph: Dict[int, Dict[int, List[str]]] = {
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

                            # Track feature usage
                            if token in CORE_METHODS:
                                feature_graph[mid][dep] = feature_graph[mid].get(
                                    dep, []
                                ) + [f"uses_snoop_{CORE_METHODS[token]['category']}"]
                            elif token == "depth":
                                feature_graph[mid][dep] = feature_graph[mid].get(
                                    dep, []
                                ) + ["uses_depth_control"]
                            elif token == "watch":
                                feature_graph[mid][dep] = feature_graph[mid].get(
                                    dep, []
                                ) + ["uses_watch_expression"]

        def bucket_weight(w: int) -> int:
            return 3 if w >= 10 else 2 if w >= 5 else 1

        wdg = [
            (f, [(t, bucket_weight(w)) for t, w in deps.items()])
            for f, deps in weights.items()
            if deps
        ]
        dg = [(f, [t for t, _ in deps]) for f, deps in wdg]

        return wdg, dg, feature_graph

    def generate(self, output: str):
        wdg, dg, feature_graph = self.build_graph_v1()

        # Build module map
        mods = []
        for m in self.modules:
            # Serialize snoop methods
            methods_serializable = {}
            for method_id, method_info in m.snoop_methods.items():
                methods_serializable[method_id] = {
                    "name": method_info.name,
                    "category": method_info.category,
                    "returns_tracer": method_info.returns_tracer,
                    "is_decorator": method_info.is_decorator,
                    "supports_depth": method_info.supports_depth,
                    "supports_watch": method_info.supports_watch,
                }

            # Serialize trace configs
            trace_configs_serializable = [
                {
                    "depth": tc.depth,
                    "watches": tc.watches,
                    "prefix": tc.prefix,
                    "output_stream": tc.output_stream,
                    "color": tc.color,
                    "catch_exceptions": tc.catch_exceptions,
                }
                for tc in m.trace_configs
            ]

            mod_entry = (
                m.pri,
                m.size,
                m.exports,
                m.imports,
                methods_serializable,
                trace_configs_serializable,
                m.has_depth_tracing,
                m.has_watch_expressions,
                m.has_exception_tracing,
            )
            mods.append(mod_entry)

        bundle = {
            "V": 1,
            "F": "snoop",
            "S": self.strs,
            "Y": self.syms,
            "M": mods,
            "W": wdg,
            "D": dg,
            "C": {i: m.src for i, m in enumerate(self.modules) if m.src},
            "LVL": SNOOP_LEVELS,
            "TRC": TRACE_CONFIGURATION,
            "WTC": VARIABLE_WATCHING,
            "DPT": DEPTH_CONTROL,
            "EXC": EXCEPTION_TRACING,
            "FT": SNOOP_FEATURES,
            "R": feature_graph,
            "t": {
                "f": len(self.modules),
                "l": self.stats["lines"],
                **{k: self.stats[k] for k in ["c", "h", "n", "l", "s"]},
                "version": 1,
                "framework": "snoop",
                "depth_tracing": True,
                "watch_expressions": True,
                "exception_tracing": True,
            },
        }

        json_str = json.dumps(bundle, separators=(",", ":"))
        out = self.root / output
        out.write_text(json_str)

        raw = len(json_str)
        comp = len(zlib.compress(json_str.encode(), 9))

        print(f"\n{'=' * 50}")
        print(
            f"CALYX-SNOOP v1.0: {len(self.modules)} modules, {self.stats['lines']} lines"
        )
        print(f"Symbols: {len(self.syms)} | Strings: {len(self.strs)}")
        print(f"Depth Tracing: Enabled | Watch Expressions: Enabled")
        print(
            f"Raw: {raw / 1024:.1f} KB | Compressed: {comp / 1024:.1f} KB ({comp / raw * 100:.1f}%)"
        )
        print(f"{'=' * 50}")


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".")
    p.add_argument("--output", default="calyx_snoop_v1.json")
    p.add_argument("--max-lines", type=int, default=30000)
    args = p.parse_args()

    b = CalyxSnoopBundlerV1(args.root, args.max_lines)
    b.discover()
    b.generate(args.output)


if __name__ == "__main__":
    main()
