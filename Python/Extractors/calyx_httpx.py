#!/usr/bin/env python3
"""
CALYX-HTTPX BUNDLER v6.0 - Transport-Layer HTTP Client IR
Treats HTTPX as a dual async/sync HTTP client with pluggable transport layers
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
# CONFIGURATION: HTTPX-SPECIFIC
# ============================================================================

CORE_CLASSES = {
    "Client",  # Sync HTTP client
    "AsyncClient",  # Async HTTP client
    "Request",  # HTTP request
    "Response",  # HTTP response
    "Headers",  # HTTP headers
    "Cookies",  # Cookie jar
    "URL",  # URL handling
    "QueryParams",  # Query parameters
}

TRANSPORT_CLASSES = {
    "BaseTransport",  # Transport interface (sync)
    "AsyncBaseTransport",  # Transport interface (async)
    "HTTPTransport",  # HTTP/1.1 transport (sync)
    "AsyncHTTPTransport",  # HTTP/1.1 transport (async)
    "ASGITransport",  # ASGI transport
    "WSGITransport",  # WSGI transport
    "MockTransport",  # Test transport
}

CONFIG_CLASSES = {
    "Timeout",  # Timeout configuration
    "Limits",  # Connection limits
    "Proxy",  # Proxy configuration
}

AUTH_CLASSES = {
    "Auth",  # Auth base class
    "BasicAuth",  # HTTP Basic auth
    "DigestAuth",  # HTTP Digest auth
    "FunctionAuth",  # Callable auth
}

HIGH_PRIORITY = {
    "_client.py",
    "_models.py",
    "_transports/base.py",
    "_transports/default.py",
    "_config.py",
    "_auth.py",
}

LOW_PRIORITY_PATTERNS = {
    "tests/",
    "test_",
    "docs/",
}

# ============================================================================
# V6: TRANSPORT LAYER ARCHITECTURE
# ============================================================================

TRANSPORT_LAYERS = {
    "interface": {
        "BaseTransport": "Sync transport interface",
        "AsyncBaseTransport": "Async transport interface",
        "contract": "handle_request(request) -> response",
    },
    "implementations": {
        "HTTPTransport": "HTTP/1.1 via httpcore (sync)",
        "AsyncHTTPTransport": "HTTP/1.1 via httpcore (async)",
        "ASGITransport": "ASGI application transport",
        "WSGITransport": "WSGI application transport",
        "MockTransport": "In-memory test transport",
    },
    "composition": "Client wraps Transport, Transport wraps ConnectionPool",
}

# ============================================================================
# V6: ASYNC/SYNC DUALITY
# ============================================================================

DUALITY_PATTERN = {
    "sync_class": "Client",
    "async_class": "AsyncClient",
    "shared_base": "BaseClient",
    "method_pairs": [
        ("request", "async def request"),
        ("get", "async def get"),
        ("post", "async def post"),
        ("send", "async def send"),
    ],
    "context_managers": [
        ("with Client() as client:", "async with AsyncClient() as client:"),
    ],
}

# ============================================================================
# V6: HTTP PROTOCOL LAYERS
# ============================================================================

HTTP_PROTOCOL_STACK = {
    "application": "Client API (get, post, request)",
    "connection_pool": "Connection reuse and limits",
    "http_version": "HTTP/1.1, HTTP/2 negotiation",
    "transport": "Socket I/O and TLS",
    "network": "TCP/IP",
}

# ============================================================================
# V6: CONNECTION LIFECYCLE
# ============================================================================

CONNECTION_STATES = {
    "IDLE": "Connection available in pool",
    "ACTIVE": "Request in progress",
    "CLOSED": "Connection closed",
}

# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class HTTPXMethod:
    """HTTP method signature"""

    name: str
    is_async: bool
    parameters: List[str]
    returns: str
    has_sync_twin: bool = False
    transport_layer: Optional[str] = None


@dataclass
class TransportInfo:
    """Transport layer information"""

    name: str
    is_async: bool
    implements: str  # "BaseTransport" or "AsyncBaseTransport"
    protocol: str  # "HTTP/1.1", "HTTP/2", "ASGI", etc.


@dataclass
class ModuleV6:
    pri: int
    size: int
    exports: List[int]
    imports: List[int]
    is_async_module: bool = False
    has_sync_twin: bool = False
    transport_layer: Optional[str] = None
    http_methods: Dict[int, HTTPXMethod] = field(default_factory=dict)
    src: Optional[str] = None


# ============================================================================
# NODE ROLES
# ============================================================================


class NodeRole(IntFlag):
    """HTTPX component roles"""

    CLIENT = 1 << 0  # Client class
    TRANSPORT = 1 << 1  # Transport layer
    MODEL = 1 << 2  # Request/Response models
    CONFIG = 1 << 3  # Configuration
    AUTH = 1 << 4  # Authentication
    ASYNC_IMPL = 1 << 5  # Async implementation
    SYNC_IMPL = 1 << 6  # Sync implementation


# ============================================================================
# MAIN BUNDLER CLASS
# ============================================================================


class CalyxHTTPXBundlerV6:
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

        # Transport registry
        self.transports: Dict[str, TransportInfo] = {}

    def _init_symbols(self):
        """Initialize core HTTP symbols"""
        for cls in CORE_CLASSES | TRANSPORT_CLASSES | CONFIG_CLASSES | AUTH_CLASSES:
            self.intern_sym(cls)

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

    def detect_async_module(self, src: str) -> bool:
        """Detect if module is primarily async"""
        async_count = src.count("async def ") + src.count("async with ")
        sync_count = src.count("def ") - async_count
        return async_count > sync_count * 0.3  # >30% async

    def detect_transport_layer(self, name: str, src: str) -> Optional[str]:
        """Detect which transport layer this module implements"""
        if "_transports" in name:
            if "ASGI" in src or "asgi" in name:
                return "ASGI"
            elif "WSGI" in src or "wsgi" in name:
                return "WSGI"
            elif "Mock" in src or "mock" in name:
                return "Mock"
            elif "AsyncHTTPTransport" in src:
                return "HTTP/1.1 (async)"
            elif "HTTPTransport" in src:
                return "HTTP/1.1 (sync)"
            else:
                return "Base"
        return None

    def extract_http_methods(self, src: str) -> Dict[str, HTTPXMethod]:
        """Extract HTTP client methods"""
        methods = {}

        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name in [
                        "get",
                        "post",
                        "put",
                        "patch",
                        "delete",
                        "head",
                        "options",
                        "request",
                        "send",
                    ]:
                        is_async = isinstance(node, ast.AsyncFunctionDef)
                        params = [arg.arg for arg in node.args.args]

                        # Determine return type
                        returns = "Response"
                        if node.returns:
                            if isinstance(node.returns, ast.Name):
                                returns = node.returns.id

                        methods[node.name] = HTTPXMethod(
                            name=node.name,
                            is_async=is_async,
                            parameters=params,
                            returns=returns,
                        )
        except SyntaxError:
            pass

        return methods

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

        # Check for core classes
        for cls in CORE_CLASSES:
            if re.search(rf"class\s+{cls}\b", src):
                return 1

        # Transport implementations
        for cls in TRANSPORT_CLASSES:
            if re.search(rf"class\s+{cls}\b", src):
                return 1

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
        if "tests" in rel.parts:
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

        # Extract HTTPX-specific data
        is_async = self.detect_async_module(src)
        transport = self.detect_transport_layer(str(path.name), src)
        http_methods_map = self.extract_http_methods(src)

        http_methods_dict = {}
        for method_name, method_info in http_methods_map.items():
            method_id = self.intern_sym(method_name)
            http_methods_dict[method_id] = method_info

        # Check for sync/async twins
        has_twin = False
        if "Client" in src and "AsyncClient" in src:
            has_twin = True

        return ModuleV6(
            pri=pri,
            size=lines,
            exports=exp_ids,
            imports=self.extract_imports_v6(src),
            is_async_module=is_async,
            has_sync_twin=has_twin,
            transport_layer=transport,
            http_methods=http_methods_dict,
            src=self.minify_python(src) if pri <= 2 else None,
        )

    def discover(self):
        all_mods = []

        # Find HTTPX source
        src_dir = self.root / "httpx"
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
        """Build dependency + transport graph"""
        weights: Dict[int, Dict[int, int]] = {i: {} for i in range(len(self.modules))}
        transport_graph: Dict[int, Dict[int, List[str]]] = {
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

                            # Track transport layer usage
                            if token in TRANSPORT_CLASSES:
                                transport_graph[mid][dep] = transport_graph[mid].get(
                                    dep, []
                                ) + ["uses_transport"]

        def bucket_weight(w: int) -> int:
            return 3 if w >= 10 else 2 if w >= 5 else 1

        wdg = [
            (f, [(t, bucket_weight(w)) for t, w in deps.items()])
            for f, deps in weights.items()
            if deps
        ]
        dg = [(f, [t for t, _ in deps]) for f, deps in wdg]

        return wdg, dg, transport_graph

    def generate(self, output: str):
        wdg, dg, transport_graph = self.build_graph_v6()

        # Build module map
        mods = []
        for m in self.modules:
            # Serialize HTTP methods
            methods_serializable = {}
            for method_id, method_info in m.http_methods.items():
                methods_serializable[method_id] = {
                    "name": method_info.name,
                    "is_async": method_info.is_async,
                    "parameters": method_info.parameters,
                    "returns": method_info.returns,
                    "has_sync_twin": method_info.has_sync_twin,
                }

            mod_entry = (
                m.pri,
                m.size,
                m.exports,
                m.imports,
                m.is_async_module,
                m.has_sync_twin,
                m.transport_layer,
                methods_serializable,
            )
            mods.append(mod_entry)

        bundle = {
            "V": 6,
            "F": "httpx",
            "S": self.strs,
            "Y": self.syms,
            "M": mods,
            "W": wdg,
            "D": dg,
            "C": {i: m.src for i, m in enumerate(self.modules) if m.src},
            "T": TRANSPORT_LAYERS,
            "A": DUALITY_PATTERN,
            "P": HTTP_PROTOCOL_STACK,
            "R": transport_graph,
            "t": {
                "f": len(self.modules),
                "l": self.stats["lines"],
                **{k: self.stats[k] for k in ["c", "h", "n", "l", "s"]},
                "version": 6,
                "framework": "httpx",
                "async_sync_duality": True,
            },
        }

        json_str = json.dumps(bundle, separators=(",", ":"))
        out = self.root / output
        out.write_text(json_str)

        raw = len(json_str)
        comp = len(zlib.compress(json_str.encode(), 9))

        print(f"\n{'=' * 50}")
        print(
            f"CALYX-HTTPX v6.0: {len(self.modules)} modules, {self.stats['lines']} lines"
        )
        print(f"Symbols: {len(self.syms)} | Strings: {len(self.strs)}")
        print(f"Async/Sync Duality: True")
        print(
            f"Raw: {raw / 1024:.1f} KB | Compressed: {comp / 1024:.1f} KB ({comp / raw * 100:.1f}%)"
        )
        print(f"{'=' * 50}")


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".")
    p.add_argument("--output", default="calyx_httpx_v6.json")
    p.add_argument("--max-lines", type=int, default=30000)
    args = p.parse_args()

    b = CalyxHTTPXBundlerV6(args.root, args.max_lines)
    b.discover()
    b.generate(args.output)


if __name__ == "__main__":
    main()
