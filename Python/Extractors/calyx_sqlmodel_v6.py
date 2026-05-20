#!/usr/bin/env python3
"""
CALYX-SQLMODEL BUNDLER v6.0 - Type-Safe ORM Bridge IR
Treats SQLModel as a Pydantic+SQLAlchemy hybrid with dual model inheritance
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
# CONFIGURATION: SQLMODEL-SPECIFIC
# ============================================================================

CORE_CLASSES = {
    "SQLModel",  # Base model class
    "Field",  # Field definition
    "Relationship",  # Relationship definition
    "Session",  # Database session
    "select",  # Query builder
    "create_engine",  # Engine factory
}

PYDANTIC_INTEGRATION = {
    "BaseModel",  # Pydantic base
    "FieldInfo",  # Field metadata
    "validator",  # Validation decorator
    "field_validator",  # Pydantic v2 validator
    "model_validator",  # Model-level validator
}

SQLALCHEMY_INTEGRATION = {
    "Column",  # SQLAlchemy column
    "Integer",  # Integer type
    "String",  # String type
    "Boolean",  # Boolean type
    "DateTime",  # DateTime type
    "ForeignKey",  # Foreign key
    "relationship",  # SQLAlchemy relationship
    "Mapped",  # Type annotation
}

TYPE_MAPPINGS = {
    "int": "Integer",
    "str": "String",
    "bool": "Boolean",
    "float": "Float",
    "datetime": "DateTime",
    "date": "Date",
    "UUID": "Uuid",
    "Decimal": "Numeric",
}

HIGH_PRIORITY = {
    "main.py",
    "__init__.py",
    "expression.py",
}

LOW_PRIORITY_PATTERNS = {
    "tests/",
    "test_",
    "docs/",
    "docs_src/",
}

# ============================================================================
# V6: DUAL INHERITANCE MODEL
# ============================================================================

DUAL_INHERITANCE = {
    "pydantic_side": {
        "base": "BaseModel",
        "provides": [
            "Validation",
            "Serialization (model_dump, model_dump_json)",
            "Parsing (model_validate, model_validate_json)",
            "JSON Schema generation",
        ],
        "methods": ["model_dump", "model_validate", "model_fields"],
    },
    "sqlalchemy_side": {
        "base": "DeclarativeMeta",
        "provides": [
            "Table mapping",
            "ORM queries",
            "Database persistence",
            "Relationships",
        ],
        "methods": ["__tablename__", "__table__", "metadata"],
    },
    "sqlmodel_bridge": {
        "metaclass": "SQLModelMetaclass",
        "inherits_from": ["ModelMetaclass", "DeclarativeMeta"],
        "resolves_conflict": "Multiple inheritance resolution via custom metaclass",
    },
}

# ============================================================================
# V6: TABLE VS NON-TABLE MODELS
# ============================================================================

MODEL_TYPES = {
    "table_model": {
        "definition": "SQLModel with table=True",
        "purpose": "Database table representation",
        "has_table": True,
        "has_primary_key": True,
        "example": "class Hero(SQLModel, table=True):",
    },
    "data_model": {
        "definition": "SQLModel without table=True",
        "purpose": "Pydantic validation only (DTOs, API schemas)",
        "has_table": False,
        "has_primary_key": False,
        "example": "class HeroCreate(SQLModel):",
    },
    "relationship_pattern": {
        "parent": "Hero (table=True)",
        "child": "Team (table=True)",
        "link": "Relationship(back_populates=...)",
        "foreign_key": "Field(foreign_key='team.id')",
    },
}

# ============================================================================
# V6: FIELD SYSTEM
# ============================================================================

FIELD_SYSTEM = {
    "field_function": {
        "signature": "Field(default=..., primary_key=False, foreign_key=None, ...)",
        "combines": ["Pydantic FieldInfo", "SQLAlchemy Column"],
        "parameters": {
            "default": "Default value (Pydantic)",
            "default_factory": "Factory function (Pydantic)",
            "primary_key": "Primary key flag (SQLAlchemy)",
            "foreign_key": "Foreign key reference (SQLAlchemy)",
            "index": "Create index (SQLAlchemy)",
            "unique": "Unique constraint (SQLAlchemy)",
            "nullable": "NULL allowed (SQLAlchemy)",
            "sa_column": "Override SQLAlchemy column",
        },
    },
    "relationship_function": {
        "signature": "Relationship(back_populates=..., link_model=...)",
        "purpose": "Define relationships between models",
        "parameters": {
            "back_populates": "Reverse relationship name",
            "link_model": "Association table for many-to-many",
            "sa_relationship": "Override SQLAlchemy relationship",
        },
    },
}

# ============================================================================
# V6: QUERY PATTERNS
# ============================================================================

QUERY_PATTERNS = {
    "select_pattern": {
        "basic": "select(Hero)",
        "filter": "select(Hero).where(Hero.name == 'Spider-Man')",
        "join": "select(Hero, Team).join(Team)",
        "order": "select(Hero).order_by(Hero.name)",
    },
    "session_pattern": {
        "create": "session.add(hero)",
        "read": "session.exec(select(Hero)).all()",
        "update": "session.add(hero); session.commit()",
        "delete": "session.delete(hero); session.commit()",
    },
    "type_safety": {
        "select_returns": "Select[Tuple[Hero]]",
        "exec_returns": "Result[Hero]",
        "all_returns": "Sequence[Hero]",
        "first_returns": "Hero | None",
    },
}

# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class SQLModelClass:
    """SQLModel class metadata"""

    name: str
    is_table: bool
    fields: List[str]
    relationships: List[str]
    inherits_from: List[str]
    primary_keys: List[str] = field(default_factory=list)
    foreign_keys: List[str] = field(default_factory=list)


@dataclass
class FieldDefinition:
    """Field metadata"""

    name: str
    python_type: str
    sqlalchemy_type: Optional[str]
    is_primary_key: bool
    is_foreign_key: bool
    is_nullable: bool
    has_default: bool


@dataclass
class ModuleV6:
    pri: int
    size: int
    exports: List[int]
    imports: List[int]
    sqlmodel_classes: Dict[int, SQLModelClass] = field(default_factory=dict)
    field_definitions: Dict[int, FieldDefinition] = field(default_factory=dict)
    uses_pydantic: bool = False
    uses_sqlalchemy: bool = False
    src: Optional[str] = None


# ============================================================================
# NODE ROLES
# ============================================================================


class NodeRole(IntFlag):
    """SQLModel component roles"""

    TABLE_MODEL = 1 << 0  # Database table model
    DATA_MODEL = 1 << 1  # Pydantic-only model
    FIELD = 1 << 2  # Field definition
    RELATIONSHIP = 1 << 3  # Relationship
    QUERY = 1 << 4  # Query expression
    SESSION = 1 << 5  # Session management
    ENGINE = 1 << 6  # Engine configuration


# ============================================================================
# MAIN BUNDLER CLASS
# ============================================================================


class CalyxSQLModelBundlerV6:
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
        """Initialize SQLModel core symbols"""
        for cls in CORE_CLASSES | PYDANTIC_INTEGRATION | SQLALCHEMY_INTEGRATION:
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

    def extract_sqlmodel_classes(self, src: str) -> Dict[str, SQLModelClass]:
        """Extract SQLModel class definitions"""
        classes = {}

        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    # Check if it inherits from SQLModel
                    inherits_sqlmodel = False
                    is_table = False

                    for base in node.bases:
                        if isinstance(base, ast.Name) and base.id == "SQLModel":
                            inherits_sqlmodel = True

                    # Check for table=True in keywords
                    for keyword in node.keywords:
                        if keyword.arg == "table" and isinstance(
                            keyword.value, ast.Constant
                        ):
                            if keyword.value.value is True:
                                is_table = True

                    if inherits_sqlmodel:
                        fields = []
                        relationships = []
                        primary_keys = []
                        foreign_keys = []

                        # Extract field definitions
                        for item in node.body:
                            if isinstance(item, ast.AnnAssign):
                                field_name = (
                                    item.target.id
                                    if isinstance(item.target, ast.Name)
                                    else None
                                )
                                if field_name:
                                    fields.append(field_name)

                                    # Check if it's a Field() with primary_key=True
                                    if isinstance(item.value, ast.Call):
                                        if (
                                            isinstance(item.value.func, ast.Name)
                                            and item.value.func.id == "Field"
                                        ):
                                            for kw in item.value.keywords:
                                                if (
                                                    kw.arg == "primary_key"
                                                    and isinstance(
                                                        kw.value, ast.Constant
                                                    )
                                                ):
                                                    if kw.value.value is True:
                                                        primary_keys.append(field_name)
                                                elif kw.arg == "foreign_key":
                                                    foreign_keys.append(field_name)
                                        elif (
                                            isinstance(item.value.func, ast.Name)
                                            and item.value.func.id == "Relationship"
                                        ):
                                            relationships.append(field_name)

                        classes[node.name] = SQLModelClass(
                            name=node.name,
                            is_table=is_table,
                            fields=fields,
                            relationships=relationships,
                            inherits_from=[],
                            primary_keys=primary_keys,
                            foreign_keys=foreign_keys,
                        )
        except SyntaxError:
            pass

        return classes

    def extract_field_definitions(self, src: str) -> Dict[str, FieldDefinition]:
        """Extract Field() definitions"""
        fields = {}

        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.AnnAssign):
                    if isinstance(node.target, ast.Name):
                        field_name = node.target.id

                        # Get Python type
                        python_type = "Unknown"
                        if isinstance(node.annotation, ast.Name):
                            python_type = node.annotation.id

                        # Check if it's a Field() call
                        is_pk = False
                        is_fk = False
                        is_nullable = True
                        has_default = False

                        if isinstance(node.value, ast.Call):
                            if (
                                isinstance(node.value.func, ast.Name)
                                and node.value.func.id == "Field"
                            ):
                                has_default = True
                                for kw in node.value.keywords:
                                    if kw.arg == "primary_key":
                                        is_pk = True
                                    elif kw.arg == "foreign_key":
                                        is_fk = True
                                    elif kw.arg == "nullable":
                                        if isinstance(kw.value, ast.Constant):
                                            is_nullable = kw.value.value

                        # Map to SQLAlchemy type
                        sa_type = TYPE_MAPPINGS.get(python_type)

                        fields[field_name] = FieldDefinition(
                            name=field_name,
                            python_type=python_type,
                            sqlalchemy_type=sa_type,
                            is_primary_key=is_pk,
                            is_foreign_key=is_fk,
                            is_nullable=is_nullable,
                            has_default=has_default,
                        )
        except SyntaxError:
            pass

        return fields

    def detect_pydantic_usage(self, src: str) -> bool:
        """Detect if module uses Pydantic features"""
        pydantic_markers = [
            "BaseModel",
            "validator",
            "field_validator",
            "model_validator",
            "model_dump",
            "model_validate",
        ]
        return any(marker in src for marker in pydantic_markers)

    def detect_sqlalchemy_usage(self, src: str) -> bool:
        """Detect if module uses SQLAlchemy features"""
        sqlalchemy_markers = [
            "Column",
            "ForeignKey",
            "relationship",
            "create_engine",
            "sessionmaker",
            "declarative_base",
        ]
        return any(marker in src for marker in sqlalchemy_markers)

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

        # Check for SQLModel class
        if re.search(r"class\s+SQLModel\b", src):
            return 1

        # Check for metaclass
        if re.search(r"class\s+SQLModelMetaclass\b", src):
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
        if "tests" in rel.parts or "docs" in rel.parts or "docs_src" in rel.parts:
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

        # Extract SQLModel-specific data
        sqlmodel_classes_map = self.extract_sqlmodel_classes(src)
        sqlmodel_classes_dict = {}
        for class_name, class_info in sqlmodel_classes_map.items():
            class_id = self.intern_sym(class_name)
            sqlmodel_classes_dict[class_id] = class_info

        field_definitions_map = self.extract_field_definitions(src)
        field_definitions_dict = {}
        for field_name, field_info in field_definitions_map.items():
            field_id = self.intern_sym(field_name)
            field_definitions_dict[field_id] = field_info

        uses_pydantic = self.detect_pydantic_usage(src)
        uses_sqlalchemy = self.detect_sqlalchemy_usage(src)

        return ModuleV6(
            pri=pri,
            size=lines,
            exports=exp_ids,
            imports=self.extract_imports_v6(src),
            sqlmodel_classes=sqlmodel_classes_dict,
            field_definitions=field_definitions_dict,
            uses_pydantic=uses_pydantic,
            uses_sqlalchemy=uses_sqlalchemy,
            src=self.minify_python(src) if pri <= 2 else None,
        )

    def discover(self):
        all_mods = []

        # Find SQLModel source
        src_dir = self.root / "sqlmodel"
        if not src_dir.exists():
            src_dir = self.root

        for path in src_dir.glob("**/*.py"):
            if any(
                x in str(path) for x in ["__pycache__", ".pytest", "tests", "docs_src"]
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

    def build_graph_v6(self) -> Tuple[List, List, Dict]:
        """Build dependency + inheritance graph"""
        weights: Dict[int, Dict[int, int]] = {i: {} for i in range(len(self.modules))}
        inheritance_graph: Dict[int, Dict[int, List[str]]] = {
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

                            # Track Pydantic/SQLAlchemy usage
                            if token in PYDANTIC_INTEGRATION:
                                inheritance_graph[mid][dep] = inheritance_graph[
                                    mid
                                ].get(dep, []) + ["uses_pydantic"]
                            elif token in SQLALCHEMY_INTEGRATION:
                                inheritance_graph[mid][dep] = inheritance_graph[
                                    mid
                                ].get(dep, []) + ["uses_sqlalchemy"]

        def bucket_weight(w: int) -> int:
            return 3 if w >= 10 else 2 if w >= 5 else 1

        wdg = [
            (f, [(t, bucket_weight(w)) for t, w in deps.items()])
            for f, deps in weights.items()
            if deps
        ]
        dg = [(f, [t for t, _ in deps]) for f, deps in wdg]

        return wdg, dg, inheritance_graph

    def generate(self, output: str):
        wdg, dg, inheritance_graph = self.build_graph_v6()

        # Build module map
        mods = []
        for m in self.modules:
            # Serialize SQLModel classes
            classes_serializable = {}
            for class_id, class_info in m.sqlmodel_classes.items():
                classes_serializable[class_id] = {
                    "name": class_info.name,
                    "is_table": class_info.is_table,
                    "fields": class_info.fields,
                    "relationships": class_info.relationships,
                    "primary_keys": class_info.primary_keys,
                    "foreign_keys": class_info.foreign_keys,
                }

            # Serialize field definitions
            fields_serializable = {}
            for field_id, field_info in m.field_definitions.items():
                fields_serializable[field_id] = {
                    "name": field_info.name,
                    "python_type": field_info.python_type,
                    "sqlalchemy_type": field_info.sqlalchemy_type,
                    "is_primary_key": field_info.is_primary_key,
                    "is_foreign_key": field_info.is_foreign_key,
                    "is_nullable": field_info.is_nullable,
                }

            mod_entry = (
                m.pri,
                m.size,
                m.exports,
                m.imports,
                classes_serializable,
                fields_serializable,
                m.uses_pydantic,
                m.uses_sqlalchemy,
            )
            mods.append(mod_entry)

        bundle = {
            "V": 6,
            "F": "sqlmodel",
            "S": self.strs,
            "Y": self.syms,
            "M": mods,
            "W": wdg,
            "D": dg,
            "C": {i: m.src for i, m in enumerate(self.modules) if m.src},
            "I": DUAL_INHERITANCE,
            "T": MODEL_TYPES,
            "F_SYS": FIELD_SYSTEM,
            "Q": QUERY_PATTERNS,
            "R": inheritance_graph,
            "t": {
                "f": len(self.modules),
                "l": self.stats["lines"],
                **{k: self.stats[k] for k in ["c", "h", "n", "l", "s"]},
                "version": 6,
                "framework": "sqlmodel",
                "dual_inheritance": True,
            },
        }

        json_str = json.dumps(bundle, separators=(",", ":"))
        out = self.root / output
        out.write_text(json_str)

        raw = len(json_str)
        comp = len(zlib.compress(json_str.encode(), 9))

        print(f"\n{'=' * 50}")
        print(
            f"CALYX-SQLMODEL v6.0: {len(self.modules)} modules, {self.stats['lines']} lines"
        )
        print(f"Symbols: {len(self.syms)} | Strings: {len(self.strs)}")
        print(f"Dual Inheritance: Pydantic + SQLAlchemy")
        print(
            f"Raw: {raw / 1024:.1f} KB | Compressed: {comp / 1024:.1f} KB ({comp / raw * 100:.1f}%)"
        )
        print(f"{'=' * 50}")


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".")
    p.add_argument("--output", default="calyx_sqlmodel_v6.json")
    p.add_argument("--max-lines", type=int, default=30000)
    args = p.parse_args()

    b = CalyxSQLModelBundlerV6(args.root, args.max_lines)
    b.discover()
    b.generate(args.output)


if __name__ == "__main__":
    main()
