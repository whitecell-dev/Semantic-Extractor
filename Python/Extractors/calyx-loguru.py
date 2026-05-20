#!/usr/bin/env python3
"""
CALYX-LOGURU BUNDLER v6.0 - Structured Logging Framework IR
Treats Loguru as a lazy-evaluation logger with contextual binding and sink management
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
# CONFIGURATION: LOGURU-SPECIFIC
# ============================================================================

CORE_CLASSES = {
    "Logger",  # Main logger class
    "LevelConfig",  # Level configuration
}

LOG_LEVELS = {
    "TRACE": 5,
    "DEBUG": 10,
    "INFO": 20,
    "SUCCESS": 25,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}

CORE_METHODS = {
    "add",  # Add sink
    "remove",  # Remove sink
    "bind",  # Bind contextual data
    "contextualize",  # Context manager for binding
    "patch",  # Patch log record
    "opt",  # Options for lazy evaluation
    "catch",  # Decorator to catch exceptions
    "complete",  # Wait for async sinks
    "level",  # Level management
    "enable",  # Enable logging
    "disable",  # Disable logging
}

LAZY_EVALUATION_METHODS = {
    "opt": {
        "lazy": "Defer string formatting until actually logged",
        "colors": "Force colorization on/off",
        "raw": "Skip formatting, output raw message",
        "exception": "Attach exception info",
        "depth": "Adjust stack frame depth",
        "capture": "Capture locals in exception",
        "ansi": "Strip ANSI codes",
    },
}

BINDING_METHODS = {
    "bind": {
        "type": "immutable",
        "scope": "returns new logger instance",
        "usage": "logger.bind(request_id='123')",
        "persistence": "Permanent until garbage collected",
    },
    "contextualize": {
        "type": "context_manager",
        "scope": "within 'with' block",
        "usage": "with logger.contextualize(user='alice'):",
        "persistence": "Temporary, released on exit",
    },
    "patch": {
        "type": "callback",
        "scope": "applies to each log record",
        "usage": "logger.patch(lambda record: record.update(...))",
        "persistence": "Applied on every log call",
    },
}

SINK_TYPES = {
    "file": "Path or file-like object",
    "stream": "sys.stdout, sys.stderr",
    "callable": "Custom function(message)",
    "handler": "logging.Handler compatible",
    "coroutine": "async def sink(message)",
}

HIGH_PRIORITY = {
    "_logger.py",
    "__init__.py",
    "_handler.py",
    "_file_sink.py",
}

LOW_PRIORITY_PATTERNS = {
    "tests/",
    "test_",
    "docs/",
}

# ============================================================================
# V6: LAZY EVALUATION SYSTEM
# ============================================================================

LAZY_EVALUATION_PATTERN = {
    "deferred_formatting": {
        "without_opt": "logger.debug('Value: {}', expensive_call())",
        "problem": "expensive_call() runs even if DEBUG disabled",
        "with_opt": "logger.opt(lazy=True).debug('Value: {}', lambda: expensive_call())",
        "benefit": "Lambda only called if DEBUG enabled",
    },
    "implementation": {
        "check_level_first": "if record.level >= handler.level",
        "then_format": "message = format_string.format(*args)",
        "optimization": "Skip formatting if level too low",
    },
}

# ============================================================================
# V6: CONTEXTUAL BINDING
# ============================================================================

CONTEXTUAL_BINDING = {
    "bind_pattern": {
        "creates": "New logger instance with extra context",
        "example": "request_logger = logger.bind(request_id=uuid.uuid4())",
        "usage": "request_logger.info('Processing')",
        "output": "{time} | INFO | Processing | request_id=abc-123",
    },
    "contextualize_pattern": {
        "creates": "Temporary context via context manager",
        "example": "with logger.contextualize(user='alice'): logger.info('Action')",
        "usage": "Scoped to with block",
        "output": "{time} | INFO | Action | user=alice",
    },
    "patch_pattern": {
        "creates": "Dynamic record modification",
        "example": "logger.patch(lambda r: r.update(env='prod'))",
        "usage": "Applied to every log call",
        "output": "{time} | INFO | Message | env=prod",
    },
}

# ============================================================================
# V6: SINK MANAGEMENT
# ============================================================================

SINK_LIFECYCLE = {
    "add": {
        "signature": "add(sink, *, level=DEBUG, format=..., filter=None, colorize=None)",
        "returns": "handler_id (int)",
        "purpose": "Register new logging destination",
    },
    "remove": {
        "signature": "remove(handler_id=None)",
        "purpose": "Unregister sink by ID",
        "note": "Can remove all if handler_id is None",
    },
    "complete": {
        "signature": "complete()",
        "purpose": "Wait for async sinks to finish",
        "async_safe": True,
    },
}

# ============================================================================
# V6: EXCEPTION HANDLING
# ============================================================================

EXCEPTION_FEATURES = {
    "catch_decorator": {
        "usage": "@logger.catch",
        "purpose": "Automatically log exceptions",
        "example": "@logger.catch\ndef risky_function(): ...",
        "output": "Logs full exception with traceback",
    },
    "exception_option": {
        "usage": "logger.opt(exception=True).error('Failed')",
        "purpose": "Attach current exception to log",
        "captures": "sys.exc_info() automatically",
    },
    "better_exceptions": {
        "feature": "Enhanced traceback formatting",
        "shows": "Variable values in stack frames",
        "controlled_by": "diagnose=True parameter",
    },
}

# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class LoggerMethod:
    """Logger method metadata"""

    name: str
    category: str  # "level", "sink", "context", "option"
    is_lazy: bool
    returns_logger: bool
    is_decorator: bool = False


@dataclass
class SinkDefinition:
    """Sink configuration"""

    sink_type: str  # "file", "stream", "callable", "handler", "coroutine"
    level: str
    format_string: Optional[str]
    is_async: bool


@dataclass
class ModuleV6:
    pri: int
    size: int
    exports: List[int]
    imports: List[int]
    logger_methods: Dict[int, LoggerMethod] = field(default_factory=dict)
    sink_definitions: List[SinkDefinition] = field(default_factory=list)
    has_lazy_eval: bool = False
    has_binding: bool = False
    has_exception_handling: bool = False
    src: Optional[str] = None


# ============================================================================
# NODE ROLES
# ============================================================================


class NodeRole(IntFlag):
    """Loguru component roles"""

    LOGGER = 1 << 0  # Logger class
    SINK = 1 << 1  # Sink handler
    HANDLER = 1 << 2  # Handler implementation
    FORMATTER = 1 << 3  # Formatting logic
    COLORIZER = 1 << 4  # Color output
    EXCEPTION = 1 << 5  # Exception handling
    FILTER = 1 << 6  # Log filtering


# ============================================================================
# MAIN BUNDLER CLASS
# ============================================================================


class CalyxLoguruBundlerV6:
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

        self.modules: List[ModuleV6] = []
        self.sym_to_mods: Dict[int, List[int]] = defaultdict(list)

        self.stats = {"c": 0, "h": 0, "n": 0, "l": 0, "s": 0, "lines": 0}

    def _init_symbols(self):
        """Initialize Loguru core symbols"""
        for cls in CORE_CLASSES:
            self.intern_sym(cls)
        for method in CORE_METHODS:
            self.intern_sym(method)
        for level in LOG_LEVELS.keys():
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

    def extract_logger_methods(self, src: str) -> Dict[str, LoggerMethod]:
        """Extract Logger method definitions"""
        methods = {}

        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == "Logger":
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            method_name = item.name

                            # Categorize method
                            if method_name in LOG_LEVELS or method_name in [
                                "trace",
                                "debug",
                                "info",
                                "success",
                                "warning",
                                "error",
                                "critical",
                            ]:
                                category = "level"
                            elif method_name in ["add", "remove", "complete"]:
                                category = "sink"
                            elif method_name in ["bind", "contextualize", "patch"]:
                                category = "context"
                            elif method_name in ["opt", "catch"]:
                                category = "option"
                            else:
                                category = "utility"

                            # Check if returns logger (for chaining)
                            returns_logger = method_name in ["bind", "opt", "patch"]

                            # Check if it's a decorator
                            is_decorator = method_name == "catch"

                            # Check for lazy evaluation
                            is_lazy = "opt" in method_name or "lazy" in src

                            methods[method_name] = LoggerMethod(
                                name=method_name,
                                category=category,
                                is_lazy=is_lazy,
                                returns_logger=returns_logger,
                                is_decorator=is_decorator,
                            )
        except SyntaxError:
            pass

        return methods

    def detect_lazy_eval(self, src: str) -> bool:
        """Detect lazy evaluation usage"""
        markers = ["opt(lazy=True)", "lambda:", "callable("]
        return any(marker in src for marker in markers)

    def detect_binding(self, src: str) -> bool:
        """Detect contextual binding usage"""
        markers = ["bind(", "contextualize(", "patch("]
        return any(marker in src for marker in markers)

    def detect_exception_handling(self, src: str) -> bool:
        """Detect exception handling features"""
        markers = ["@logger.catch", "opt(exception=", "diagnose=", "backtrace="]
        return any(marker in src for marker in markers)

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

        # High priority for core files
        if any(h in p for h in HIGH_PRIORITY):
            return 1

        # Check for Logger class
        if re.search(r"class\s+Logger\b", src):
            return 1

        # Check for sink implementations
        if "Sink" in p or "_sink" in p:
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

        # Extract Loguru-specific data
        logger_methods_map = self.extract_logger_methods(src)
        logger_methods_dict = {}
        for method_name, method_info in logger_methods_map.items():
            method_id = self.intern_sym(method_name)
            logger_methods_dict[method_id] = method_info

        has_lazy = self.detect_lazy_eval(src)
        has_binding = self.detect_binding(src)
        has_exception = self.detect_exception_handling(src)

        return ModuleV6(
            pri=pri,
            size=lines,
            exports=exp_ids,
            imports=self.extract_imports_v6(src),
            logger_methods=logger_methods_dict,
            has_lazy_eval=has_lazy,
            has_binding=has_binding,
            has_exception_handling=has_exception,
            src=self.minify_python(src) if pri <= 2 else None,
        )

    def discover(self):
        all_mods = []

        # Find Loguru source
        src_dir = self.root / "loguru"
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
        """Build dependency + feature graph"""
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
                                ) + ["uses_logger_method"]

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
        wdg, dg, feature_graph = self.build_graph_v6()

        # Build module map
        mods = []
        for m in self.modules:
            # Serialize logger methods
            methods_serializable = {}
            for method_id, method_info in m.logger_methods.items():
                methods_serializable[method_id] = {
                    "name": method_info.name,
                    "category": method_info.category,
                    "is_lazy": method_info.is_lazy,
                    "returns_logger": method_info.returns_logger,
                    "is_decorator": method_info.is_decorator,
                }

            mod_entry = (
                m.pri,
                m.size,
                m.exports,
                m.imports,
                methods_serializable,
                m.has_lazy_eval,
                m.has_binding,
                m.has_exception_handling,
            )
            mods.append(mod_entry)

        bundle = {
            "V": 6,
            "F": "loguru",
            "S": self.strs,
            "Y": self.syms,
            "M": mods,
            "W": wdg,
            "D": dg,
            "C": {i: m.src for i, m in enumerate(self.modules) if m.src},
            "L": LOG_LEVELS,
            "LAZ": LAZY_EVALUATION_PATTERN,
            "BND": CONTEXTUAL_BINDING,
            "SNK": SINK_LIFECYCLE,
            "EXC": EXCEPTION_FEATURES,
            "OPT": LAZY_EVALUATION_METHODS,
            "R": feature_graph,
            "t": {
                "f": len(self.modules),
                "l": self.stats["lines"],
                **{k: self.stats[k] for k in ["c", "h", "n", "l", "s"]},
                "version": 6,
                "framework": "loguru",
                "lazy_evaluation": True,
            },
        }

        json_str = json.dumps(bundle, separators=(",", ":"))
        out = self.root / output
        out.write_text(json_str)

        raw = len(json_str)
        comp = len(zlib.compress(json_str.encode(), 9))

        print(f"\n{'=' * 50}")
        print(
            f"CALYX-LOGURU v6.0: {len(self.modules)} modules, {self.stats['lines']} lines"
        )
        print(f"Symbols: {len(self.syms)} | Strings: {len(self.strs)}")
        print(f"Lazy Evaluation: Supported")
        print(
            f"Raw: {raw / 1024:.1f} KB | Compressed: {comp / 1024:.1f} KB ({comp / raw * 100:.1f}%)"
        )
        print(f"{'=' * 50}")


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".")
    p.add_argument("--output", default="calyx_loguru_v6.json")
    p.add_argument("--max-lines", type=int, default=30000)
    args = p.parse_args()

    b = CalyxLoguruBundlerV6(args.root, args.max_lines)
    b.discover()
    b.generate(args.output)


if __name__ == "__main__":
    main()
