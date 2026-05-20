#!/usr/bin/env python3
"""
CALYX-GRIFFE BUNDLER v6.0 - Static Analysis Framework IR
Treats Griffe as a Python introspection tool with visitor/inspector dual agents
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
# CONFIGURATION: GRIFFE-SPECIFIC
# ============================================================================

CORE_CLASSES = {
    "GriffeLoader",  # Main loader
    "Object",  # Base object
    "Module",  # Module object
    "Class",  # Class object
    "Function",  # Function object
    "Attribute",  # Attribute object
    "TypeAlias",  # Type alias
    "Alias",  # Alias object
    "Parameter",  # Function parameter
    "Decorator",  # Decorator
    "Docstring",  # Docstring
}

AGENT_TYPES = {
    "visitor": "AST-based static analysis (visit)",
    "inspector": "Runtime introspection (inspect)",
}

OBJECT_KINDS = {
    "MODULE": "Python module",
    "CLASS": "Python class",
    "FUNCTION": "Python function",
    "ATTRIBUTE": "Python attribute",
    "ALIAS": "Import alias",
    "TYPE_ALIAS": "Type alias",
}

DOCSTRING_STYLES = {
    "google": "Google-style docstrings",
    "numpy": "NumPy-style docstrings",
    "sphinx": "Sphinx-style docstrings",
}

HIGH_PRIORITY = {
    "loader.py",
    "models.py",
    "visitor.py",
    "inspector.py",
    "__init__.py",
}

LOW_PRIORITY_PATTERNS = {
    "tests/",
    "test_",
    "docs/",
}

# ============================================================================
# V6: DUAL AGENT SYSTEM
# ============================================================================

DUAL_AGENT_PATTERN = {
    "visitor": {
        "method": "visit()",
        "input": "Source code (AST)",
        "process": "Parse AST → Build Object tree",
        "pros": ["Fast", "No execution", "Works on any code"],
        "cons": ["Limited to static info", "Can't resolve runtime values"],
        "use_case": "Documentation generation from source",
    },
    "inspector": {
        "method": "inspect()",
        "input": "Imported module (runtime)",
        "process": "Import → Introspect → Build Object tree",
        "pros": ["Complete info", "Resolves runtime values", "Gets C extensions"],
        "cons": ["Requires import", "Executes code", "Platform-specific"],
        "use_case": "Analyzing installed packages",
    },
    "hybrid": {
        "strategy": "Try visitor first, fall back to inspector",
        "controlled_by": "allow_inspection=True, force_inspection=False",
    },
}

# ============================================================================
# V6: OBJECT TREE STRUCTURE
# ============================================================================

OBJECT_TREE = {
    "hierarchy": {
        "Module": {
            "children": ["Class", "Function", "Attribute", "TypeAlias"],
            "can_contain": "Any object",
        },
        "Class": {
            "children": ["Class", "Function", "Attribute"],
            "special": "Can be nested",
        },
        "Function": {
            "children": ["Function"],
            "special": "Can have nested functions",
        },
        "Attribute": {
            "children": [],
            "special": "Leaf node",
        },
    },
    "navigation": {
        "parent": "object.parent → parent Object",
        "members": "object.members → dict of children",
        "resolve": "object.resolve(name) → Object or Alias",
    },
}

# ============================================================================
# V6: SIGNATURE EXTRACTION
# ============================================================================

SIGNATURE_COMPONENTS = {
    "parameters": {
        "name": "Parameter name",
        "annotation": "Type hint (Optional)",
        "kind": "positional, keyword, var_positional, var_keyword",
        "default": "Default value (Optional)",
    },
    "returns": {
        "annotation": "Return type hint",
    },
    "decorators": {
        "value": "Decorator expression",
        "lineno": "Line number",
    },
}

# ============================================================================
# V6: DOCSTRING PARSING
# ============================================================================

DOCSTRING_SECTIONS = {
    "google": ["Args", "Returns", "Raises", "Yields", "Examples", "Attributes", "Note"],
    "numpy": [
        "Parameters",
        "Returns",
        "Raises",
        "Yields",
        "Examples",
        "Attributes",
        "See Also",
    ],
    "sphinx": [":param", ":type", ":return", ":rtype", ":raises"],
}

# ============================================================================
# V6: EXTENSION SYSTEM
# ============================================================================

EXTENSION_HOOKS = {
    "on_module_loaded": "Called after module is loaded",
    "on_class_loaded": "Called after class is loaded",
    "on_function_loaded": "Called after function is loaded",
    "on_attribute_loaded": "Called after attribute is loaded",
}

# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class GriffeObject:
    """Griffe object metadata"""

    name: str
    kind: str  # MODULE, CLASS, FUNCTION, ATTRIBUTE, ALIAS
    has_docstring: bool
    has_type_hints: bool
    is_public: bool
    lineno: Optional[int] = None


@dataclass
class SignatureInfo:
    """Function/method signature"""

    name: str
    parameters: List[str]
    return_annotation: Optional[str]
    decorators: List[str]
    is_async: bool
    is_method: bool
    is_classmethod: bool
    is_staticmethod: bool


@dataclass
class ModuleV6:
    pri: int
    size: int
    exports: List[int]
    imports: List[int]
    griffe_objects: Dict[int, GriffeObject] = field(default_factory=dict)
    signatures: Dict[int, SignatureInfo] = field(default_factory=dict)
    uses_visitor: bool = False
    uses_inspector: bool = False
    has_docstring_parsing: bool = False
    src: Optional[str] = None


# ============================================================================
# NODE ROLES
# ============================================================================


class NodeRole(IntFlag):
    """Griffe component roles"""

    LOADER = 1 << 0  # Loader logic
    AGENT = 1 << 1  # Visitor or Inspector
    MODEL = 1 << 2  # Object models
    PARSER = 1 << 3  # Docstring parser
    EXTENSION = 1 << 4  # Extension system
    FINDER = 1 << 5  # Module finder


# ============================================================================
# MAIN BUNDLER CLASS
# ============================================================================


class CalyxGriffeBundlerV6:
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
        """Initialize Griffe core symbols"""
        for cls in CORE_CLASSES:
            self.intern_sym(cls)
        for kind in OBJECT_KINDS.keys():
            self.intern_sym(kind)

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

    def extract_griffe_objects(self, src: str) -> Dict[str, GriffeObject]:
        """Extract Griffe object model instances"""
        objects = {}

        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    # Check if it's a Griffe object type
                    for base in node.bases:
                        if isinstance(base, ast.Name) and base.id == "Object":
                            kind = "OBJECT"
                            if node.name == "Module":
                                kind = "MODULE"
                            elif node.name == "Class":
                                kind = "CLASS"
                            elif node.name == "Function":
                                kind = "FUNCTION"
                            elif node.name == "Attribute":
                                kind = "ATTRIBUTE"

                            # Check for docstring
                            has_docstring = False
                            if node.body and isinstance(node.body[0], ast.Expr):
                                if isinstance(node.body[0].value, ast.Constant):
                                    has_docstring = True

                            objects[node.name] = GriffeObject(
                                name=node.name,
                                kind=kind,
                                has_docstring=has_docstring,
                                has_type_hints=False,
                                is_public=not node.name.startswith("_"),
                                lineno=node.lineno,
                            )
        except SyntaxError:
            pass

        return objects

    def extract_signatures(self, src: str) -> Dict[str, SignatureInfo]:
        """Extract function signatures"""
        signatures = {}

        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func_name = node.name

                    # Extract parameters
                    params = [arg.arg for arg in node.args.args]

                    # Extract decorators
                    decorators = []
                    for dec in node.decorator_list:
                        if isinstance(dec, ast.Name):
                            decorators.append(dec.id)
                        elif isinstance(dec, ast.Attribute):
                            decorators.append(dec.attr)

                    # Check method type
                    is_method = False
                    is_classmethod = False
                    is_staticmethod = False

                    if params and params[0] in ("self", "cls"):
                        is_method = True
                        if params[0] == "cls" or "classmethod" in decorators:
                            is_classmethod = True

                    if "staticmethod" in decorators:
                        is_staticmethod = True

                    # Return annotation
                    return_annotation = None
                    if node.returns:
                        if isinstance(node.returns, ast.Name):
                            return_annotation = node.returns.id

                    signatures[func_name] = SignatureInfo(
                        name=func_name,
                        parameters=params,
                        return_annotation=return_annotation,
                        decorators=decorators,
                        is_async=isinstance(node, ast.AsyncFunctionDef),
                        is_method=is_method,
                        is_classmethod=is_classmethod,
                        is_staticmethod=is_staticmethod,
                    )
        except SyntaxError:
            pass

        return signatures

    def detect_visitor_usage(self, src: str) -> bool:
        """Detect visitor agent usage"""
        markers = ["visit(", "ast.NodeVisitor", "def visit_"]
        return any(marker in src for marker in markers)

    def detect_inspector_usage(self, src: str) -> bool:
        """Detect inspector agent usage"""
        markers = ["inspect(", "getattr(", "inspect."]
        return any(marker in src for marker in markers)

    def detect_docstring_parsing(self, src: str) -> bool:
        """Detect docstring parsing"""
        markers = ["parse_docstring", "google", "numpy", "sphinx", "DocstringStyle"]
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

        # Check for core classes
        for cls in CORE_CLASSES:
            if re.search(rf"class\s+{cls}\b", src):
                return 1

        # Agent implementations
        if "visitor" in p or "inspector" in p:
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

        # Extract Griffe-specific data
        griffe_objects_map = self.extract_griffe_objects(src)
        griffe_objects_dict = {}
        for obj_name, obj_info in griffe_objects_map.items():
            obj_id = self.intern_sym(obj_name)
            griffe_objects_dict[obj_id] = obj_info

        signatures_map = self.extract_signatures(src)
        signatures_dict = {}
        for sig_name, sig_info in signatures_map.items():
            sig_id = self.intern_sym(sig_name)
            signatures_dict[sig_id] = sig_info

        uses_visitor = self.detect_visitor_usage(src)
        uses_inspector = self.detect_inspector_usage(src)
        has_docstring = self.detect_docstring_parsing(src)

        return ModuleV6(
            pri=pri,
            size=lines,
            exports=exp_ids,
            imports=self.extract_imports_v6(src),
            griffe_objects=griffe_objects_dict,
            signatures=signatures_dict,
            uses_visitor=uses_visitor,
            uses_inspector=uses_inspector,
            has_docstring_parsing=has_docstring,
            src=self.minify_python(src) if pri <= 2 else None,
        )

    def discover(self):
        all_mods = []

        # Find Griffe source
        src_dir = self.root / "packages" / "griffelib" / "src" / "griffe"
        if not src_dir.exists():
            src_dir = self.root / "src" / "griffe"
        if not src_dir.exists():
            src_dir = self.root / "griffe"
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
        """Build dependency + agent graph"""
        weights: Dict[int, Dict[int, int]] = {i: {} for i in range(len(self.modules))}
        agent_graph: Dict[int, Dict[int, List[str]]] = {
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

                            # Track agent usage
                            if token in CORE_CLASSES:
                                agent_graph[mid][dep] = agent_graph[mid].get(
                                    dep, []
                                ) + ["uses_griffe_model"]

        def bucket_weight(w: int) -> int:
            return 3 if w >= 10 else 2 if w >= 5 else 1

        wdg = [
            (f, [(t, bucket_weight(w)) for t, w in deps.items()])
            for f, deps in weights.items()
            if deps
        ]
        dg = [(f, [t for t, _ in deps]) for f, deps in wdg]

        return wdg, dg, agent_graph

    def generate(self, output: str):
        wdg, dg, agent_graph = self.build_graph_v6()

        # Build module map
        mods = []
        for m in self.modules:
            # Serialize Griffe objects
            objects_serializable = {}
            for obj_id, obj_info in m.griffe_objects.items():
                objects_serializable[obj_id] = {
                    "name": obj_info.name,
                    "kind": obj_info.kind,
                    "has_docstring": obj_info.has_docstring,
                    "has_type_hints": obj_info.has_type_hints,
                    "is_public": obj_info.is_public,
                    "lineno": obj_info.lineno,
                }

            # Serialize signatures
            sigs_serializable = {}
            for sig_id, sig_info in m.signatures.items():
                sigs_serializable[sig_id] = {
                    "name": sig_info.name,
                    "parameters": sig_info.parameters,
                    "return_annotation": sig_info.return_annotation,
                    "decorators": sig_info.decorators,
                    "is_async": sig_info.is_async,
                    "is_method": sig_info.is_method,
                }

            mod_entry = (
                m.pri,
                m.size,
                m.exports,
                m.imports,
                objects_serializable,
                sigs_serializable,
                m.uses_visitor,
                m.uses_inspector,
                m.has_docstring_parsing,
            )
            mods.append(mod_entry)

        bundle = {
            "V": 6,
            "F": "griffe",
            "S": self.strs,
            "Y": self.syms,
            "M": mods,
            "W": wdg,
            "D": dg,
            "C": {i: m.src for i, m in enumerate(self.modules) if m.src},
            "AGT": DUAL_AGENT_PATTERN,
            "OBJ": OBJECT_TREE,
            "SIG": SIGNATURE_COMPONENTS,
            "DOC": DOCSTRING_SECTIONS,
            "EXT": EXTENSION_HOOKS,
            "R": agent_graph,
            "t": {
                "f": len(self.modules),
                "l": self.stats["lines"],
                **{k: self.stats[k] for k in ["c", "h", "n", "l", "s"]},
                "version": 6,
                "framework": "griffe",
                "dual_agent": True,
            },
        }

        json_str = json.dumps(bundle, separators=(",", ":"))
        out = self.root / output
        out.write_text(json_str)

        raw = len(json_str)
        comp = len(zlib.compress(json_str.encode(), 9))

        print(f"\n{'=' * 50}")
        print(
            f"CALYX-GRIFFE v6.0: {len(self.modules)} modules, {self.stats['lines']} lines"
        )
        print(f"Symbols: {len(self.syms)} | Strings: {len(self.strs)}")
        print(f"Dual Agent System: Visitor + Inspector")
        print(
            f"Raw: {raw / 1024:.1f} KB | Compressed: {comp / 1024:.1f} KB ({comp / raw * 100:.1f}%)"
        )
        print(f"{'=' * 50}")


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--root", default="./griffe")
    p.add_argument("--output", default="calyx_griffe_v6.json")
    p.add_argument("--max-lines", type=int, default=30000)
    args = p.parse_args()

    b = CalyxGriffeBundlerV6(args.root, args.max_lines)
    b.discover()
    b.generate(args.output)


if __name__ == "__main__":
    main()
