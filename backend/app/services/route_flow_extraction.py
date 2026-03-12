from __future__ import annotations

import ast
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

from app.services.identity import make_route_id


_DB_READ_METHODS = {"query", "get", "first", "all", "one", "one_or_none", "scalar", "scalars", "fetchone", "fetchall"}
_DB_WRITE_METHODS = {"add", "add_all", "delete", "merge", "update", "insert", "bulk_save_objects", "bulk_insert_mappings"}
_DB_COMMIT_METHODS = {"commit", "flush", "refresh", "rollback", "save"}
_DB_ROOT_NAMES = {"db", "session", "conn", "connection", "engine", "cursor"}
_EXTERNAL_ROOTS = {"requests", "httpx", "aiohttp", "urllib", "axios", "fetch", "openai", "anthropic", "boto3", "stripe", "s3"}
_RESPONSE_ROOTS = {"response", "res", "reply"}
_RESPONSE_METHODS = {"json", "send", "status", "end"}
_SERVICE_PATH_HINTS = ("/service/", "/services/", "/usecase/", "/usecases/", "/domain/", "/logic/")
_REPOSITORY_PATH_HINTS = ("/repository/", "/repositories/", "/repo/", "/repos/", "/dao/", "/store/")
_EXTERNAL_PATH_HINTS = ("/gateway/", "/gateways/", "/client/", "/clients/", "/integration/", "/integrations/")
_DATA_PATH_HINTS = ("/db/", "/database/", "/models/", "/orm/", "/entity/", "/entities/")
_SKIP_CALL_NAMES = {"Depends", "Query", "Body", "Path", "File", "Form"}
_JS_IMPORT_RE = re.compile(
    r"import\s+(?P<binding>[A-Za-z_$][\w$]*(?:\s*,\s*\{[^}]+\})?|\{[^}]+\})\s+from\s+['\"](?P<path>[^'\"]+)['\"]"
)
_JS_REQUIRE_RE = re.compile(
    r"(?:const|let|var)\s+(?P<alias>[A-Za-z_$][\w$]*)\s*=\s*require\(\s*['\"](?P<path>[^'\"]+)['\"]\s*\)"
)
_JS_MEMBER_CALL_RE = re.compile(r"(?P<object>[A-Za-z_$][\w$]*)\s*\.\s*(?P<method>[A-Za-z_$][\w$]*)\s*\(")
_JS_CALL_RE = re.compile(r"(?<!function\s)(?<!class\s)(?<!new\s)(?P<name>[A-Za-z_$][\w$]*)\s*\(")


def enrich_routes_with_flows(
    files: list[dict],
    root: str,
    routes: list[dict],
    components: list[dict],
    import_graph: dict,
) -> list[dict]:
    extractor = _RouteFlowExtractor(
        files=files,
        root=root,
        components=components,
        import_graph=import_graph,
    )
    enriched: list[dict] = []
    for route in routes:
        route_copy = dict(route)
        request_flow = extractor.extract(route_copy)
        route_copy["request_flow"] = request_flow
        enriched.append(route_copy)
    return enriched


