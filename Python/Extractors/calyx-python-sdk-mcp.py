#!/usr/bin/env python3
"""
CALYX-MCP BUNDLER v6.1 - Decorator-Driven Protocol Primitive IR
Treats the MCP Python SDK as a decorator-driven server/client framework
with tool, resource, prompt, and transport primitives.
"""

import json
import re
import zlib
import ast
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from collections import Counter, defaultdict
from enum import IntFlag

# ============================================================================
# CONFIGURATION: MCP-SPECIFIC
# ============================================================================

CORE_DECORATORS = {
    "tool",
    "resource",
    "prompt",
    "list_tools",
    "call_tool",
    "list_resources",
    "read_resource",
    "list_prompts",
    "get_prompt",
    "list_resource_templates",
}

CORE_TYPES = {
    "TextContent",
    "ImageContent",
    "EmbeddedResource",
    "CallToolResult",
    "GetPromptResult",
    "ListToolsResult",
    "ListResourcesResult",
    "ListPromptsResult",
    "Tool",
    "Resource",
    "Prompt",
    "PromptMessage",
    "SamplingMessage",
    "AnyUrl",
}

CORE_CLASSES = {
    "FastMCP",
    "Server",
    "ClientSession",
    "Context",
    "ServerSession",
    "StdioServerParameters",
    "InitializationOptions",
    "NotificationOptions",
}

TRANSPORT_TYPES = {
    "stdio": "Standard I/O transport for local process communication",
    "sse": "Server-Sent Events transport (legacy, being superseded)",
    "streamable-http": "Streamable HTTP transport (recommended for production)",
}

HIGH_PRIORITY = {
    "fastmcp.py",
    "server.py",
    "session.py",
    "types.py",
    "__init__.py",
    "stdio.py",
    "streamable_http.py",
    "context.py",
}

LOW_PRIORITY_PATTERNS = {
    "tests/",
    "test_",
    "examples/",
    "docs/",
    "_compat",
}

# ============================================================================
# V6: DECORATOR PLACEMENT CONSTRAINTS
# ============================================================================


class DecoratorConstraint(IntFlag):
    """Bitmask for legal decorator placement"""

    NONE = 0
    FUNCTION = 1 << 0  # Decorates a plain function
    ASYNC_FUNCTION = 1 << 1  # Decorates an async function
    METHOD = 1 << 2  # Decorates a method on Server/FastMCP
    TOP_LEVEL = 1 << 3  # Can be at module level
    NESTED = 1 << 4  # Can be nested inside a lifespan/context
    PARAMETER = 1 << 5  # Adds/injects a parameter (e.g. Context)
    PRIMITIVE = 1 << 6  # Registers an MCP primitive (tool/resource/prompt)

    # Composite constraints
    TOOL_BUILDER = FUNCTION | ASYNC_FUNCTION | TOP_LEVEL | PRIMITIVE
    RESOURCE_BUILDER = FUNCTION | ASYNC_FUNCTION | TOP_LEVEL | PRIMITIVE
    PROMPT_BUILDER = FUNCTION | TOP_LEVEL | PRIMITIVE
    LOWLEVEL_HANDLER = METHOD | ASYNC_FUNCTION  # @server.list_tools() etc.


