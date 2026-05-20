#!/usr/bin/env python3
"""
CALYX-FASTSTREAM BUNDLER v6.0 - Async Event-Driven Messaging Framework IR
Treats FastStream as a multi-broker message bus with subscriber/publisher patterns
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
# CONFIGURATION: FASTSTREAM-SPECIFIC
# ============================================================================

CORE_CLASSES = {
    "FastStream",  # Main application class
    "KafkaBroker",  # Kafka broker
    "NatsBroker",  # NATS broker
    "RabbitBroker",  # RabbitMQ broker
    "RedisBroker",  # Redis broker
    "ConfluentBroker",  # Confluent Kafka broker
    "Router",  # Message routing
}

BROKER_TYPES = {
    "kafka": "Apache Kafka message broker",
    "nats": "NATS.io message broker",
    "rabbit": "RabbitMQ AMQP broker",
    "redis": "Redis pub/sub and streams",
    "confluent": "Confluent Kafka (managed)",
    "mqtt": "MQTT IoT broker",
}

DECORATOR_PATTERNS = {
    "@broker.subscriber": {
        "role": "message_consumer",
        "purpose": "Subscribe to messages from queue/topic/channel",
        "returns": "AsyncContextManager",
        "side_effect": "Registers handler with broker",
    },
    "@broker.publisher": {
        "role": "message_producer",
        "purpose": "Publish messages to queue/topic/channel",
        "returns": "Callable decorator",
        "side_effect": "Creates publisher configuration",
    },
    "@app.after_startup": {
        "role": "lifecycle_hook",
        "purpose": "Execute after broker connection established",
        "timing": "post_startup",
    },
    "@app.on_shutdown": {
        "role": "lifecycle_hook",
        "purpose": "Execute before broker disconnection",
        "timing": "pre_shutdown",
    },
}

HIGH_PRIORITY = {
    "app.py",
    "broker.py",
    "__init__.py",
    "registrator.py",
}

LOW_PRIORITY_PATTERNS = {
    "tests/",
    "test_",
    "docs/",
    "benchmarks/",
}

# ============================================================================
# V6: MESSAGE BROKER PATTERNS
# ============================================================================

BROKER_PATTERNS = {
    "subscriber_lifecycle": {
        "registration": "Decorator collects handler + routing key",
        "startup": "Broker connects and starts consuming",
        "message_flow": "Message → deserialize → dependency injection → handler",
        "acknowledgment": "Auto-ack (default) or manual ack via context",
        "error_handling": "Retry logic + dead letter queue support",
    },
    "publisher_lifecycle": {
        "registration": "Decorator creates publisher spec",
        "publish": "Serialize message → broker.publish()",
        "reply_to": "RPC pattern via correlation_id",
    },
    "dependency_injection": {
        "message_param": "Inject raw message via type annotation",
        "context_param": "Inject broker context, logger, etc.",
        "custom_depends": "FastDepends integration",
    },
}

# ============================================================================
# V6: ASYNC PATTERNS
# ============================================================================

ASYNC_PATTERNS = {
    "broker_connection": {
        "pattern": "async with broker:",
        "behavior": "Context manager for connection lifecycle",
        "guarantees": ["graceful_shutdown", "connection_pooling"],
    },
    "message_handler": {
        "pattern": "async def handler(msg: Message):",
        "concurrency": "anyio TaskGroup for parallel handlers",
        "backpressure": "Configurable max_workers per subscriber",
    },
    "publishing": {
        "pattern": "await broker.publish(msg, queue='events')",
        "modes": ["fire_and_forget", "rpc_request", "batch_publish"],
    },
}

# ============================================================================
# V6: BROKER-SPECIFIC FEATURES
# ============================================================================

BROKER_FEATURES = {
    "kafka": {
        "consumer_groups": "Parallel consumption with group_id",
        "partitions": "Manual partition assignment",
        "offsets": "Commit strategies (auto, manual, batched)",
        "key_routing": "Message key → partition mapping",
    },
    "nats": {
        "subjects": "Hierarchical topic wildcards (foo.*.bar)",
        "jetstream": "Persistent streams with ack policies",
        "kv_store": "Built-in key-value storage",
        "object_store": "Large object storage",
    },
    "rabbit": {
        "exchanges": "Direct, topic, fanout, headers",
        "bindings": "Queue-to-exchange routing rules",
        "qos": "Prefetch count for backpressure",
        "priority_queues": "Message prioritization",
    },
    "redis": {
        "pubsub": "Classic pub/sub channels",
        "streams": "Consumer groups on Redis Streams",
        "lists": "LPUSH/RPOP queue semantics",
        "patterns": "Pattern-based subscriptions",
    },
}

# ============================================================================
# V6: MIDDLEWARE SYSTEM
# ============================================================================

MIDDLEWARE_TYPES = {
    "BaseMiddleware": "Base class for all middleware",
    "ExceptionMiddleware": "Catch and handle exceptions",
    "PrometheusMiddleware": "Metrics collection",
    "OpenTelemetryMiddleware": "Distributed tracing",
}

# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class SubscriberInfo:
    """Subscriber handler metadata"""

    handler_name: str
    queue_or_topic: str  # Routing destination
    broker_type: str  # kafka, nats, rabbit, redis
    filters: List[str]  # Message filters
    dependencies: List[str]  # Injected parameters
    is_batch: bool  # Batch message handling
    ack_mode: str  # auto, manual, immediate


@dataclass
class PublisherInfo:
    """Publisher metadata"""

    publisher_name: str
    destination: str  # Queue/topic to publish to
    broker_type: str
    reply_to: Optional[str]  # RPC reply queue
    is_rpc: bool


@dataclass
class BrokerConfig:
    """Broker configuration"""

    broker_type: str  # kafka, nats, rabbit, redis
    connection_url: Optional[str]
    middlewares: List[str]
    graceful_timeout: Optional[int]
    apply_types: bool  # Auto type conversion


@dataclass
class ModuleV6:
    pri: int
    size: int
    exports: List[int]
    imports: List[int]
    subscribers: Dict[int, SubscriberInfo] = field(default_factory=dict)
    publishers: Dict[int, PublisherInfo] = field(default_factory=dict)
    broker_configs: List[BrokerConfig] = field(default_factory=list)
    has_async: bool = False
    has_middleware: bool = False
    has_lifecycle_hooks: bool = False
    src: Optional[str] = None


# ============================================================================
# NODE ROLES
# ============================================================================


class NodeRole(IntFlag):
    """FastStream component roles"""

    BROKER = 1 << 0  # Message broker
    SUBSCRIBER = 1 << 1  # Message consumer
    PUBLISHER = 1 << 2  # Message producer
    ROUTER = 1 << 3  # Message routing
    MIDDLEWARE = 1 << 4  # Message middleware
    SERIALIZER = 1 << 5  # Message serialization
    SPECIFICATION = 1 << 6  # AsyncAPI spec generation


# ============================================================================
# MAIN BUNDLER CLASS
# ============================================================================


class CalyxFastStreamBundlerV6:
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
        """Initialize FastStream core symbols"""
        for cls in CORE_CLASSES:
            self.intern_sym(cls)
        for broker in BROKER_TYPES.keys():
            self.intern_sym(broker)

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

    def extract_subscribers(self, src: str) -> Dict[str, SubscriberInfo]:
        """Extract @broker.subscriber decorated handlers"""
        subscribers = {}

        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.AsyncFunctionDef):
                    # Check decorators
                    for dec in node.decorator_list:
                        dec_name = ""
                        if isinstance(dec, ast.Attribute):
                            dec_name = f"{dec.value.id if isinstance(dec.value, ast.Name) else ''}.{dec.attr}"
                        elif isinstance(dec, ast.Call) and isinstance(
                            dec.func, ast.Attribute
                        ):
                            dec_name = f"{dec.func.value.id if isinstance(dec.func.value, ast.Name) else ''}.{dec.func.attr}"

                        if "subscriber" in dec_name:
                            # Extract queue/topic from decorator args
                            queue = "unknown"
                            if isinstance(dec, ast.Call) and dec.args:
                                if isinstance(dec.args[0], ast.Constant):
                                    queue = str(dec.args[0].value)

                            # Extract dependencies from function parameters
                            deps = [arg.arg for arg in node.args.args]

                            subscribers[node.name] = SubscriberInfo(
                                handler_name=node.name,
                                queue_or_topic=queue,
                                broker_type="unknown",  # Would need more context
                                filters=[],
                                dependencies=deps,
                                is_batch=False,
                                ack_mode="auto",
                            )
        except SyntaxError:
            pass

        return subscribers

    def extract_publishers(self, src: str) -> Dict[str, PublisherInfo]:
        """Extract @broker.publisher decorated functions"""
        publishers = {}

        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for dec in node.decorator_list:
                        dec_name = ""
                        if isinstance(dec, ast.Attribute):
                            dec_name = f"{dec.value.id if isinstance(dec.value, ast.Name) else ''}.{dec.attr}"
                        elif isinstance(dec, ast.Call) and isinstance(
                            dec.func, ast.Attribute
                        ):
                            dec_name = f"{dec.func.value.id if isinstance(dec.func.value, ast.Name) else ''}.{dec.func.attr}"

                        if "publisher" in dec_name:
                            destination = "unknown"
                            if isinstance(dec, ast.Call) and dec.args:
                                if isinstance(dec.args[0], ast.Constant):
                                    destination = str(dec.args[0].value)

                            publishers[node.name] = PublisherInfo(
                                publisher_name=node.name,
                                destination=destination,
                                broker_type="unknown",
                                reply_to=None,
                                is_rpc=False,
                            )
        except SyntaxError:
            pass

        return publishers

    def detect_broker_type(self, src: str) -> Optional[str]:
        """Detect which broker type is used"""
        for broker_type in BROKER_TYPES.keys():
            if f"{broker_type.capitalize()}Broker" in src:
                return broker_type
            if f"from faststream.{broker_type}" in src:
                return broker_type
        return None

    def detect_async(self, src: str) -> bool:
        """Detect async patterns"""
        markers = ["async def", "await ", "async with"]
        return any(marker in src for marker in markers)

    def detect_middleware(self, src: str) -> bool:
        """Detect middleware usage"""
        markers = ["Middleware", "middlewares="]
        return any(marker in src for marker in markers)

    def detect_lifecycle_hooks(self, src: str) -> bool:
        """Detect lifecycle hooks"""
        markers = ["@app.after_startup", "@app.on_shutdown", "@app.on_startup"]
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

        # Check for broker classes
        for broker in BROKER_TYPES.keys():
            if f"{broker.capitalize()}Broker" in src:
                return 1

        # Check for FastStream app
        if "FastStream" in src or "class FastStream" in src:
            return 1

        # Broker-specific modules
        if any(b in p for b in ["kafka/", "nats/", "rabbit/", "redis/"]):
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

        # Extract FastStream-specific data
        subscribers_map = self.extract_subscribers(src)
        subscribers_dict = {}
        for sub_name, sub_info in subscribers_map.items():
            sub_id = self.intern_sym(sub_name)
            subscribers_dict[sub_id] = sub_info

        publishers_map = self.extract_publishers(src)
        publishers_dict = {}
        for pub_name, pub_info in publishers_map.items():
            pub_id = self.intern_sym(pub_name)
            publishers_dict[pub_id] = pub_info

        # Broker configs
        broker_configs = []
        broker_type = self.detect_broker_type(src)
        if broker_type:
            broker_configs.append(
                BrokerConfig(
                    broker_type=broker_type,
                    connection_url=None,
                    middlewares=[],
                    graceful_timeout=None,
                    apply_types=True,
                )
            )

        has_async = self.detect_async(src)
        has_middleware = self.detect_middleware(src)
        has_lifecycle = self.detect_lifecycle_hooks(src)

        return ModuleV6(
            pri=pri,
            size=lines,
            exports=exp_ids,
            imports=self.extract_imports_v6(src),
            subscribers=subscribers_dict,
            publishers=publishers_dict,
            broker_configs=broker_configs,
            has_async=has_async,
            has_middleware=has_middleware,
            has_lifecycle_hooks=has_lifecycle,
            src=self.minify_python(src) if pri <= 2 else None,
        )

    def discover(self):
        all_mods = []

        # Find FastStream source
        src_dir = self.root / "faststream"
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
        """Build dependency + message flow graph"""
        weights: Dict[int, Dict[int, int]] = {i: {} for i in range(len(self.modules))}
        message_graph: Dict[int, Dict[int, List[str]]] = {
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

                            # Track message flow
                            if token in CORE_CLASSES:
                                message_graph[mid][dep] = message_graph[mid].get(
                                    dep, []
                                ) + ["uses_broker"]

        def bucket_weight(w: int) -> int:
            return 3 if w >= 10 else 2 if w >= 5 else 1

        wdg = [
            (f, [(t, bucket_weight(w)) for t, w in deps.items()])
            for f, deps in weights.items()
            if deps
        ]
        dg = [(f, [t for t, _ in deps]) for f, deps in wdg]

        return wdg, dg, message_graph

    def generate(self, output: str):
        wdg, dg, message_graph = self.build_graph_v6()

        # Build module map
        mods = []
        for m in self.modules:
            # Serialize subscribers
            subs_serializable = {}
            for sub_id, sub_info in m.subscribers.items():
                subs_serializable[sub_id] = {
                    "handler_name": sub_info.handler_name,
                    "queue_or_topic": sub_info.queue_or_topic,
                    "broker_type": sub_info.broker_type,
                    "dependencies": sub_info.dependencies,
                    "ack_mode": sub_info.ack_mode,
                }

            # Serialize publishers
            pubs_serializable = {}
            for pub_id, pub_info in m.publishers.items():
                pubs_serializable[pub_id] = {
                    "publisher_name": pub_info.publisher_name,
                    "destination": pub_info.destination,
                    "broker_type": pub_info.broker_type,
                    "is_rpc": pub_info.is_rpc,
                }

            # Serialize broker configs
            configs_serializable = [
                {
                    "broker_type": cfg.broker_type,
                    "apply_types": cfg.apply_types,
                }
                for cfg in m.broker_configs
            ]

            mod_entry = (
                m.pri,
                m.size,
                m.exports,
                m.imports,
                subs_serializable,
                pubs_serializable,
                configs_serializable,
                m.has_async,
                m.has_middleware,
                m.has_lifecycle_hooks,
            )
            mods.append(mod_entry)

        bundle = {
            "V": 6,
            "F": "faststream",
            "S": self.strs,
            "Y": self.syms,
            "M": mods,
            "W": wdg,
            "D": dg,
            "C": {i: m.src for i, m in enumerate(self.modules) if m.src},
            "BROKERS": BROKER_TYPES,
            "PATTERNS": BROKER_PATTERNS,
            "ASYNC": ASYNC_PATTERNS,
            "FEATURES": BROKER_FEATURES,
            "MIDDLEWARE": MIDDLEWARE_TYPES,
            "DECORATORS": DECORATOR_PATTERNS,
            "R": message_graph,
            "t": {
                "f": len(self.modules),
                "l": self.stats["lines"],
                **{k: self.stats[k] for k in ["c", "h", "n", "l", "s"]},
                "version": 6,
                "framework": "faststream",
                "async_native": True,
                "multi_broker": True,
            },
        }

        json_str = json.dumps(bundle, separators=(",", ":"))
        out = self.root / output
        out.write_text(json_str)

        raw = len(json_str)
        comp = len(zlib.compress(json_str.encode(), 9))

        print(f"\n{'=' * 50}")
        print(
            f"CALYX-FASTSTREAM v6.0: {len(self.modules)} modules, {self.stats['lines']} lines"
        )
        print(f"Symbols: {len(self.syms)} | Strings: {len(self.strs)}")
        print(f"Multi-Broker: {len(BROKER_TYPES)} brokers")
        print(f"Async Native: Yes")
        print(
            f"Raw: {raw / 1024:.1f} KB | Compressed: {comp / 1024:.1f} KB ({comp / raw * 100:.1f}%)"
        )
        print(f"{'=' * 50}")


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--root", default="./faststream")
    p.add_argument("--output", default="calyx_faststream_v6.json")
    p.add_argument("--max-lines", type=int, default=30000)
    args = p.parse_args()

    b = CalyxFastStreamBundlerV6(args.root, args.max_lines)
    b.discover()
    b.generate(args.output)


if __name__ == "__main__":
    main()