class _RouteFlowExtractor:
    def __init__(self, files: list[dict], root: str, components: list[dict], import_graph: dict):
        self._files = files
        self._root = root
        self._components = components
        self._import_graph = import_graph
        self._all_paths = {str(file_info.get("path") or "") for file_info in files}
        self._component_index = {str(component.get("name") or ""): component for component in components}
        self._ast_cache: dict[str, Optional[ast.Module]] = {}
        self._source_cache: dict[str, str] = {}
        self._py_import_cache: dict[str, dict[str, dict]] = {}
        self._js_import_cache: dict[str, dict[str, dict]] = {}

    def extract(self, route: dict) -> dict:
        method = str(route.get("method") or "GET").upper()
        path = str(route.get("path") or "/")
        file_path = str(route.get("file") or "")
        route_id = make_route_id(method, path, file_path)

        stages: list[dict] = []
        seen_traces: set[tuple[str, str, str]] = set()

        self._append_stage(
            stages,
            stage_type="dispatch",
            label=f"Dispatch {method} {path}",
            file_path=file_path,
            symbol_name=route.get("handler_function"),
            class_name=route.get("controller_name"),
            line_start=route.get("line_start"),
            line_end=route.get("line_end"),
            confidence=min(float(route.get("confidence") or 0.8), 0.99),
            provenance="route_detection",
            selection_reason="Route definition provides the request entry point.",
            target_rank=1,
        )

        middleware = [item for item in route.get("middleware") or [] if item]
        auth_hints = [item for item in route.get("auth_hints") or [] if item]
        validation_hints = [item for item in route.get("validation_hints") or [] if item]

        generic_middleware = [item for item in middleware if item not in auth_hints and item not in validation_hints]
        if generic_middleware:
            self._append_stage(
                stages,
                stage_type="middleware",
                label=f"Run middleware: {', '.join(generic_middleware[:3])}",
                file_path=file_path,
                line_start=route.get("line_start"),
                line_end=route.get("line_end"),
                confidence=0.8,
                provenance="route_metadata",
                selection_reason="Route metadata includes explicit middleware names.",
                target_rank=2,
                hints=generic_middleware,
            )

        if auth_hints:
            self._append_stage(
                stages,
                stage_type="auth",
                label=f"Authorize request via {', '.join(auth_hints[:3])}",
                file_path=file_path,
                line_start=route.get("line_start"),
                line_end=route.get("line_end"),
                confidence=0.84,
                provenance="route_metadata",
                selection_reason="Route metadata includes explicit auth or guard hints.",
                target_rank=2,
                hints=auth_hints,
            )

        if validation_hints:
            self._append_stage(
                stages,
                stage_type="validation",
                label=f"Validate input via {', '.join(validation_hints[:3])}",
                file_path=file_path,
                line_start=route.get("line_start"),
                line_end=route.get("line_end"),
                confidence=0.84,
                provenance="route_metadata",
                selection_reason="Route metadata includes explicit validation hints.",
                target_rank=2,
                hints=validation_hints,
            )

        handler_file = file_path
        handler_symbol = route.get("handler_function")
        handler_class = route.get("controller_name")
        handler_lines = (route.get("line_start"), route.get("line_end"))

        extension = Path(file_path).suffix.lower()
        if extension in {".js", ".jsx", ".ts", ".tsx", ".mjs"}:
            resolved = self._resolve_js_handler(route)
            if resolved:
                handler_file = resolved.get("file_path") or handler_file
                handler_symbol = resolved.get("symbol_name") or handler_symbol
                handler_class = resolved.get("class_name") or handler_class
                handler_lines = (resolved.get("line_start"), resolved.get("line_end"))

        self._append_stage(
            stages,
            stage_type="handler",
            label=self._handler_label(method, path, handler_symbol, handler_class),
            file_path=handler_file,
            symbol_name=handler_symbol,
            class_name=handler_class,
            line_start=handler_lines[0],
            line_end=handler_lines[1],
            confidence=0.92 if handler_symbol else 0.72,
            provenance="direct_handler",
            selection_reason="Handler metadata identifies the code entry for this route.",
            target_rank=1,
        )

        if extension == ".py":
            stages.extend(
                self._trace_python_symbol(
                    file_path=handler_file,
                    symbol_name=str(handler_symbol or ""),
                    class_name=str(handler_class or "") or None,
                    depth=0,
                    seen=seen_traces,
                )
            )
        elif extension in {".js", ".jsx", ".ts", ".tsx", ".mjs"}:
            stages.extend(
                self._trace_js_symbol(
                    file_path=handler_file,
                    symbol_name=str(handler_symbol or ""),
                    class_name=str(handler_class or "") or None,
                    depth=0,
                    seen=seen_traces,
                )
            )

        self._append_stage(
            stages,
            stage_type="response",
            label=self._response_label(method),
            file_path=handler_file or file_path,
            symbol_name=handler_symbol,
            class_name=handler_class,
            line_start=handler_lines[0],
            line_end=handler_lines[1],
            confidence=0.7,
            provenance="route_completion",
            selection_reason="Routes complete by returning a response to the client.",
            target_rank=4,
        )

        normalized = self._normalize_stages(stages)
        summary = {
            "has_middleware": any(stage["stage_type"] == "middleware" for stage in normalized),
            "has_auth": any(stage["stage_type"] == "auth" for stage in normalized),
            "has_validation": any(stage["stage_type"] == "validation" for stage in normalized),
            "has_service": any(stage["stage_type"] == "service" for stage in normalized),
            "has_repository": any(stage["stage_type"] == "repository" for stage in normalized),
            "has_data_access": any(stage["stage_type"] == "data_access" for stage in normalized),
            "has_external": any(stage["stage_type"] == "external" for stage in normalized),
            "languages": self._stage_languages(normalized),
        }
        average_confidence = round(
            sum(float(stage.get("confidence") or 0.0) for stage in normalized) / max(len(normalized), 1),
            2,
        )

        return {
            "route_id": route_id,
            "stage_count": len(normalized),
            "confidence": average_confidence,
            "summary": summary,
            "stages": normalized,
        }

    def _resolve_js_handler(self, route: dict) -> Optional[dict]:
        controller_name = str(route.get("controller_name") or "")
        if not controller_name:
            return None
        imports = self._js_imports(str(route.get("file") or ""))
        target = imports.get(controller_name)
        if not target:
            return None
        symbol_name = str(route.get("handler_function") or "") or None
        body = self._find_js_symbol(target.get("file_path") or "", symbol_name or "", controller_name)
        if not body:
            return {
                "file_path": target.get("file_path"),
                "symbol_name": symbol_name,
                "class_name": controller_name,
            }
        return {
            "file_path": target.get("file_path"),
            "symbol_name": symbol_name,
            "class_name": controller_name,
            "line_start": body.get("line_start"),
            "line_end": body.get("line_end"),
        }

    def _trace_python_symbol(
        self,
        file_path: str,
        symbol_name: str,
        class_name: Optional[str],
        depth: int,
        seen: set[tuple[str, str, str]],
    ) -> list[dict]:
        if not file_path or not symbol_name or depth > 2:
            return []
        trace_key = (file_path, class_name or "", symbol_name)
        if trace_key in seen:
            return []
        seen.add(trace_key)

        symbol = self._find_python_symbol(file_path, symbol_name, class_name)
        if not symbol:
            return []

        imports = self._python_imports(file_path)
        call_stages: list[dict] = []
        for call in self._ordered_python_calls(symbol["node"]):
            stage = self._classify_python_call(file_path, call, imports, depth)
            if not stage:
                continue
            call_stages.append(stage)
            nested_target = stage.get("nested_target") or {}
            nested_file = nested_target.get("file_path")
            nested_symbol = nested_target.get("symbol_name")
            nested_class = nested_target.get("class_name")
            if nested_file and nested_symbol and stage["stage_type"] in {"service", "repository"}:
                call_stages.extend(
                    self._trace_python_symbol(
                        file_path=nested_file,
                        symbol_name=nested_symbol,
                        class_name=nested_class,
                        depth=depth + 1,
                        seen=seen,
                    )
                )
        return call_stages

    def _trace_js_symbol(
        self,
        file_path: str,
        symbol_name: str,
        class_name: Optional[str],
        depth: int,
        seen: set[tuple[str, str, str]],
    ) -> list[dict]:
        if not file_path or not symbol_name or depth > 2:
            return []
        trace_key = (file_path, class_name or "", symbol_name)
        if trace_key in seen:
            return []
        seen.add(trace_key)

        body = self._find_js_symbol(file_path, symbol_name, class_name)
        if not body:
            return []
        imports = self._js_imports(file_path)
        stages: list[dict] = []
        for call in self._ordered_js_calls(body.get("body") or ""):
            stage = self._classify_js_call(file_path, body, call, imports, depth)
            if not stage:
                continue
            stages.append(stage)
            nested_target = stage.get("nested_target") or {}
            nested_file = nested_target.get("file_path")
            nested_symbol = nested_target.get("symbol_name")
            nested_class = nested_target.get("class_name")
            if nested_file and nested_symbol and stage["stage_type"] in {"service", "repository"}:
                stages.extend(
                    self._trace_js_symbol(
                        file_path=nested_file,
                        symbol_name=nested_symbol,
                        class_name=nested_class,
                        depth=depth + 1,
                        seen=seen,
                    )
                )
        return stages

    def _classify_python_call(self, file_path: str, call: ast.Call, imports: dict[str, dict], depth: int) -> Optional[dict]:
        root_name, members = _flatten_call_target(call.func)
        if not root_name:
            return None
        member = members[-1] if members else None
        if root_name in _SKIP_CALL_NAMES:
            return None
        if root_name in _RESPONSE_ROOTS or member in _RESPONSE_METHODS:
            return None

        imported = imports.get(root_name)
        if imported:
            target_file = imported.get("file_path")
            role = _role_for_path(target_file)
            symbol_name = imported.get("symbol_name") or member or root_name
            class_name = None
            if imported.get("import_kind") == "class":
                class_name = imported.get("symbol_name") or root_name
                if member:
                    symbol_name = member
            elif imported.get("import_kind") == "module" and member:
                symbol_name = member
            if role in {"service", "repository", "external", "data_access"}:
                line_start = getattr(call, "lineno", None)
                if role == "data_access" and not _is_strong_data_access_target(target_file, symbol_name, member):
                    return None
                stage_type = role if role != "data_access" else "data_access"
                stage = self._make_stage(
                    stage_type=stage_type,
                    label=self._call_label(stage_type, symbol_name, target_file),
                    file_path=target_file or file_path,
                    symbol_name=symbol_name,
                    class_name=class_name,
                    line_start=line_start,
                    line_end=getattr(call, "end_lineno", line_start),
                    confidence=0.82 if depth == 0 else 0.76,
                    provenance="import_tracing",
                    selection_reason="Call target resolves to a local module with a strong structural role.",
                    target_rank=2 if stage_type in {"service", "repository"} else 3,
                    nested_target={
                        "file_path": target_file,
                        "symbol_name": symbol_name,
                        "class_name": class_name,
                    },
                )
                return stage

        if root_name in _DB_ROOT_NAMES or any(name in _DB_READ_METHODS | _DB_WRITE_METHODS | _DB_COMMIT_METHODS for name in members):
            line_start = getattr(call, "lineno", None)
            stage_type = self._db_stage_type(root_name, members)
            return self._make_stage(
                stage_type=stage_type,
                label=self._db_label(stage_type, root_name, members),
                file_path=file_path,
                line_start=line_start,
                line_end=getattr(call, "end_lineno", line_start),
                confidence=0.78,
                provenance="direct_code_signal",
                selection_reason="Call chain matches common database session or persistence methods.",
                target_rank=3,
            )

        if root_name in _EXTERNAL_ROOTS or _looks_external(member or root_name):
            line_start = getattr(call, "lineno", None)
            return self._make_stage(
                stage_type="external",
                label=f"Call external dependency via {root_name}",
                file_path=file_path,
                symbol_name=member or root_name,
                line_start=line_start,
                line_end=getattr(call, "end_lineno", line_start),
                confidence=0.72,
                provenance="direct_code_signal",
                selection_reason="Call target matches common external client libraries.",
                target_rank=3,
            )
        return None

    def _classify_js_call(self, file_path: str, body: dict, call: dict, imports: dict[str, dict], depth: int) -> Optional[dict]:
        root_name = str(call.get("root") or "")
        member = str(call.get("member") or "") or None
        if not root_name:
            return None
        if root_name in _RESPONSE_ROOTS or member in _RESPONSE_METHODS:
            return None

        imported = imports.get(root_name)
        if imported:
            target_file = imported.get("file_path")
            role = _role_for_path(target_file)
            symbol_name = imported.get("symbol_name") or member or root_name
            class_name = None
            if imported.get("import_kind") == "class":
                class_name = imported.get("symbol_name") or root_name
                if member:
                    symbol_name = member
            elif imported.get("import_kind") == "module" and member:
                symbol_name = member
            if role in {"service", "repository", "external", "data_access"}:
                if role == "data_access" and not _is_strong_data_access_target(target_file, symbol_name, member):
                    return None
                stage_type = role if role != "data_access" else "data_access"
                return self._make_stage(
                    stage_type=stage_type,
                    label=self._call_label(stage_type, symbol_name, target_file),
                    file_path=target_file or file_path,
                    symbol_name=symbol_name,
                    class_name=class_name,
                    line_start=body.get("line_start", 1) + int(call.get("line_offset") or 0),
                    line_end=body.get("line_start", 1) + int(call.get("line_offset") or 0),
                    confidence=0.8 if depth == 0 else 0.74,
                    provenance="import_tracing",
                    selection_reason="Call target resolves to a local module with a strong structural role.",
                    target_rank=2 if stage_type in {"service", "repository"} else 3,
                    nested_target={
                        "file_path": target_file,
                        "symbol_name": symbol_name,
                        "class_name": class_name,
                    },
                )

        if root_name in _DB_ROOT_NAMES or member in _DB_READ_METHODS | _DB_WRITE_METHODS | _DB_COMMIT_METHODS:
            line_number = body.get("line_start", 1) + int(call.get("line_offset") or 0)
            stage_type = self._db_stage_type(root_name, [member] if member else [])
            return self._make_stage(
                stage_type=stage_type,
                label=self._db_label(stage_type, root_name, [member] if member else []),
                file_path=file_path,
                line_start=line_number,
                line_end=line_number,
                confidence=0.74,
                provenance="direct_code_signal",
                selection_reason="Call chain matches common persistence methods.",
                target_rank=3,
            )

        if root_name in _EXTERNAL_ROOTS or _looks_external(member or root_name):
            line_number = body.get("line_start", 1) + int(call.get("line_offset") or 0)
            return self._make_stage(
                stage_type="external",
                label=f"Call external dependency via {root_name}",
                file_path=file_path,
                symbol_name=member or root_name,
                line_start=line_number,
                line_end=line_number,
                confidence=0.7,
                provenance="direct_code_signal",
                selection_reason="Call target matches common external client libraries.",
                target_rank=3,
            )
        return None

    def _ordered_python_calls(self, node: ast.AST) -> list[ast.Call]:
        calls = [child for child in ast.walk(node) if isinstance(child, ast.Call)]
        return sorted(calls, key=lambda child: (getattr(child, "lineno", 0), getattr(child, "col_offset", 0)))

    def _ordered_js_calls(self, body: str) -> list[dict]:
        calls: list[dict] = []
        lines = body.splitlines()
        for index, line in enumerate(lines):
            for match in _JS_MEMBER_CALL_RE.finditer(line):
                calls.append({
                    "root": match.group("object"),
                    "member": match.group("method"),
                    "line_offset": index,
                })
            for match in _JS_CALL_RE.finditer(line):
                name = match.group("name")
                if name in {"if", "for", "while", "switch", "catch", "return"}:
                    continue
                calls.append({"root": name, "member": None, "line_offset": index})
        calls.sort(key=lambda item: int(item.get("line_offset") or 0))
        return calls

    def _python_imports(self, file_path: str) -> dict[str, dict]:
        if file_path in self._py_import_cache:
            return self._py_import_cache[file_path]
        tree = self._parse_python_file(file_path)
        if tree is None:
            self._py_import_cache[file_path] = {}
            return {}
        imports: dict[str, dict] = {}
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ImportFrom):
                resolved_module = self._resolve_python_module(file_path, node.module, node.level)
                for alias in node.names:
                    alias_name = alias.asname or alias.name
                    imports[alias_name] = {
                        "file_path": resolved_module,
                        "symbol_name": alias.name if alias.name != "*" else None,
                        "import_kind": "class" if alias.name[:1].isupper() else "symbol",
                    }
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    alias_name = alias.asname or alias.name.split(".")[-1]
                    imports[alias_name] = {
                        "file_path": self._resolve_python_module(file_path, alias.name, 0),
                        "symbol_name": None,
                        "import_kind": "module",
                    }
        self._py_import_cache[file_path] = imports
        return imports

    def _js_imports(self, file_path: str) -> dict[str, dict]:
        if file_path in self._js_import_cache:
            return self._js_import_cache[file_path]
        content = self._read_text(file_path)
        imports: dict[str, dict] = {}
        if not content:
            self._js_import_cache[file_path] = imports
            return imports
        for match in _JS_IMPORT_RE.finditer(content):
            binding = match.group("binding").strip()
            resolved = self._resolve_js_module(file_path, match.group("path"))
            if binding.startswith("{") and binding.endswith("}"):
                for raw_name in binding[1:-1].split(","):
                    raw_name = raw_name.strip()
                    if not raw_name:
                        continue
                    symbol_name = raw_name.split(" as ")[0].strip()
                    alias_name = raw_name.split(" as ")[-1].strip()
                    imports[alias_name] = {
                        "file_path": resolved,
                        "symbol_name": symbol_name,
                        "import_kind": "class" if symbol_name[:1].isupper() else "symbol",
                    }
                continue
            default_name = binding.split(",", 1)[0].strip()
            imports[default_name] = {
                "file_path": resolved,
                "symbol_name": default_name,
                "import_kind": "class" if default_name[:1].isupper() else "module",
            }
        for match in _JS_REQUIRE_RE.finditer(content):
            alias_name = match.group("alias")
            imports[alias_name] = {
                "file_path": self._resolve_js_module(file_path, match.group("path")),
                "symbol_name": alias_name,
                "import_kind": "class" if alias_name[:1].isupper() else "module",
            }
        self._js_import_cache[file_path] = imports
        return imports

    def _resolve_python_module(self, file_path: str, module: Optional[str], level: int) -> Optional[str]:
        parts: list[str]
        if level > 0:
            base_parts = [part for part in os.path.dirname(file_path).split("/") if part]
            trim = max(level - 1, 0)
            if trim:
                base_parts = base_parts[:-trim]
            module_parts = [part for part in str(module or "").split(".") if part]
            parts = base_parts + module_parts
        else:
            parts = [part for part in str(module or "").split(".") if part]
        candidates: list[str] = []
        if parts:
            joined = "/".join(parts)
            candidates.append(f"{joined}.py")
            candidates.append(f"{joined}/__init__.py")
        return self._pick_existing_path(candidates)

    def _resolve_js_module(self, file_path: str, module: str) -> Optional[str]:
        if not module or not module.startswith("."):
            return None
        base_dir = os.path.dirname(file_path)
        raw = os.path.normpath(os.path.join(base_dir, module)).replace("\\", "/")
        candidates = [raw, f"{raw}.ts", f"{raw}.tsx", f"{raw}.js", f"{raw}.jsx", f"{raw}.mjs", f"{raw}/index.ts", f"{raw}/index.tsx", f"{raw}/index.js", f"{raw}/index.jsx"]
        return self._pick_existing_path(candidates)

    def _pick_existing_path(self, candidates: list[str]) -> Optional[str]:
        for candidate in candidates:
            if candidate in self._all_paths:
                return candidate
        for candidate in candidates:
            matches = [path for path in self._all_paths if path.endswith(candidate)]
            if len(matches) == 1:
                return matches[0]
        return None

    def _find_python_symbol(self, file_path: str, symbol_name: str, class_name: Optional[str]) -> Optional[dict]:
        tree = self._parse_python_file(file_path)
        if tree is None:
            return None
        if class_name:
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef) or node.name != class_name:
                    continue
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == symbol_name:
                        return {
                            "node": child,
                            "line_start": getattr(child, "lineno", None),
                            "line_end": getattr(child, "end_lineno", getattr(child, "lineno", None)),
                        }
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol_name:
                return {
                    "node": node,
                    "line_start": getattr(node, "lineno", None),
                    "line_end": getattr(node, "end_lineno", getattr(node, "lineno", None)),
                }
        return None

    def _find_js_symbol(self, file_path: str, symbol_name: str, class_name: Optional[str]) -> Optional[dict]:
        source = self._read_text(file_path)
        if not source or not symbol_name:
            return None

        patterns: list[re.Pattern[str]] = []
        if class_name:
            class_match = re.search(rf"class\s+{re.escape(class_name)}\b", source)
            if class_match:
                class_open = source.find("{", class_match.end())
                class_close = _match_brace(source, class_open)
                if class_open != -1 and class_close != -1:
                    class_body = source[class_open + 1:class_close]
                    method_match = re.search(rf"(?:static\s+)?(?:async\s+)?{re.escape(symbol_name)}\s*\([^)]*\)\s*\{{", class_body)
                    if method_match:
                        start = class_open + 1 + method_match.start()
                        body_open = source.find("{", start)
                        body_close = _match_brace(source, body_open)
                        if body_open != -1 and body_close != -1:
                            return {
                                "body": source[body_open + 1:body_close],
                                "line_start": source.count("\n", 0, start) + 1,
                                "line_end": source.count("\n", 0, body_close) + 1,
                            }

        patterns.extend(
            [
                re.compile(rf"function\s+{re.escape(symbol_name)}\s*\([^)]*\)\s*\{{"),
                re.compile(rf"(?:const|let|var)\s+{re.escape(symbol_name)}\s*=\s*(?:async\s*)?\([^)]*\)\s*=>\s*\{{"),
                re.compile(rf"(?:const|let|var)\s+{re.escape(symbol_name)}\s*=\s*function\s*\([^)]*\)\s*\{{"),
                re.compile(rf"exports\.{re.escape(symbol_name)}\s*=\s*(?:async\s*)?\([^)]*\)\s*=>\s*\{{"),
            ]
        )
        for pattern in patterns:
            match = pattern.search(source)
            if not match:
                continue
            open_brace = source.find("{", match.start())
            close_brace = _match_brace(source, open_brace)
            if open_brace != -1 and close_brace != -1:
                return {
                    "body": source[open_brace + 1:close_brace],
                    "line_start": source.count("\n", 0, match.start()) + 1,
                    "line_end": source.count("\n", 0, close_brace) + 1,
                }
        return None

    def _parse_python_file(self, file_path: str) -> Optional[ast.Module]:
        if file_path in self._ast_cache:
            return self._ast_cache[file_path]
        source = self._read_text(file_path)
        if not source:
            self._ast_cache[file_path] = None
            return None
        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError:
            tree = None
        self._ast_cache[file_path] = tree
        return tree

    def _read_text(self, file_path: str) -> str:
        if file_path in self._source_cache:
            return self._source_cache[file_path]
        full_path = os.path.join(self._root, file_path)
        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as handle:
                content = handle.read()
        except OSError:
            content = ""
        self._source_cache[file_path] = content
        return content

    def _db_stage_type(self, root_name: str, members: list[Optional[str]]) -> str:
        member_names = {name for name in members if name}
        if member_names & _DB_READ_METHODS:
            return "data_access"
        if member_names & (_DB_WRITE_METHODS | _DB_COMMIT_METHODS):
            return "data_access"
        if root_name in _DB_ROOT_NAMES:
            return "data_access"
        return "repository"

    def _db_label(self, stage_type: str, root_name: str, members: list[Optional[str]]) -> str:
        methods = [name for name in members if name]
        if methods:
            return f"Perform persistence via {root_name}.{'.'.join(methods[:3])}"
        return "Perform persistence operations"

    def _call_label(self, stage_type: str, symbol_name: str, file_path: Optional[str]) -> str:
        file_hint = Path(file_path or "").name
        if stage_type == "service":
            return f"Run service {symbol_name}"
        if stage_type == "repository":
            return f"Access repository {symbol_name}"
        if stage_type == "external":
            return f"Call external integration {symbol_name}"
        if stage_type == "data_access":
            return f"Perform persistence step {symbol_name}"
        return f"Call {symbol_name or file_hint}"

    def _handler_label(self, method: str, path: str, handler_symbol: Optional[str], handler_class: Optional[str]) -> str:
        if handler_class and handler_symbol:
            return f"Handle {method} {path} in {handler_class}.{handler_symbol}"
        if handler_symbol:
            return f"Handle {method} {path} in {handler_symbol}"
        return f"Handle {method} {path}"

    def _response_label(self, method: str) -> str:
        status = {"POST": "201", "DELETE": "204", "GET": "200", "PUT": "200", "PATCH": "200"}.get(method, "200")
        return f"Return {status} response"

    def _normalize_stages(self, stages: list[dict]) -> list[dict]:
        normalized: list[dict] = []
        seen: set[tuple[str, str, str, str]] = set()
        for stage in stages:
            stage_type = str(stage.get("stage_type") or "")
            file_path = str(stage.get("file_path") or "")
            symbol_name = str(stage.get("symbol_name") or "")
            class_name = str(stage.get("class_name") or "")
            key = (stage_type, file_path, class_name, symbol_name)
            if key in seen and stage_type not in {"dispatch", "response"}:
                continue
            seen.add(key)
            cleaned = {key_name: value for key_name, value in stage.items() if key_name != "nested_target"}
            normalized.append(cleaned)
        for index, stage in enumerate(normalized, start=1):
            stage["step"] = index
        return normalized

    def _stage_languages(self, stages: list[dict]) -> list[str]:
        languages: set[str] = set()
        for stage in stages:
            file_path = str(stage.get("file_path") or "")
            suffix = Path(file_path).suffix.lower()
            if suffix == ".py":
                languages.add("Python")
            elif suffix in {".js", ".jsx"}:
                languages.add("JavaScript")
            elif suffix in {".ts", ".tsx"}:
                languages.add("TypeScript")
        return sorted(languages)

    def _append_stage(self, stages: list[dict], **kwargs) -> None:
        stages.append(self._make_stage(**kwargs))

    def _make_stage(self, **kwargs) -> dict:
        stage_type = str(kwargs.get("stage_type") or "unknown")
        file_path = str(kwargs.get("file_path") or "")
        symbol_name = kwargs.get("symbol_name")
        class_name = kwargs.get("class_name")
        line_start = kwargs.get("line_start")
        line_end = kwargs.get("line_end") or line_start
        target_rank = int(kwargs.get("target_rank") or 3)
        selection_reason = str(kwargs.get("selection_reason") or "Deterministic route-flow stage.")
        confidence = round(float(kwargs.get("confidence") or 0.0), 2)
        return {
            "stage_type": stage_type,
            "label": str(kwargs.get("label") or stage_type.replace("_", " ")),
            "file_path": file_path,
            "symbol_name": symbol_name,
            "class_name": class_name,
            "line_start": line_start,
            "line_end": line_end,
            "confidence": confidence,
            "provenance": str(kwargs.get("provenance") or "direct"),
            "anchor_kind": "symbol" if symbol_name else "file",
            "target_rank": target_rank,
            "selection_reason": selection_reason,
            "evidence": {
                "file_path": file_path,
                "symbol_name": symbol_name,
                "class_name": class_name,
                "line_start": line_start,
                "line_end": line_end,
                "anchor_kind": "symbol" if symbol_name else "file",
                "target_rank": target_rank,
                "selection_reason": selection_reason,
            },
            "hints": list(kwargs.get("hints") or []),
            "nested_target": kwargs.get("nested_target"),
        }