# Decorator placement and signature rules
DECORATOR_RULES = {
    # FastMCP high-level decorators
    "tool": {
        "constraint": DecoratorConstraint.TOOL_BUILDER,
        "transforms": "function_to_tool",
        "creates_node": True,
        "signature_requirement": "typed_params",
        "pattern": r"@(?:mcp|server)\.tool\(",
        "context_injection": "Context",
        "return_handling": "structured_or_text",
    },
    "resource": {
        "constraint": DecoratorConstraint.RESOURCE_BUILDER,
        "transforms": "function_to_resource",
        "creates_node": True,
        "signature_requirement": "uri_template_match",
        "pattern": r"@(?:mcp|server)\.resource\(",
        "context_injection": None,
        "return_handling": "text_or_blob",
    },
    "prompt": {
        "constraint": DecoratorConstraint.PROMPT_BUILDER,
        "transforms": "function_to_prompt",
        "creates_node": True,
        "signature_requirement": "typed_params",
        "pattern": r"@(?:mcp|server)\.prompt\(",
        "context_injection": None,
        "return_handling": "str_or_message_list",
    },
    # Low-level server decorators
    "list_tools": {
        "constraint": DecoratorConstraint.LOWLEVEL_HANDLER,
        "transforms": "registers_list_handler",
        "creates_node": False,
        "signature_requirement": "no_params",
        "pattern": r"@server\.list_tools\(",
        "context_injection": None,
        "return_handling": "list_of_Tool",
    },
    "call_tool": {
        "constraint": DecoratorConstraint.LOWLEVEL_HANDLER,
        "transforms": "registers_call_handler",
        "creates_node": False,
        "signature_requirement": "name_and_arguments",
        "pattern": r"@server\.call_tool\(",
        "context_injection": None,
        "return_handling": "CallToolResult_or_dict",
    },
    "list_resources": {
        "constraint": DecoratorConstraint.LOWLEVEL_HANDLER,
        "transforms": "registers_list_handler",
        "creates_node": False,
        "signature_requirement": "no_params_or_request",
        "pattern": r"@server\.list_resources\(",
        "context_injection": None,
        "return_handling": "ListResourcesResult",
    },
    "read_resource": {
        "constraint": DecoratorConstraint.LOWLEVEL_HANDLER,
        "transforms": "registers_read_handler",
        "creates_node": False,
        "signature_requirement": "uri_param",
        "pattern": r"@server\.read_resource\(",
        "context_injection": None,
        "return_handling": "str_or_bytes",
    },
    "list_prompts": {
        "constraint": DecoratorConstraint.LOWLEVEL_HANDLER,
        "transforms": "registers_list_handler",
        "creates_node": False,
        "signature_requirement": "no_params",
        "pattern": r"@server\.list_prompts\(",
        "context_injection": None,
        "return_handling": "list_of_Prompt",
    },
    "get_prompt": {
        "constraint": DecoratorConstraint.LOWLEVEL_HANDLER,
        "transforms": "registers_get_handler",
        "creates_node": False,
        "signature_requirement": "name_and_arguments",
        "pattern": r"@server\.get_prompt\(",
        "context_injection": None,
        "return_handling": "GetPromptResult",
    },
    "list_resource_templates": {
        "constraint": DecoratorConstraint.LOWLEVEL_HANDLER,
        "transforms": "registers_list_handler",
        "creates_node": False,
        "signature_requirement": "no_params_or_request",
        "pattern": r"@server\.list_resource_templates\(",
        "context_injection": None,
        "return_handling": "ListResourceTemplatesResult",
    },
}

# ============================================================================
# V6: SIGNATURE INVARIANTS
# ============================================================================

SIGNATURE_INVARIANTS = {
    "tool": {
        "context_param": "ctx: Context",
        "context_position": "any",
        "context_injection": "auto_injected_by_fastmcp",
        "type_requirement": "all_params_typed",
        "return_types": ["str", "int", "float", "bool", "dict", "BaseModel", "TypedDict", "list", "CallToolResult"],
        "async_supported": True,
    },
    "resource": {
        "uri_template_params": "extracted_from_uri_pattern",
        "param_match": "uri_template_vars_must_match_func_params",
        "return_types": ["str", "bytes"],
        "async_supported": True,
    },
    "prompt": {
        "return_types": ["str", "list[Message]"],
        "async_supported": False,
        "message_types": ["UserMessage", "AssistantMessage"],
    },
    "list_tools": {
        "params": [],
        "return_type": "list[types.Tool]",
        "async_required": True,
    },
    "call_tool": {
        "params": ["name: str", "arguments: dict[str, Any]"],
        "return_type": "list[TextContent] | dict | CallToolResult",
        "async_required": True,
    },
    "read_resource": {
        "params": ["uri: AnyUrl"],
        "return_type": "str | bytes",
        "async_required": True,
    },
}

# ============================================================================
# V6: TYPE SYSTEM
# ============================================================================

