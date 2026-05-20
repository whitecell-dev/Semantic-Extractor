#!/usr/bin/env python3
"""
CALYX-PLAYWRIGHT v7.0 - Browser Automation IR
Maps Playwright's actionability protocol and ownership hierarchy for LLM generation
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
# V7 CONFIGURATION: PLAYWRIGHT-SPECIFIC (Browser Automation)
# ============================================================================

# The Playwright Trinity: Ownership + Actionability
CORE_SYMBOLS = {
    "browser",  # Browser instance (Chromium/Firefox/WebKit)
    "context",  # BrowserContext (isolated session)
    "page",  # Page (tab with DOM)
    "locator",  # Locator (wait-for + action proxy)
    "frame",  # Frame (iframe support)
    "selectors",  # Selector engine
    "expect",  # Assertion helper
    "playwright",  # Playwright entry point
}

CORE_CLASSES = {
    "Playwright",  # Main entry point
    "Browser",  # Browser process
    "BrowserContext",  # Isolated session (cookies, storage)
    "Page",  # Tab/DOM container
    "Locator",  # Element pointer with auto-waiting
    "Frame",  # IFrame handler
    "JSHandle",  # JavaScript object reference
    "ElementHandle",  # Raw element reference
    "APIRequestContext",  # API testing
    "CDPSession",  # Chrome DevTools Protocol
    "Response",  # Network response
    "Request",  # Network request
    "Route",  # Request interception
    "WebSocket",  # WebSocket connection
    "Worker",  # WebWorker
}

CORE_TYPES = {
    "Actionability",  # Visible, stable, enabled, editable
    "SelectorEngine",  # CSS, XPath, text, role
    "WaitForOptions",  # Timeout, state
    "LocatorOptions",  # Has, filter
    "Assertion",  # expect().to_...
    "Trace",  # Trace viewer
    "Screenshot",  # Screenshot options
}

HIGH_PRIORITY = {
    "playwright/async_api/__init__.py",  # Primary API
    "playwright/_impl/_locator.py",  # Locator logic (self-healing)
    "playwright/_impl/_page.py",  # Page actions
    "playwright/_impl/_browser_context.py",  # Context management
    "playwright/_impl/_assertions.py",  # Expect API
    "playwright/sync_api/__init__.py",  # Sync wrapper
}

LOW_PRIORITY_PATTERNS = {
    "tests/",
    "test_",
    "_generated.py",
    "driver/",
    "third_party/",
    "network/",  # Network internals (noise)
}

# ============================================================================
# V7: NODE ROLES (Browser Automation Hierarchy)
# ============================================================================


class NodeRole(IntFlag):
    """Role in the Playwright automation tree"""

    ENGINE = 1 << 0  # Playwright manager (launch/connect)
    CONTEXT = 1 << 1  # BrowserContext (session isolation)
    PAGE = 1 << 2  # Page (DOM container)
    LOCATOR = 1 << 3  # Locator (element pointer)
    ACTION = 1 << 4  # Action (click, fill, check)
    ASSERTION = 1 << 5  # Assertion (expect().to_...)
    FRAME = 1 << 6  # Frame (iframe navigation)
    NETWORK = 1 << 7  # Network interception
    WAIT = 1 << 8  # Wait condition
    QUERY = 1 << 9  # Query selector


# ============================================================================
# V7: ACTIONABILITY INVARIANTS (Wait-to-Act Protocol)
# ============================================================================

ACTIONABILITY_INVARIANTS = {
    "click": {
        "pre_conditions": ["visible", "stable", "enabled"],
        "auto_wait": True,
        "retry_on": ["stale_element", "intercepted"],
        "timeout_ms": 30000,
    },
    "fill": {
        "pre_conditions": ["visible", "enabled", "editable"],
        "auto_wait": True,
        "retry_on": ["readonly", "disabled"],
        "timeout_ms": 30000,
    },
    "check": {
        "pre_conditions": ["visible", "enabled", "checkable"],
        "auto_wait": True,
        "retry_on": ["already_checked"],
        "timeout_ms": 30000,
    },
    "hover": {
        "pre_conditions": ["visible", "stable"],
        "auto_wait": True,
        "retry_on": ["hidden"],
        "timeout_ms": 30000,
    },
    "select_option": {
        "pre_conditions": ["visible", "enabled"],
        "auto_wait": True,
        "retry_on": ["no_such_option"],
        "timeout_ms": 30000,
    },
    "wait_for": {
        "pre_conditions": [],
        "auto_wait": False,
        "types": ["selector", "function", "timeout", "navigation"],
    },
}

# ============================================================================
# V7: EVENT CONTEXT EDGES
# ============================================================================

EVENT_EDGES = [
    # Ownership hierarchy (strict)
    ("Playwright", "Browser", "launches"),
    ("Browser", "BrowserContext", "creates"),
    ("BrowserContext", "Page", "opens_tab"),
    ("Page", "Frame", "contains"),
    ("Page", "Locator", "queries"),
    # Event-driven relationships
    ("Page", "wait_for_event('popup')", "triggers_new_page"),
    ("Page", "on('request')", "monitors_network"),
    ("Page", "on('response')", "captures_response"),
    ("Page", "on('dialog')", "handles_alert"),
    ("Page", "on('console')", "captures_log"),
    ("Page", "on('download')", "triggers_download"),
    # Context sharing
    ("BrowserContext", "Page", "shares_storage"),
    ("BrowserContext", "APIRequestContext", "shares_session"),
    # Assertion flow
    ("Locator", "expect", "asserts_state"),
    ("expect", "to_be_visible", "verifies"),
    ("expect", "to_have_text", "validates"),
    # Action flow
    ("Locator", "click", "performs_action"),
    ("Page", "goto", "navigates"),
    ("Frame", "locator", "queries_in_iframe"),
]

# ============================================================================
# V7: MIDDLEWARE PATTERNS (Async/Sync Dualism)
# ============================================================================

PLAYWRIGHT_PATTERNS = {
    "async_api": {
        "signature": "async with async_playwright() as p:",
        "context_manager": True,
        "entry_point": "playwright.async_api",
    },
    "sync_api": {
        "signature": "with sync_playwright() as p:",
        "context_manager": True,
        "entry_point": "playwright.sync_api",
    },
    "locator_chain": {
        "methods": [
            "get_by_role",
            "get_by_text",
            "get_by_label",
            "get_by_placeholder",
            "get_by_alt_text",
            "get_by_title",
            "get_by_test_id",
        ],
        "returns": "Locator",
        "is_chainable": True,
    },
    "action_method": {
        "methods": [
            "click",
            "fill",
            "check",
            "uncheck",
            "hover",
            "select_option",
            "press",
            "type",
            "focus",
            "blur",
            "clear",
        ],
        "pre_conditions": ["wait_for", "scroll_into_view"],
        "is_async": True,
    },
}

# ============================================================================
# V7: ROUTE PATTERNS (Page Navigation & State)
# ============================================================================

PAGE_PATTERNS = {
    "goto": {
        "params": ["url"],
        "options": ["wait_until", "timeout", "referer"],
        "wait_states": ["load", "domcontentloaded", "networkidle", "commit"],
    },
    "reload": {
        "options": ["wait_until", "timeout"],
    },
    "go_back": {},
    "go_forward": {},
    "set_content": {
        "params": ["html"],
        "options": ["wait_until", "timeout"],
    },
}

QUERY_PATTERNS = {
    "query_selector": {
        "returns": "ElementHandle",
        "auto_wait": False,
    },
    "query_selector_all": {
        "returns": "List[ElementHandle]",
        "auto_wait": False,
    },
    "locator": {
        "returns": "Locator",
        "auto_wait": True,
        "is_primary": True,
    },
    "frame_locator": {
        "params": ["selector"],
        "returns": "FrameLocator",
    },
    "get_by_role": {
        "params": ["role"],
        "options": [
            "name",
            "checked",
            "disabled",
            "exact",
            "expanded",
            "includeHidden",
            "level",
            "pressed",
            "selected",
        ],
    },
}

# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class ActionabilitySignature:
    """Playwright actionability protocol"""

    name: str
    pre_conditions: List[str]
    auto_wait: bool
    retry_on: List[str]
    is_async: bool
    returns: Optional[str]
    timeout_ms: int


@dataclass
class ModuleV7:
    pri: int
    size: int
    exports: List[int]  # symbol IDs
    imports: List[int]  # string IDs
    node_role: int = NodeRole.ENGINE
    action_signatures: Dict[int, ActionabilitySignature] = field(default_factory=dict)
    composition_patterns: Dict[int, str] = field(default_factory=dict)
    src: Optional[str] = None


# ============================================================================
# MAIN BUNDLER CLASS
# ============================================================================


class CalyxPlaywrightBundlerV7:
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

        self.modules: List[ModuleV7] = []
        self.sym_to_mods: Dict[int, List[int]] = defaultdict(list)

        self.stats = {"c": 0, "h": 0, "n": 0, "l": 0, "s": 0, "lines": 0}

        # V7: Playwright-specific storage
        self.action_invariants = ACTIONABILITY_INVARIANTS
        self.event_edges = EVENT_EDGES
        self.playwright_patterns = PLAYWRIGHT_PATTERNS
        self.page_patterns = PAGE_PATTERNS
        self.query_patterns = QUERY_PATTERNS

    def _init_symbols(self):
        """Initialize core Playwright symbols"""
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
        """Python-aware minification preserving async/await"""
        # Remove docstrings
        src = re.sub(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', "", src)

        lines = []
        for line in src.split("\n"):
            # Preserve async def, context managers
            if any(
                pattern in line
                for pattern in ["async def", "with ", "async with", "def "]
            ):
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

    def extract_action_signature(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> Optional[ActionabilitySignature]:
        """Extract Playwright actionability protocol"""
        name = node.name
        is_async = isinstance(node, ast.AsyncFunctionDef)

        # Check if this is a known action
        if name in self.action_invariants:
            inv = self.action_invariants[name]
            return ActionabilitySignature(
                name=name,
                pre_conditions=inv["pre_conditions"],
                auto_wait=inv["auto_wait"],
                retry_on=inv.get("retry_on", []),
                is_async=is_async,
                returns=None,
                timeout_ms=inv.get("timeout_ms", 30000),
            )

        # Check for locator chain methods
        if name in self.playwright_patterns["locator_chain"]["methods"]:
            return ActionabilitySignature(
                name=name,
                pre_conditions=[],
                auto_wait=True,
                retry_on=[],
                is_async=is_async,
                returns="Locator",
                timeout_ms=30000,
            )

        return None

    def extract_node_role(self, src: str, class_name: Optional[str] = None) -> int:
        """Determine node role from Playwright hierarchy"""
        role = NodeRole.ENGINE  # Default

        # Check for Context
        if re.search(r"class\s+\w+.*BrowserContext", src) or "BrowserContext" in src:
            role |= NodeRole.CONTEXT

        # Check for Page
        if re.search(r"class\s+\w+.*Page", src) or "Page" in src and "def goto" in src:
            role |= NodeRole.PAGE

        # Check for Locator
        if re.search(r"class\s+\w+.*Locator", src) or "get_by_" in src:
            role |= NodeRole.LOCATOR

        # Check for Frame
        if re.search(r"class\s+\w+.*Frame", src):
            role |= NodeRole.FRAME

        # Check for Action methods
        if any(action in src for action in self.action_invariants.keys()):
            role |= NodeRole.ACTION

        # Check for Assertion
        if "expect" in src and "to_" in src:
            role |= NodeRole.ASSERTION

        # Check for Network
        if "route" in src and "intercept" in src:
            role |= NodeRole.NETWORK

        # Check for Wait
        if "wait_for" in src or "wait_until" in src:
            role |= NodeRole.WAIT

        return role

    def extract_composition_patterns(self, src: str) -> Dict[int, str]:
        """Extract Playwright composition patterns"""
        patterns = {}

        # Check for async context manager pattern
        if "async_playwright()" in src:
            async_id = self.intern_sym("async_playwright")
            patterns[async_id] = "async_context"

        # Check for sync context manager pattern
        if "sync_playwright()" in src:
            sync_id = self.intern_sym("sync_playwright")
            patterns[sync_id] = "sync_context"

        # Check for locator chain
        for method in self.playwright_patterns["locator_chain"]["methods"]:
            if f".{method}(" in src:
                locator_id = self.intern_sym(method)
                patterns[locator_id] = "locator_chain"

        # Check for event listeners
        if ".on(" in src:
            event_id = self.intern_sym("on")
            patterns[event_id] = "event_listener"

        return patterns

    def extract_exports_v7(self, src: str) -> List[Tuple[str, str]]:
        """Extract exports with their type"""
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

    def extract_action_signatures_from_ast(
        self, src: str
    ) -> Dict[str, ActionabilitySignature]:
        """Extract actionability signatures"""
        signatures = {}

        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sig = self.extract_action_signature(node)
                    if sig:
                        signatures[node.name] = sig
        except SyntaxError:
            pass

        return signatures

    def extract_imports_v7(self, src: str) -> List[int]:
        """Extract Playwright-specific imports"""
        imports = []

        for m in re.findall(r"^\s*import\s+(\w+)", src, re.MULTILINE)[:10]:
            imports.append(self.intern_str(m))

        for m in re.findall(r"^\s*from\s+(\S+)\s+import", src, re.MULTILINE)[:10]:
            # Prioritize playwright imports
            if "playwright" in m:
                imports.insert(0, self.intern_str(m))
            else:
                imports.append(self.intern_str(m))

        return imports

    def priority(self, path: Path, src: str) -> int:
        p = str(path)

        # High priority for core Playwright files
        if any(h in p for h in HIGH_PRIORITY):
            return 1

        # Check for core classes
        for cls in CORE_CLASSES:
            if re.search(rf"class\s+{cls}\b", src):
                return 1

        # Check for locator logic (self-healing)
        if "get_by_" in src and "Locator" in src:
            return 1

        # Check for action methods
        if any(action in src for action in self.action_invariants.keys()):
            return 2

        # High export count
        if src.count("class ") + src.count("async def ") > 10:
            return 2

        # Low priority patterns
        for pat in LOW_PRIORITY_PATTERNS:
            if pat.lower() in p.lower():
                return 4

        return 3

    def analyze(self, path: Path) -> Optional[ModuleV7]:
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

        exports = self.extract_exports_v7(src)
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

        # V7: Extract action signatures
        signatures_map = self.extract_action_signatures_from_ast(src)
        signatures_dict = {}
        for func_name, sig in signatures_map.items():
            func_id = self.intern_sym(func_name)
            signatures_dict[func_id] = sig

        # V7: Extract composition patterns
        composition_patterns = self.extract_composition_patterns(src)

        # V7: Determine node role
        node_role = self.extract_node_role(src)

        return ModuleV7(
            pri=pri,
            size=lines,
            exports=exp_ids,
            imports=self.extract_imports_v7(src),
            node_role=node_role,
            action_signatures=signatures_dict,
            composition_patterns=composition_patterns,
            src=self.minify_python(src) if pri <= 2 else None,
        )

    def discover(self):
        all_mods = []

        # Find all Python files in playwright directory
        src_dir = self.root / "playwright"
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

    def build_graph_v7(self) -> Tuple[List, List, Dict]:
        """Build dependency graph + ownership hierarchy"""
        weights: Dict[int, Dict[int, int]] = {i: {} for i in range(len(self.modules))}
        ownership_tree: Dict[int, Dict[int, List[str]]] = {
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

                            # Track ownership hierarchy
                            if token in CORE_CLASSES:
                                ownership_tree[mid][dep] = ownership_tree[mid].get(
                                    dep, []
                                ) + ["owns"]

                            # Track event relationships
                            if token in ["on", "wait_for_event"]:
                                ownership_tree[mid][dep] = ownership_tree[mid].get(
                                    dep, []
                                ) + ["event_listener"]

        def bucket_weight(w: int) -> int:
            return 3 if w >= 10 else 2 if w >= 5 else 1

        wdg = [
            (f, [(t, bucket_weight(w)) for t, w in deps.items()])
            for f, deps in weights.items()
            if deps
        ]
        dg = [(f, [t for t, _ in deps]) for f, deps in wdg]

        return wdg, dg, ownership_tree

    def generate(self, output: str):
        wdg, dg, ownership_tree = self.build_graph_v7()

        # Build module map
        mods = []
        for m in self.modules:
            # Convert ActionabilitySignature to serializable format
            sigs_serializable = {}
            for func_id, sig in m.action_signatures.items():
                sigs_serializable[func_id] = {
                    "name": sig.name,
                    "pre_conditions": sig.pre_conditions,
                    "auto_wait": sig.auto_wait,
                    "retry_on": sig.retry_on,
                    "is_async": sig.is_async,
                    "returns": sig.returns,
                    "timeout_ms": sig.timeout_ms,
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
            "V": 7,
            "F": "playwright",
            "S": self.strs,
            "Y": self.syms,
            "M": mods,
            "W": wdg,
            "D": dg,
            "C": {i: m.src for i, m in enumerate(self.modules) if m.src},
            "I": self.action_invariants,
            "P": self.playwright_patterns,
            "T": self.page_patterns,
            "Q": self.query_patterns,
            "R": ownership_tree,
            "E": self.event_edges,
            "t": {
                "f": len(self.modules),
                "l": self.stats["lines"],
                **{k: self.stats[k] for k in ["c", "h", "n", "l", "s"]},
                "version": 7,
                "framework": "playwright",
                "actionability_protocol": True,
                "async_sync_dual": True,
            },
        }

        json_str = json.dumps(bundle, separators=(",", ":"))
        out = self.root / output
        out.write_text(json_str)

        raw = len(json_str)
        comp = len(zlib.compress(json_str.encode(), 9))

        print(f"\n{'=' * 50}")
        print(
            f"CALYX-PLAYWRIGHT v7.0: {len(self.modules)} modules, {self.stats['lines']} lines"
        )
        print(f"Symbols: {len(self.syms)} | Strings: {len(self.strs)}")
        print(f"Actionability Protocol: True")
        print(f"Async/Sync Dualism: True")
        print(
            f"Raw: {raw / 1024:.1f} KB | Compressed: {comp / 1024:.1f} KB ({comp / raw * 100:.1f}%)"
        )
        print(f"{'=' * 50}")


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--root", default="./playwright")
    p.add_argument("--output", default="calyx_playwright_v7.json")
    p.add_argument("--max-lines", type=int, default=30000)
    args = p.parse_args()

    b = CalyxPlaywrightBundlerV7(args.root, args.max_lines)
    b.discover()
    b.generate(args.output)


if __name__ == "__main__":
    main()