def _flatten_call_target(node: ast.AST) -> tuple[Optional[str], list[str]]:
    if isinstance(node, ast.Call):
        return _flatten_call_target(node.func)
    if isinstance(node, ast.Attribute):
        root_name, members = _flatten_call_target(node.value)
        members.append(node.attr)
        return root_name, members
    if isinstance(node, ast.Name):
        return node.id, []
    return None, []


def _role_for_path(file_path: Optional[str]) -> Optional[str]:
    if not file_path:
        return None
    normalized_path = str(file_path).replace("\\", "/").lower().strip("/")
    normalized = f"/{normalized_path}"
    if any(hint in normalized for hint in _SERVICE_PATH_HINTS):
        return "service"
    if any(hint in normalized for hint in _REPOSITORY_PATH_HINTS):
        return "repository"
    if any(hint in normalized for hint in _EXTERNAL_PATH_HINTS):
        return "external"
    if any(hint in normalized for hint in _DATA_PATH_HINTS):
        return "data_access"
    return None


def _looks_external(name: str) -> bool:
    lowered = str(name or "").lower()
    if lowered.endswith("exception"):
        return False
    return any(token in lowered for token in ("http", "request", "client", "gateway", "stripe", "openai", "anthropic", "s3"))


def _is_strong_data_access_target(file_path: Optional[str], symbol_name: Optional[str], member: Optional[str]) -> bool:
    normalized = str(file_path or "").replace("\\", "/").lower()
    symbol = str(symbol_name or "").lower()
    member_name = str(member or "").lower()
    strong_path = any(token in normalized for token in ("/repository/", "/repositories/", "/dao/", "/db/", "/database/", "/orm/"))
    strong_symbol = any(token in symbol for token in ("repo", "repository", "store", "session", "query", "db"))
    strong_member = member_name in (_DB_READ_METHODS | _DB_WRITE_METHODS | _DB_COMMIT_METHODS)
    return strong_path or strong_symbol or strong_member


def _match_brace(source: str, open_index: int) -> int:
    if open_index < 0 or open_index >= len(source) or source[open_index] != "{":
        return -1
    depth = 0
    for index in range(open_index, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1