TYPE_INVARIANTS = {
    "TextContent": {
        "python_type": "mcp.types.TextContent",
        "fields": {"type": "Literal['text']", "text": "str"},
        "usage": "text tool output / prompt messages",
    },
    "ImageContent": {
        "python_type": "mcp.types.ImageContent",
        "fields": {"type": "Literal['image']", "data": "str (base64)", "mimeType": "str"},
        "usage": "image tool output",
    },
    "EmbeddedResource": {
        "python_type": "mcp.types.EmbeddedResource",
        "fields": {"type": "Literal['resource']", "resource": "TextResourceContents | BlobResourceContents"},
        "usage": "embedding resources inside tool results",
    },
    "CallToolResult": {
        "python_type": "mcp.types.CallToolResult",
        "fields": {
            "content": "list[TextContent | ImageContent | EmbeddedResource]",
            "structuredContent": "dict | None",
            "isError": "bool | None",
            "_meta": "dict | None",
        },
        "usage": "full tool response with optional structured output and metadata",
    },
    "Tool": {
        "python_type": "mcp.types.Tool",
        "fields": {"name": "str", "description": "str", "inputSchema": "dict"},
        "usage": "low-level tool registration",
    },
    "Resource": {
        "python_type": "mcp.types.Resource",
        "fields": {"uri": "AnyUrl", "name": "str", "description": "str | None"},
        "usage": "low-level resource registration",
    },
    "Context": {
        "python_type": "mcp.server.fastmcp.Context",
        "fields": {
            "request_id": "str",
            "client_id": "str | None",
            "fastmcp": "FastMCP",
            "session": "ServerSession",
            "request_context": "RequestContext",
        },
        "usage": "injected into tools/resources by FastMCP",
        "methods": [
            "debug(message)",
            "info(message)",
            "warning(message)",
            "error(message)",
            "report_progress(progress, total, message)",
            "read_resource(uri)",
            "elicit(message, schema)",
        ],
    },
}

# ============================================================================
# V6: MCP PRIMITIVE LIFECYCLE
# ============================================================================

PRIMITIVE_LIFECYCLE = {
    "tool": {
        "register": "@mcp.tool() or @server.list_tools() + @server.call_tool()",
        "discovery": "session.list_tools()",
        "invocation": "session.call_tool(name, arguments)",
        "notification": "ctx.session.send_tool_list_changed()",
        "structured_output": True,
    },
    "resource": {
        "register": "@mcp.resource(uri_template) or @server.list_resources() + @server.read_resource()",
        "discovery": "session.list_resources()",
        "invocation": "session.read_resource(uri)",
        "notification": "ctx.session.send_resource_list_changed() or send_resource_updated(uri)",
        "structured_output": False,
    },
    "prompt": {
        "register": "@mcp.prompt() or @server.list_prompts() + @server.get_prompt()",
        "discovery": "session.list_prompts()",
        "invocation": "session.get_prompt(name, arguments)",
        "notification": "ctx.session.send_prompt_list_changed()",
        "structured_output": False,
    },
}

# ============================================================================
# V6: TRANSPORT LIFECYCLE
# ============================================================================

TRANSPORT_LIFECYCLE = {
    "stdio": {
        "server_usage": "mcp.server.stdio.stdio_server()",
        "client_usage": "mcp.client.stdio.stdio_client(StdioServerParameters(...))",
        "use_case": "local subprocess, Claude Desktop integration",
        "stateful": True,
    },
    "streamable-http": {
        "server_usage": "mcp.run(transport='streamable-http') or streamable_http_app()",
        "client_usage": "mcp.client.streamable_http.streamable_http_client(url)",
        "use_case": "production multi-client deployments",
        "stateful": "optional (stateless_http=True for stateless)",
        "recommended": True,
    },
    "sse": {
        "server_usage": "mcp.sse_app()",
        "client_usage": "mcp.client.sse.sse_client(url)",
        "use_case": "legacy SSE, being superseded by streamable-http",
        "stateful": True,
        "deprecated": True,
    },
}

# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class DecoratorInfo:
    """Decorator metadata with signature requirements"""

    name: str
    constraint: int
    transforms: str
    signature_requirement: str
    pattern: str = ""
    context_injection: Optional[str] = None
    return_handling: Optional[str] = None


@dataclass
class SignatureTuple:
    """Function signature with parameter mapping"""

    func_name: str
    params: List[str]
    param_types: List[int]
    defaults: List[Any]
    decorators: List[int]
    is_async: bool
    signature_valid: bool


@dataclass
class ModuleV6:
    pri: int
    size: int
    exports: List[int]
    imports: List[int]
    decorator_constraints: Dict[int, int] = field(default_factory=dict)
    node_role: int = 0
    signatures: Dict[int, SignatureTuple] = field(default_factory=dict)
    src: Optional[str] = None


# ============================================================================
# NODE ROLES
# ============================================================================


