#!/usr/bin/env python3
"""
CALYX-STARLETTE BUNDLER v6.0 - ASGI Middleware Stack IR
Treats ASGI applications as composition of middleware layers with scope-receive-send protocol
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
# CONFIGURATION: STARLETTE-SPECIFIC (ASGI)
# ============================================================================

# The ASGI Trinity
CORE_SYMBOLS = {
    "scope",  # ASGI scope dict (connection metadata)
    "receive",  # Async callable to receive messages
    "send",  # Async callable to send messages
}

CORE_CLASSES = {
    "Starlette",  # Main application
    "Route",  # Path -> Endpoint mapping
    "Mount",  # Prefix -> Sub-app mounting
    "Router",  # Route container
    "Request",  # Scope -> Request object
    "Response",  # Response abstraction
    "JSONResponse",  # JSON response
    "HTMLResponse",  # HTML response
    "StreamingResponse",  # Streaming response
    "WebSocket",  # WebSocket connection
    "Middleware",  # Middleware wrapper
    "BaseHTTPMiddleware",  # HTTP middleware base
}

CORE_TYPES = {
    "ASGIApp",  # Callable[[Scope, Receive, Send], Awaitable[None]]
    "Scope",  # Dict with connection info
    "Receive",  # Async callable
    "Send",  # Async callable
    "Lifespan",  # Lifespan protocol
}

HIGH_PRIORITY = {
    "routing.py",  # Path matching and dispatch
    "responses.py",  # Response byte-stream emission
    "requests.py",  # Scope -> Request mapping
    "middleware/base.py",  # Middleware protocol
    "applications.py",  # Main Starlette app
    "types.py",  # ASGI type definitions
}

LOW_PRIORITY_PATTERNS = {
    "tests/",
    "test_",
    "testclient",
    "schemas",
    "staticfiles",
}

# ============================================================================
# V6: NODE ROLES (ASGI Architecture)
# ============================================================================


class NodeRole(IntFlag):
    """Role in the ASGI middleware stack"""

    ROUTER = 1 << 0  # Routes requests (Router, Route)
    MIDDLEWARE = 1 << 1  # Wraps app (Middleware, BaseHTTPMiddleware)
    ENDPOINT = 1 << 2  # Terminal handler (view function)
    APPLICATION = 1 << 3  # Root app (Starlette)
    RESPONSE = 1 << 4  # Response emitter
    REQUEST = 1 << 5  # Request parser
    WEBSOCKET = 1 << 6  # WebSocket handler


# ============================================================================
# V6: COMPOSITION INVARIANTS (ASGI Protocol Rules)
# ============================================================================

SIGNATURE_INVARIANTS = {
    "asgi_app": {
        "required_params": ["scope", "receive", "send"],
        "param_order": "fixed",  # Order matters in ASGI
        "is_async": True,
        "return_type": "None",
    },
    "endpoint": {
        "required_params": ["request"],
        "return_type": "Response",
        "is_async": True,  # Most endpoints are async
        "can_be_sync": True,  # But sync is allowed
    },
    "middleware_call": {
        "required_params": ["scope", "receive", "send"],
        "wraps": "app",
        "is_async": True,
    },
    "middleware_dispatch": {
        "required_params": ["request", "call_next"],
        "return_type": "Response",
        "is_async": True,
    },
    "websocket_endpoint": {
        "required_params": ["websocket"],
        "return_type": "None",
        "is_async": True,
    },
}

# ============================================================================
# V6: ASGI EDGES (Middleware Stack & Routing Tree)
# ============================================================================

# Middleware stack edges (onion layers)
ASGI_EDGES = [
    # Application composition
    ("Starlette", "Middleware", "is_wrapped_by"),
    ("Middleware", "app", "wraps_app"),
    # Routing composition
    ("Router", "Route", "dispatches_to"),
    ("Route", "endpoint", "invokes_endpoint"),
    ("Mount", "Router", "delegates_to"),
    ("Mount", "app", "mounts_subapp"),
    # Request/Response flow
    ("scope", "Request", "parsed_into"),
    ("endpoint", "Response", "returns"),
    ("Response", "send", "emits_via"),
    # WebSocket flow
    ("scope", "WebSocket", "parsed_into"),
    ("websocket_endpoint", "send", "emits_via"),
]

# ============================================================================
# V6: MIDDLEWARE COMPOSITION PATTERNS
# ============================================================================

MIDDLEWARE_PATTERNS = {
    "BaseHTTPMiddleware": {
        "init_signature": ["app"],
        "dispatch_signature": ["request", "call_next"],
        "is_class_based": True,
        "wrapping_model": "dispatch_override",
    },
    "pure_asgi_middleware": {
        "init_signature": ["app"],
        "call_signature": ["scope", "receive", "send"],
        "is_class_based": True,
        "wrapping_model": "direct_asgi",
    },
    "middleware_decorator": {
        "function_signature": ["app"],
        "returns": "ASGIApp",
        "wrapping_model": "closure",
    },
}

# ============================================================================
# V6: ROUTE COMPOSITION PATTERNS
# ============================================================================

ROUTE_PATTERNS = {
    "Route": {
        "required_params": ["path", "endpoint"],
        "optional_params": ["methods", "name", "include_in_schema"],
        "path_type": "str_with_params",  # "/users/{user_id}"
        "endpoint_type": "callable_or_class",
    },
    "Mount": {
        "required_params": ["path", "app"],
        "optional_params": ["name"],
        "path_type": "prefix",  # "/api"
        "app_type": "ASGIApp_or_Router",
    },
    "WebSocketRoute": {
        "required_params": ["path", "endpoint"],
        "optional_params": ["name"],
        "endpoint_type": "async_callable",
    },
}

# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class ASGISignature:
    """ASGI protocol signature"""

    name: str
    params: List[str]
    param_types: List[int]  # Type symbol IDs
    is_async: bool
    return_type: Optional[str]
    protocol_valid: bool  # Matches ASGI protocol


@dataclass
class ModuleV6:
    pri: int
    size: int
    exports: List[int]  # symbol IDs
    imports: List[int]  # string IDs
    node_role: int = NodeRole.ENDPOINT
    asgi_signatures: Dict[int, ASGISignature] = field(default_factory=dict)
    composition_patterns: Dict[int, str] = field(default_factory=dict)
    src: Optional[str] = None


# ============================================================================
# MAIN BUNDLER CLASS
# ============================================================================


class CalyxStarletteBundlerV6:
    def __init__(self, root: str = ".", max_lines: int = 30000):
        self.root = Path(root)
        self.max_lines = max_lines

        # Intern tables
        self.strs: List[str] = []
        self.str_id: Dict[str, int] = {}

        self.syms: List[str] = []
        self.sym_id: Dict[str, int] = {}

        # Initialize symbols
        self._init_symbols()

        self.modules: List[ModuleV6] = []
        self.sym_to_mods: Dict[int, List[int]] = defaultdict(list)

        self.stats = {"c": 0, "h": 0, "n": 0, "l": 0, "s": 0, "lines": 0}

        # V6: ASGI-specific storage
        self.signature_invariants = SIGNATURE_INVARIANTS
        self.asgi_edges = ASGI_EDGES
        self.middleware_patterns = MIDDLEWARE_PATTERNS
        self.route_patterns = ROUTE_PATTERNS

    def _init_symbols(self):
        """Initialize core ASGI symbols"""
        for sym in CORE_SYMBOLS | CORE_CLASSES | CORE_TYPES:
            self.intern_sym(sym)

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
        Python-aware minification preserving:
        - Indentation
        - __call__ methods (ASGI protocol)
        - async def (required for ASGI)
        """
        # Remove docstrings but preserve function signatures
        src = re.sub(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', "", src)

        lines = []
        for line in src.split("\n"):
            # Preserve async def, __call__, and class definitions
            if any(pattern in line for pattern in ["async def", "__call__", "class ", "def "]):
                lines.append(line.rstrip())
                continue

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

    def extract_asgi_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> Optional[ASGISignature]:
        """
        Extract ASGI protocol signature
        """
        name = node.name
        params = [arg.arg for arg in node.args.args]
        param_types = []
        is_async = isinstance(node, ast.AsyncFunctionDef)

        # Extract parameter types
        for arg in node.args.args:
            if arg.annotation:
                if isinstance(arg.annotation, ast.Name):
                    param_types.append(self.intern_sym(arg.annotation.id))
                else:
                    param_types.append(self.intern_sym("Any"))
            else:
                param_types.append(self.intern_sym("Any"))

        # Extract return type
        return_type = None
        if node.returns:
            if isinstance(node.returns, ast.Name):
                return_type = node.returns.id

        # Validate ASGI protocol
        protocol_valid = self._validate_asgi_protocol(params, is_async, name)

        return ASGISignature(
            name=name,
            params=params,
            param_types=param_types,
            is_async=is_async,
            return_type=return_type,
            protocol_valid=protocol_valid,
        )

    def _validate_asgi_protocol(self, params: List[str], is_async: bool, name: str) -> bool:
        """
        Validate ASGI protocol compliance
        """
        # Check for ASGI app signature
        if set(params) == {"scope", "receive", "send"}:
            return is_async  # Must be async

        # Check for endpoint signature
        if "request" in params:
            return True  # Can be sync or async

        # Check for WebSocket endpoint
        if "websocket" in params:
            return is_async  # Must be async

        # Check for middleware dispatch
        if set(params) == {"request", "call_next"}:
            return is_async  # Must be async

        # Check for __call__ in middleware
        if name == "__call__" and set(params) == {"self", "scope", "receive", "send"}:
            return is_async

        return True  # Default to valid

    def extract_node_role(self, src: str, class_name: Optional[str] = None) -> int:
        """
        Determine node role from class inheritance and function signatures
        """
        role = NodeRole.ENDPOINT  # Default

        # Check for Router
        if re.search(r"class\s+\w+.*Router", src):
            role |= NodeRole.ROUTER

        # Check for Middleware
        if re.search(r"class\s+\w+.*Middleware|BaseHTTPMiddleware", src):
            role |= NodeRole.MIDDLEWARE

        # Check for Application
        if re.search(r"class\s+\w+.*Starlette", src) or "Starlette(" in src:
            role |= NodeRole.APPLICATION

        # Check for Response
        if re.search(r"class\s+\w+.*Response", src):
            role |= NodeRole.RESPONSE

        # Check for Request
        if re.search(r"class\s+\w+.*Request", src):
            role |= NodeRole.REQUEST

        # Check for WebSocket
        if re.search(r"class\s+\w+.*WebSocket", src):
            role |= NodeRole.WEBSOCKET

        # Check for endpoint (async def with request parameter)
        if re.search(r"async\s+def\s+\w+.*request", src):
            role |= NodeRole.ENDPOINT

        return role

    def extract_composition_patterns(self, src: str) -> Dict[int, str]:
        """
        Extract middleware and route composition patterns
        """
        patterns = {}

        # Check for Route composition
        if re.search(r"Route\(", src):
            route_id = self.intern_sym("Route")
            patterns[route_id] = "route_composition"

        # Check for Mount composition
        if re.search(r"Mount\(", src):
            mount_id = self.intern_sym("Mount")
            patterns[mount_id] = "mount_composition"

        # Check for Middleware composition
        if re.search(r"Middleware\(", src):
            middleware_id = self.intern_sym("Middleware")
            patterns[middleware_id] = "middleware_wrapping"

        # Check for routes list composition
        if re.search(r"routes\s*=\s*\[", src):
            router_id = self.intern_sym("Router")
            patterns[router_id] = "list_composition"

        return patterns

    def extract_exports_v6(self, src: str) -> List[Tuple[str, str]]:
        """
        Extract exports with their type
        """
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
                (r"^\s*async\s+def\s+(\w+)", "function"),
                (r"^\s*def\s+(\w+)", "function"),
            ]

            for pattern, decl_type in patterns:
                matches = re.findall(pattern, src, re.MULTILINE)
                for match in matches[:20]:
                    exports.append((match, decl_type))

        return exports

    def extract_asgi_signatures_from_ast(self, src: str) -> Dict[str, ASGISignature]:
        """Extract ASGI protocol signatures"""
        signatures = {}

        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sig = self.extract_asgi_signature(node)
                    if sig:
                        signatures[node.name] = sig
        except SyntaxError:
            pass

        return signatures

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

        # High priority for core ASGI files
        if any(h in p for h in HIGH_PRIORITY):
            return 1

        # Check for core classes
        for cls in CORE_CLASSES:
            if re.search(rf"class\s+{cls}\b", src):
                return 1

        # Check for ASGI protocol
        if all(sym in src for sym in ["scope", "receive", "send"]):
            return 2

        # High export count
        if src.count("class ") + src.count("async def ") > 10:
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

        # Skip tests
        if "tests" in rel.parts or "test_" in path.name:
            return None

        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                src = f.read()
        except Exception:
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
        for exp_name, exp_type in exports:
            sym_id = self.intern_sym(exp_name)
            exp_ids.append(sym_id)
            self.sym_to_mods[sym_id].append(mod_idx)

        self.stats["lines"] += lines
        self.stats["c" if pri == 1 else "h" if pri == 2 else "n" if pri == 3 else "l"] += 1

        # V6: Extract ASGI signatures
        signatures_map = self.extract_asgi_signatures_from_ast(src)
        signatures_dict = {}
        for func_name, sig in signatures_map.items():
            func_id = self.intern_sym(func_name)
            signatures_dict[func_id] = sig

        # V6: Extract composition patterns
        composition_patterns = self.extract_composition_patterns(src)

        # V6: Determine node role
        node_role = self.extract_node_role(src)

        return ModuleV6(
            pri=pri,
            size=lines,
            exports=exp_ids,
            imports=self.extract_imports_v6(src),
            node_role=node_role,
            asgi_signatures=signatures_dict,
            composition_patterns=composition_patterns,
            src=self.minify_python(src) if pri <= 2 else None,
        )

    def discover(self):
        all_mods = []

        # Find all Python files
        src_dir = self.root / "starlette"
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
        V6: Build dependency graph + ASGI composition tree
        """
        weights: Dict[int, Dict[int, int]] = {i: {} for i in range(len(self.modules))}
        asgi_composition: Dict[int, Dict[int, List[str]]] = {i: {} for i in range(len(self.modules))}

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

                            # V6: Track ASGI composition
                            if token in CORE_CLASSES:
                                asgi_composition[mid][dep] = asgi_composition[mid].get(dep, []) + ["uses_class"]

        def bucket_weight(w: int) -> int:
            return 3 if w >= 10 else 2 if w >= 5 else 1

        wdg = [(f, [(t, bucket_weight(w)) for t, w in deps.items()]) for f, deps in weights.items() if deps]
        dg = [(f, [t for t, _ in deps]) for f, deps in wdg]

        return wdg, dg, asgi_composition

    def generate(self, output: str):
        wdg, dg, asgi_composition = self.build_graph_v6()

        # V6: Build module map
        mods = []
        for m in self.modules:
            # Convert ASGISignature to serializable format
            sigs_serializable = {}
            for func_id, sig in m.asgi_signatures.items():
                sigs_serializable[func_id] = {
                    "name": sig.name,
                    "params": sig.params,
                    "param_types": sig.param_types,
                    "is_async": sig.is_async,
                    "return_type": sig.return_type,
                    "protocol_valid": sig.protocol_valid,
                }

            mod_entry = (
                m.pri,
                m.size,
                m.exports,
                m.imports,
                m.node_role,
                sigs_serializable,
                m.composition_patterns,
            )
            mods.append(mod_entry)

        bundle = {
            "V": 6,
            "F": "starlette",
            "S": self.strs,
            "Y": self.syms,
            "M": mods,
            "W": wdg,
            "D": dg,
            "C": {i: m.src for i, m in enumerate(self.modules) if m.src},
            "I": self.signature_invariants,
            "P": self.middleware_patterns,
            "T": self.route_patterns,
            "R": asgi_composition,
            "E": self.asgi_edges,  # ASGI edge patterns
            "t": {
                "f": len(self.modules),
                "l": self.stats["lines"],
                **{k: self.stats[k] for k in ["c", "h", "n", "l", "s"]},
                "version": 6,
                "framework": "starlette",
                "asgi_protocol": True,
            },
        }

        json_str = json.dumps(bundle, separators=(",", ":"))
        out = self.root / output
        out.write_text(json_str)

        raw = len(json_str)
        comp = len(zlib.compress(json_str.encode(), 9))

        print(f"\n{'=' * 50}")
        print(f"CALYX-STARLETTE v6.0: {len(self.modules)} modules, {self.stats['lines']} lines")
        print(f"Symbols: {len(self.syms)} | Strings: {len(self.strs)}")
        print(f"ASGI Protocol: True")
        print(f"Raw: {raw / 1024:.1f} KB | Compressed: {comp / 1024:.1f} KB ({comp / raw * 100:.1f}%)")
        print(f"{'=' * 50}")


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--root", default="./starlette")
    p.add_argument("--output", default="calyx_starlette_v6.json")
    p.add_argument("--max-lines", type=int, default=30000)
    args = p.parse_args()

    b = CalyxStarletteBundlerV6(args.root, args.max_lines)
    b.discover()
    b.generate(args.output)


if __name__ == "__main__":
    main()