class NodeRole(IntFlag):
    """Role in the MCP primitive graph"""

    FASTMCP_SERVER = 1 << 0  # FastMCP high-level server
    LOWLEVEL_SERVER = 1 << 1  # Low-level Server class
    CLIENT = 1 << 2  # ClientSession
    TOOL_HANDLER = 1 << 3  # Registers/handles tools
    RESOURCE_HANDLER = 1 << 4  # Registers/handles resources
    PROMPT_HANDLER = 1 << 5  # Registers/handles prompts
    TRANSPORT = 1 << 6  # Transport layer (stdio/http/sse)
    TYPES = 1 << 7  # Protocol type definitions
    AUTH = 1 << 8  # Authentication / OAuth


# Primitive tree edges
PRIMITIVE_EDGES = [
    ("FastMCP", "tool", "registers_tool"),
    ("FastMCP", "resource", "registers_resource"),
    ("FastMCP", "prompt", "registers_prompt"),
    ("Server", "list_tools", "handles_list"),
    ("Server", "call_tool", "handles_call"),
    ("Server", "list_resources", "handles_list"),
    ("Server", "read_resource", "handles_read"),
    ("Server", "list_prompts", "handles_list"),
    ("Server", "get_prompt", "handles_get"),
    ("ClientSession", "list_tools", "calls_list"),
    ("ClientSession", "call_tool", "calls_tool"),
    ("ClientSession", "list_resources", "calls_list"),
    ("ClientSession", "read_resource", "calls_read"),
]

# ============================================================================
# MAIN BUNDLER CLASS
# ============================================================================


class CalyxMCPBundlerV6:
    def __init__(self, root: str = ".", max_lines: int = 30000, output_dir: str = "."):
        self.root = Path(root).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.max_lines = max_lines

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Intern tables
        self.strs: List[str] = []
        self.str_id: Dict[str, int] = {}

        self.syms: List[str] = []
        self.sym_id: Dict[str, int] = {}

        # Decorator registry
        self.decorator_info: Dict[str, DecoratorInfo] = {}
        self._init_decorators()

        self.modules: List[ModuleV6] = []
        self.sym_to_mods: Dict[int, List[int]] = defaultdict(list)

        self.stats = {"c": 0, "h": 0, "n": 0, "l": 0, "s": 0, "lines": 0}

        self.signature_invariants = SIGNATURE_INVARIANTS
        self.type_invariants = TYPE_INVARIANTS
        self.primitive_edges = PRIMITIVE_EDGES

    def _init_decorators(self):
        """Initialize MCP decorator rules and intern symbols"""
        for name, rules in DECORATOR_RULES.items():
            self.decorator_info[name] = DecoratorInfo(
                name=name,
                constraint=rules.get("constraint", DecoratorConstraint.NONE),
                transforms=rules.get("transforms", ""),
                signature_requirement=rules.get("signature_requirement", ""),
                pattern=rules.get("pattern", ""),
                context_injection=rules.get("context_injection"),
                return_handling=rules.get("return_handling"),
            )
            self.intern_sym(name)

        # Pre-intern core classes and types
        for name in CORE_CLASSES | CORE_TYPES:
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

    def minify_python(self, src: str) -> str:
        """Python-aware minification preserving indentation"""
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

    def extract_signature(self, node: ast.FunctionDef, decorators: List[str]) -> SignatureTuple:
        """Extract function signature and validate against MCP decorator requirements"""
        func_name = node.name
        params = []
        param_types = []
        defaults = []
        decorator_ids = [self.intern_sym(d) for d in decorators]
        is_async = isinstance(node, ast.AsyncFunctionDef)

        for arg in node.args.args:
            params.append(arg.arg)
            if arg.annotation:
                if isinstance(arg.annotation, ast.Name):
                    type_id = self.intern_sym(arg.annotation.id)
                elif isinstance(arg.annotation, ast.Attribute):
                    type_id = self.intern_sym(arg.annotation.attr)
                elif isinstance(arg.annotation, ast.Subscript):
                    # e.g. Context[ServerSession, None]
                    if isinstance(arg.annotation.value, ast.Name):
                        type_id = self.intern_sym(arg.annotation.value.id)
                    else:
                        type_id = self.intern_sym("Any")
                else:
                    type_id = self.intern_sym("Any")
                param_types.append(type_id)
            else:
                param_types.append(self.intern_sym("Any"))

        defaults_offset = len(params) - len(node.args.defaults)
        for i in range(len(params)):
            if i >= defaults_offset:
                default_node = node.args.defaults[i - defaults_offset]
                if isinstance(default_node, ast.Constant):
                    defaults.append(default_node.value)
                else:
                    defaults.append(None)
            else:
                defaults.append(None)

        signature_valid = self._validate_signature(params, param_types, decorators)

        return SignatureTuple(
            func_name=func_name,
            params=params,
            param_types=param_types,
            defaults=defaults,
            decorators=decorator_ids,
            is_async=is_async,
            signature_valid=signature_valid,
        )

    def _validate_signature(self, params: List[str], param_types: List[int], decorators: List[str]) -> bool:
        """Validate function signature against MCP decorator requirements"""
        ctx_sym = self.sym_id.get("Context")

        # call_tool and get_prompt require (name, arguments)
        if "call_tool" in decorators or "get_prompt" in decorators:
            if len(params) < 2:
                return False
            if params[0] != "name":
                return False

        # read_resource requires a uri parameter
        if "read_resource" in decorators:
            if "uri" not in params:
                return False

        # Tools with Context injection: ctx param must be typed as Context
        if "tool" in decorators and "ctx" in params:
            ctx_idx = params.index("ctx")
            if ctx_sym is not None and param_types[ctx_idx] != ctx_sym:
                return False

        return True

    def extract_decorators(self, node: ast.FunctionDef) -> List[str]:
        """Extract MCP decorator names from a function node"""
        decorators = []
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Attribute):
                    # @mcp.tool(), @server.list_tools(), etc.
                    decorators.append(dec.func.attr)
            elif isinstance(dec, ast.Attribute):
                decorators.append(dec.attr)
            elif isinstance(dec, ast.Name):
                decorators.append(dec.id)
        return decorators

    def extract_node_role(self, src: str, decorators: List[str]) -> int:
        """Determine node role from source and decorators"""
        role = 0

        if re.search(r"class\s+FastMCP\b", src):
            role |= NodeRole.FASTMCP_SERVER
        if re.search(r"class\s+Server\b", src):
            role |= NodeRole.LOWLEVEL_SERVER
        if re.search(r"class\s+ClientSession\b", src):
            role |= NodeRole.CLIENT
        if any(d in ("tool", "list_tools", "call_tool") for d in decorators):
            role |= NodeRole.TOOL_HANDLER
        if any(d in ("resource", "list_resources", "read_resource", "list_resource_templates") for d in decorators):
            role |= NodeRole.RESOURCE_HANDLER
        if any(d in ("prompt", "list_prompts", "get_prompt") for d in decorators):
            role |= NodeRole.PROMPT_HANDLER
        if re.search(r"stdio|streamable.?http|sse", src, re.IGNORECASE):
            role |= NodeRole.TRANSPORT
        if "types" in src.lower() and re.search(r"class\s+\w+Content\b", src):
            role |= NodeRole.TYPES
        if re.search(r"OAuth|TokenVerifier|AuthSettings", src):
            role |= NodeRole.AUTH

        return role

    def extract_exports_v6(self, src: str) -> List[Tuple[str, str, List[str]]]:
        """Extract exports with decorators — returns (name, type, decorators)"""
        exports = []

        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    exports.append((node.name, "class", []))
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    decorators = self.extract_decorators(node)
                    exports.append((node.name, "function", decorators))
        except SyntaxError:
            for pattern, decl_type in [
                (r"^\s*class\s+(\w+)", "class"),
                (r"^\s*(?:async\s+)?def\s+(\w+)", "function"),
            ]:
                for match in re.findall(pattern, src, re.MULTILINE)[:20]:
                    exports.append((match, decl_type, []))

        return exports

    def extract_signatures_from_ast(self, src: str) -> Dict[str, SignatureTuple]:
        """Extract signatures for all MCP-decorated functions"""
        signatures = {}

        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    decorators = self.extract_decorators(node)
                    if any(d in CORE_DECORATORS for d in decorators):
                        sig = self.extract_signature(node, decorators)
                        signatures[node.name] = sig
        except SyntaxError:
            pass

        return signatures

    def extract_imports_v6(self, src: str) -> List[int]:
        """Extract import module names"""
        imports = []
        for m in re.findall(r"^\s*import\s+(\w+)", src, re.MULTILINE)[:10]:
            imports.append(self.intern_str(m))
        for m in re.findall(r"^\s*from\s+(\S+)\s+import", src, re.MULTILINE)[:10]:
            imports.append(self.intern_str(m))
        return imports

    def priority(self, path: Path, src: str) -> int:
        p = str(path)

        if any(h in p for h in HIGH_PRIORITY):
            return 1

        for cls in CORE_CLASSES:
            if re.search(rf"class\s+{cls}\b", src):
                return 1

        for dec in CORE_DECORATORS:
            if re.search(rf"def\s+{dec}\(", src):
                return 1

        if src.count("class ") + src.count("def ") > 10:
            return 2

        for pat in LOW_PRIORITY_PATTERNS:
            if pat.lower() in p.lower():
                return 4

        return 3

    def find_mcp_source(self) -> Optional[Path]:
        """Find the MCP Python SDK source directory"""
        candidates = [
            self.root / "src" / "mcp",
            self.root / "mcp",
            self.root,
        ]

        try:
            import mcp

            candidates.append(Path(mcp.__file__).parent)
        except ImportError:
            pass

        # Search site-packages
        import sys

        for sp in sys.path:
            candidate = Path(sp) / "mcp"
            if candidate.exists() and candidate.is_dir():
                candidates.append(candidate)

        for candidate in candidates:
            if candidate.exists() and candidate.is_dir():
                # Confirm it's actually the MCP SDK
                if (candidate / "__init__.py").exists() or (candidate / "server").exists():
                    return candidate

        return None

    def discover(self):
        all_mods = []

        src_dir = self.find_mcp_source()

        if not src_dir:
            print(f"Warning: MCP source not found under {self.root}")
            print("Creating minimal bundle with built-in invariant knowledge...")
            self.modules = []
            return

        print(f"Found MCP source at: {src_dir}")

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

    def analyze(self, path: Path) -> Optional[ModuleV6]:
        try:
            rel = path.relative_to(self.root)
        except ValueError:
            rel = path

        if "tests" in str(rel).lower() or "test_" in path.name:
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

        exports = self.extract_exports_v6(src)
        exp_ids = []

        mod_idx = len(self.modules)
        for exp_name, exp_type, decorators in exports:
            sym_id = self.intern_sym(exp_name)
            exp_ids.append(sym_id)
            self.sym_to_mods[sym_id].append(mod_idx)

        self.stats["lines"] += lines
        self.stats["c" if pri == 1 else "h" if pri == 2 else "n" if pri == 3 else "l"] += 1

        signatures_map = self.extract_signatures_from_ast(src)
        signatures_dict = {}
        for func_name, sig_tuple in signatures_map.items():
            func_id = self.intern_sym(func_name)
            signatures_dict[func_id] = sig_tuple

        decorator_constraints = {}
        all_decorators: List[str] = []
        for _, _, decs in exports:
            all_decorators.extend(decs)
            for dec in decs:
                if dec in self.decorator_info:
                    dec_id = self.sym_id[dec]
                    decorator_constraints[dec_id] = int(self.decorator_info[dec].constraint)

        node_role = self.extract_node_role(src, all_decorators)

        return ModuleV6(
            pri=pri,
            size=lines,
            exports=exp_ids,
            imports=self.extract_imports_v6(src),
            decorator_constraints=decorator_constraints,
            node_role=node_role,
            signatures=signatures_dict,
            src=self.minify_python(src) if pri <= 2 else None,
        )

    def build_graph_v6(self) -> Tuple[List, List, Dict]:
        """Build dependency graph + primitive tree"""
        weights: Dict[int, Dict[int, int]] = {i: {} for i in range(len(self.modules))}
        primitive_tree: Dict[int, Dict[int, List[str]]] = {i: {} for i in range(len(self.modules))}

        for mid, mod in enumerate(self.modules):
            if not mod.src:
                continue

            counts = Counter(re.findall(r"\b\w+\b", mod.src))

            for token, cnt in counts.items():
                if token in self.sym_id:
                    for dep in self.sym_to_mods.get(self.sym_id[token], []):
                        if dep != mid:
                            weight = min(cnt, 3)
                            weights[mid][dep] = weights[mid].get(dep, 0) + weight

                            if token in self.decorator_info:
                                transform = self.decorator_info[token].transforms
                                primitive_tree[mid][dep] = primitive_tree[mid].get(dep, []) + [transform]

        def bucket_weight(w: int) -> int:
            return 3 if w >= 10 else 2 if w >= 5 else 1

        wdg = [(f, [(t, bucket_weight(w)) for t, w in deps.items()]) for f, deps in weights.items() if deps]
        dg = [(f, [t for t, _ in deps]) for f, deps in wdg]

        return wdg, dg, primitive_tree

    def generate(self, output: str):
        wdg, dg, primitive_tree = self.build_graph_v6()

        mods = []
        for m in self.modules:
            sigs_serializable = {}
            for func_id, sig in m.signatures.items():
                sigs_serializable[func_id] = {
                    "func_name": sig.func_name,
                    "params": sig.params,
                    "param_types": sig.param_types,
                    "defaults": sig.defaults,
                    "decorators": sig.decorators,
                    "is_async": sig.is_async,
                    "signature_valid": sig.signature_valid,
                }

            mods.append(
                (
                    m.pri,
                    m.size,
                    m.exports,
                    m.imports,
                    m.decorator_constraints,
                    m.node_role,
                    sigs_serializable,
                )
            )

        decorator_rules = {}
        for dec_name, dec_info in self.decorator_info.items():
            dec_id = self.sym_id.get(dec_name)
            if dec_id is not None:
                decorator_rules[dec_id] = {
                    "constraint": int(dec_info.constraint),
                    "transforms": dec_info.transforms,
                    "signature_requirement": dec_info.signature_requirement,
                    "pattern": dec_info.pattern,
                    "context_injection": dec_info.context_injection,
                    "return_handling": dec_info.return_handling,
                }

        bundle = {
            "V": 6,
            "F": "mcp-python-sdk",
            "S": self.strs,
            "Y": self.syms,
            "M": mods,
            "W": wdg,
            "D": dg,
            "C": {i: m.src for i, m in enumerate(self.modules) if m.src},
            "I": self.signature_invariants,  # Signature invariants
            "P": decorator_rules,  # Decorator placement rules
            "T": self.type_invariants,  # Type system invariants
            "R": primitive_tree,  # Primitive tree edges
            "PL": PRIMITIVE_LIFECYCLE,  # Tool/resource/prompt lifecycle
            "TR": TRANSPORT_LIFECYCLE,  # Transport options
            "PE": self.primitive_edges,  # Structural edges
            "t": {
                "f": len(self.modules),
                "l": self.stats["lines"],
                **{k: self.stats[k] for k in ["c", "h", "n", "l", "s"]},
                "version": 6,
                "framework": "mcp-python-sdk",
                "decorators": len(decorator_rules),
                "type_invariants": len(self.type_invariants),
                "primitives": ["tool", "resource", "prompt"],
                "transports": list(TRANSPORT_LIFECYCLE.keys()),
            },
        }

        json_str = json.dumps(bundle, separators=(",", ":"))

        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.output_dir / output
        output_path.write_text(json_str)

        raw = len(json_str)
        comp = len(zlib.compress(json_str.encode(), 9))

        print(f"\n{'=' * 50}")
        print(f"CALYX-MCP v6.1: {len(self.modules)} modules, {self.stats['lines']} lines")
        print(f"Symbols: {len(self.syms)} | Strings: {len(self.strs)}")
        print(f"Decorators: {len(decorator_rules)} | Types: {len(self.type_invariants)}")
        print(f"Primitives: tool, resource, prompt")
        print(f"Transports: {', '.join(TRANSPORT_LIFECYCLE.keys())}")
        print(f"Output: {output_path}")
        print(f"Raw: {raw / 1024:.1f} KB | Compressed: {comp / 1024:.1f} KB ({comp / raw * 100:.1f}%)")
        print(f"{'=' * 50}")


def main():
    import argparse

    p = argparse.ArgumentParser(description="CALYX-MCP Bundler v6.1 — Semantic IR for the MCP Python SDK")
    p.add_argument("--root", default=".", help="Root directory for MCP SDK source")
    p.add_argument("--output", default="calyx_mcp_v6.json", help="Output file name")
    p.add_argument("--output-dir", default=".", help="Output directory")
    p.add_argument("--max-lines", type=int, default=30000, help="Max lines to include")
    args = p.parse_args()

    b = CalyxMCPBundlerV6(
        root=args.root,
        max_lines=args.max_lines,
        output_dir=args.output_dir,
    )
    b.discover()
    b.generate(args.output)


if __name__ == "__main__":
    main()
