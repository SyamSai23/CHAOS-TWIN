from __future__ import annotations

import ast
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


_TEST_PATH_SEGMENTS = {
    "test",
    "tests",
    "__tests__",
    "spec",
    "specs",
    "features",
    "cypress",
}
_TEST_FILE_SUFFIXES = (
    ".spec.ts",
    ".spec.js",
    ".test.ts",
    ".test.js",
    ".spec.tsx",
    ".spec.jsx",
    ".test.tsx",
    ".test.jsx",
    "_test.py",
    "test_.py",
)
_JS_ROUTE_METHODS = {"get", "post", "put", "delete", "patch", "head", "options", "all"}
_PY_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}
_JAVA_ROUTE_RE = re.compile(
    r"@(Get|Post|Put|Delete|Request)Mapping\s*\(\s*(?:value\s*=\s*)?[\"']([^\"']+)[\"']",
    re.I,
)
_GO_ROUTE_RE = re.compile(
    r"""(?:http\.HandleFunc|[a-z]\.(?:GET|POST|PUT|DELETE|PATCH|Handle))\s*\(\s*[\"']([^\"']+)[\"']""",
    re.I,
)
_RUBY_ROUTE_RE = re.compile(
    r"\b(get|post|put|delete|patch|resources|resource)\s+[\"']([^\"']+)[\"']",
    re.I,
)
_JS_REQUIRE_RE = re.compile(
    r"(?:const|let|var)\s+(?P<alias>[A-Za-z_$][\w$]*)\s*=\s*require\(\s*[\"'](?P<path>[^\"']+)[\"']\s*\)"
)
_JS_IMPORT_RE = re.compile(
    r"import\s+(?P<alias>[A-Za-z_$][\w$]*)\s+from\s+[\"'](?P<path>[^\"']+)[\"']"
)
_JS_ROUTER_DEF_RE = re.compile(
    r"(?:const|let|var)\s+(?P<var>[A-Za-z_$][\w$]*)\s*=\s*(?:express\s*\.\s*)?Router\s*\("
)
_JS_APP_DEF_RE = re.compile(
    r"(?:const|let|var)\s+(?P<var>[A-Za-z_$][\w$]*)\s*=\s*express\s*\("
)
_JS_EXPORT_DEFAULT_FUNCTION_RE = re.compile(
    r"export\s+default\s+function\s*(?P<name>[A-Za-z_$][\w$]*)?\s*\("
)
_JS_CALL_TOKEN_RE = re.compile(
    r"\b(?P<object>[A-Za-z_$][\w$]*)\s*\.\s*(?P<method>route|use|get|post|put|delete|patch|head|options|all)\s*\(",
    re.I,
)
_AUTH_HINT_RE = re.compile(r"(?:^|[_.])(?:auth|jwt|login|required?|guard|session|passport|role|permission|acl)", re.I)
_VALIDATION_HINT_RE = re.compile(r"(?:^|[_.])(?:valid|schema|zod|yup|joi|marshal|sanitize|parser)", re.I)


@dataclass
class RouteCandidate:
    method: str
    path: str
    local_path: str
    file: str
    component: str
    handler_function: Optional[str] = None
    controller_name: Optional[str] = None
    router_prefix: str = ""
    middleware: list[str] = field(default_factory=list)
    auth_hints: list[str] = field(default_factory=list)
    validation_hints: list[str] = field(default_factory=list)
    detection_source: str = ""
    detection_rule: str = ""
    confidence: float = 0.0
    line_start: Optional[int] = None
    line_end: Optional[int] = None

    def dedupe_key(self) -> tuple:
        return (
            self.method,
            self.file,
            self.local_path,
            self.handler_function or "",
            self.controller_name or "",
            self.line_start or 0,
        )

    def strength_key(self) -> tuple:
        return (
            round(self.confidence, 4),
            1 if self.line_start is not None else 0,
            1 if self.handler_function else 0,
            1 if self.controller_name else 0,
            len(self.router_prefix or ""),
            len(self.path or ""),
        )

    def to_dict(self) -> dict:
        middleware = _stable_unique(self.middleware)
        auth_hints = _stable_unique(self.auth_hints)
        validation_hints = _stable_unique(self.validation_hints)
        best_target = _route_best_target(self)
        return {
            "method": self.method,
            "path": self.path,
            "local_path": self.local_path,
            "file": self.file,
            "component": self.component,
            "handler_function": self.handler_function,
            "controller_name": self.controller_name,
            "router_prefix": self.router_prefix,
            "middleware": middleware,
            "auth_hints": auth_hints,
            "validation_hints": validation_hints,
            "detection_source": self.detection_source,
            "detection_rule": self.detection_rule,
            "confidence": round(self.confidence, 2),
            "line_start": self.line_start,
            "line_end": self.line_end,
            "best_target": best_target,
            "evidence": {
                "file_path": self.file,
                "symbol_name": self.handler_function,
                "symbol_kind": "handler" if self.handler_function else None,
                "class_name": self.controller_name,
                "line_start": self.line_start,
                "line_end": self.line_end,
                "detection_source": self.detection_source,
                "detection_rule": self.detection_rule,
                "confidence": round(self.confidence, 2),
                "anchor_kind": best_target["anchor_kind"],
                "target_rank": best_target["target_rank"],
                "selection_reason": best_target["selection_reason"],
            },
        }


@dataclass
class JSImportContext:
    file: str
    component: str
    content: str
    masked: str
    router_vars: set[str] = field(default_factory=set)
    app_vars: set[str] = field(default_factory=set)
    imports: dict[str, str] = field(default_factory=dict)
    router_middleware: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    local_mount_prefixes: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    file_mount_prefixes: list[str] = field(default_factory=list)
    cross_file_mounts: list[tuple[str, str]] = field(default_factory=list)


def detect_routes(
    files: list[dict],
    languages: list[str],
    root: str,
    components: list[dict],
) -> list[dict]:
    candidates: list[RouteCandidate] = []
    component_name_for = _component_name_resolver(components)

    if "Python" in languages:
        for file_info in files:
            if file_info["extension"] != ".py" or _is_test_file(file_info["path"]):
                continue
            content = _safe_read(os.path.join(root, file_info["path"]))
            if not content:
                continue
            candidates.extend(
                _extract_python_route_candidates(
                    content=content,
                    file_path=file_info["path"],
                    component=component_name_for(file_info["path"]),
                )
            )

    if any(language in languages for language in ("JavaScript", "TypeScript")):
        js_files = [
            file_info
            for file_info in files
            if file_info["extension"] in {".js", ".ts", ".jsx", ".tsx", ".mjs"}
            and not _is_test_file(file_info["path"])
        ]
        contexts = _build_js_contexts(root=root, files=js_files, component_name_for=component_name_for)
        for context in contexts.values():
            candidates.extend(_extract_js_route_candidates(context))

    if "Java" in languages:
        for file_info in files:
            if file_info["extension"] != ".java" or _is_test_file(file_info["path"]):
                continue
            content = _safe_read(os.path.join(root, file_info["path"]))
            if not content:
                continue
            for match in _JAVA_ROUTE_RE.finditer(content):
                method_word = match.group(1).upper()
                method = {
                    "GET": "GET",
                    "POST": "POST",
                    "PUT": "PUT",
                    "DELETE": "DELETE",
                    "REQUEST": "ANY",
                }.get(method_word, method_word)
                local_path = _normalize_route_path(match.group(2))
                line_start, line_end = _line_span_from_indices(content, match.start(), match.end())
                candidates.append(
                    RouteCandidate(
                        method=method,
                        path=local_path,
                        local_path=local_path,
                        file=file_info["path"],
                        component=component_name_for(file_info["path"]),
                        detection_source="regex_scan",
                        detection_rule="java_mapping_annotation",
                        confidence=0.78,
                        line_start=line_start,
                        line_end=line_end,
                    )
                )

    if "Go" in languages:
        for file_info in files:
            if file_info["extension"] != ".go" or _is_test_file(file_info["path"]):
                continue
            content = _safe_read(os.path.join(root, file_info["path"]))
            if not content:
                continue
            for match in _GO_ROUTE_RE.finditer(content):
                local_path = _normalize_route_path(match.group(1))
                line_start, line_end = _line_span_from_indices(content, match.start(), match.end())
                candidates.append(
                    RouteCandidate(
                        method="ANY",
                        path=local_path,
                        local_path=local_path,
                        file=file_info["path"],
                        component=component_name_for(file_info["path"]),
                        detection_source="regex_scan",
                        detection_rule="go_http_handler",
                        confidence=0.72,
                        line_start=line_start,
                        line_end=line_end,
                    )
                )

    if "Ruby" in languages:
        for file_info in files:
            if os.path.basename(file_info["path"]) != "routes.rb" or _is_test_file(file_info["path"]):
                continue
            content = _safe_read(os.path.join(root, file_info["path"]))
            if not content:
                continue
            for match in _RUBY_ROUTE_RE.finditer(content):
                method_word = match.group(1).lower()
                method = method_word.upper() if method_word in {"get", "post", "put", "delete", "patch"} else "ANY"
                local_path = _normalize_route_path(match.group(2))
                line_start, line_end = _line_span_from_indices(content, match.start(), match.end())
                candidates.append(
                    RouteCandidate(
                        method=method,
                        path=local_path,
                        local_path=local_path,
                        file=file_info["path"],
                        component=component_name_for(file_info["path"]),
                        detection_source="regex_scan",
                        detection_rule="ruby_routes_file",
                        confidence=0.74,
                        line_start=line_start,
                        line_end=line_end,
                    )
                )

    return [candidate.to_dict() for candidate in _merge_route_candidates(candidates)]


def _extract_python_route_candidates(content: str, file_path: str, component: str) -> list[RouteCandidate]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    parent_map: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent_map[child] = node

    router_defs = _collect_python_router_defs(tree)
    mount_prefixes = _collect_python_mount_prefixes(tree)
    candidates: list[RouteCandidate] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        controller_name = _python_parent_class_name(node, parent_map)
        extra_decorators = [_short_expr_name(decorator) for decorator in node.decorator_list]
        non_route_decorators = [name for name in extra_decorators if name and not _looks_like_python_route_decorator(name)]

        for decorator in node.decorator_list:
            route_specs = _parse_python_route_decorator(decorator, router_defs)
            if not route_specs:
                continue

            for route_spec in route_specs:
                base_var = route_spec["base_var"]
                local_path = route_spec["local_path"]
                router_meta = router_defs.get(base_var, {})
                inherited_prefixes = mount_prefixes.get(base_var, [""])
                if not inherited_prefixes:
                    inherited_prefixes = [""]
                router_prefix = _normalize_route_prefix(router_meta.get("prefix"))
                route_dependencies = route_spec.get("dependencies", [])
                router_dependencies = router_meta.get("dependencies", [])
                middleware = router_dependencies + route_dependencies
                auth_hints = _classify_auth_hints(router_meta.get("auth_hints", []) + route_dependencies + non_route_decorators)
                validation_hints = _classify_validation_hints(router_meta.get("validation_hints", []) + route_dependencies + non_route_decorators)
                line_start = getattr(node, "lineno", None)
                line_end = getattr(node, "end_lineno", line_start)

                for mount_prefix in inherited_prefixes:
                    combined_prefix = _join_route_path(mount_prefix, router_prefix)
                    full_path = _join_route_path(combined_prefix, local_path)
                    confidence = min(
                        route_spec["confidence"]
                        + (0.02 if combined_prefix not in {"", "/"} else 0.0)
                        + (0.01 if controller_name else 0.0),
                        0.99,
                    )
                    candidates.append(
                        RouteCandidate(
                            method=route_spec["method"],
                            path=full_path,
                            local_path=local_path,
                            file=file_path,
                            component=component,
                            handler_function=node.name,
                            controller_name=controller_name,
                            router_prefix=combined_prefix,
                            middleware=_stable_unique(_clean_hint_list(middleware)),
                            auth_hints=auth_hints,
                            validation_hints=validation_hints,
                            detection_source="python_ast",
                            detection_rule=route_spec["rule"],
                            confidence=confidence,
                            line_start=line_start,
                            line_end=line_end,
                        )
                    )

    candidates.extend(_extract_django_route_candidates(tree, file_path, component))
    return candidates


def _collect_python_router_defs(tree: ast.AST) -> dict[str, dict]:
    router_defs: dict[str, dict] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        target = node.targets[0] if node.targets else None
        if not isinstance(target, ast.Name):
            continue
        call = node.value
        call_name = _call_name(call.func)
        if call_name not in {"APIRouter", "Blueprint"}:
            continue
        prefix_kw = "prefix" if call_name == "APIRouter" else "url_prefix"
        dependencies_kw = "dependencies"
        prefix = _literal_string(_keyword_value(call, prefix_kw)) or ""
        dependencies = _extract_dependency_names(_keyword_value(call, dependencies_kw))
        auth_hints = _classify_auth_hints(dependencies)
        validation_hints = _classify_validation_hints(dependencies)
        router_defs[target.id] = {
            "kind": call_name,
            "prefix": prefix,
            "dependencies": dependencies,
            "auth_hints": auth_hints,
            "validation_hints": validation_hints,
        }

    return router_defs


def _collect_python_mount_prefixes(tree: ast.AST) -> dict[str, list[str]]:
    mounts: dict[str, list[str]] = defaultdict(list)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        attr = node.func.attr
        if attr not in {"include_router", "register_blueprint"}:
            continue
        if not node.args or not isinstance(node.args[0], ast.Name):
            continue
        mounted_var = node.args[0].id
        prefix_kw = "prefix" if attr == "include_router" else "url_prefix"
        prefix = _literal_string(_keyword_value(node, prefix_kw)) or ""
        mounts[mounted_var].append(prefix)
    return {key: value for key, value in mounts.items()}


def _extract_django_route_candidates(tree: ast.AST, file_path: str, component: str) -> list[RouteCandidate]:
    if not _has_django_url_import(tree):
        return []

    candidates: list[RouteCandidate] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id not in {"path", "re_path"}:
            continue
        if not node.args:
            continue
        local_path = _literal_string(node.args[0])
        if local_path is None:
            continue
        handler_expr = node.args[1] if len(node.args) > 1 else None
        handler_label = _short_expr_name(handler_expr)
        controller_name, handler_function = _controller_and_handler_from_label(handler_label)
        candidates.append(
            RouteCandidate(
                method="ANY",
                path=_normalize_route_path(local_path),
                local_path=_normalize_route_path(local_path),
                file=file_path,
                component=component,
                handler_function=handler_function,
                controller_name=controller_name,
                detection_source="python_ast",
                detection_rule="django_urlpattern",
                confidence=0.88,
                line_start=getattr(node, "lineno", None),
                line_end=getattr(node, "end_lineno", getattr(node, "lineno", None)),
            )
        )
    return candidates


def _parse_python_route_decorator(decorator: ast.AST, router_defs: dict[str, dict]) -> list[dict]:
    if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
        return []
    if not isinstance(decorator.func.value, ast.Name):
        return []

    base_var = decorator.func.value.id
    attr = decorator.func.attr.lower()
    local_path = _literal_string(decorator.args[0] if decorator.args else _keyword_value(decorator, "path"))
    if local_path is None:
        local_path = _literal_string(_keyword_value(decorator, "rule"))
    if local_path is None:
        return []

    dependencies = _extract_dependency_names(_keyword_value(decorator, "dependencies"))
    local_path = _normalize_route_path(local_path)

    if attr in _PY_HTTP_METHODS:
        return [{
            "base_var": base_var,
            "method": attr.upper(),
            "local_path": local_path,
            "dependencies": dependencies,
            "rule": "python_route_decorator",
            "confidence": 0.96,
        }]

    if attr == "api_route":
        methods = _literal_string_list(_keyword_value(decorator, "methods")) or ["ANY"]
        return [{
            "base_var": base_var,
            "method": method.upper(),
            "local_path": local_path,
            "dependencies": dependencies,
            "rule": "python_api_route_decorator",
            "confidence": 0.92,
        } for method in methods]

    if attr == "route":
        methods = _literal_string_list(_keyword_value(decorator, "methods"))
        default_method = "GET" if router_defs.get(base_var, {}).get("kind") == "Blueprint" else "ANY"
        if not methods:
            methods = [default_method]
        return [{
            "base_var": base_var,
            "method": method.upper(),
            "local_path": local_path,
            "dependencies": dependencies,
            "rule": "python_generic_route_decorator",
            "confidence": 0.9,
        } for method in methods]

    return []


def _build_js_contexts(root: str, files: list[dict], component_name_for) -> dict[str, JSImportContext]:
    contexts: dict[str, JSImportContext] = {}
    for file_info in files:
        content = _safe_read(os.path.join(root, file_info["path"]))
        if not content:
            continue
        context = JSImportContext(
            file=file_info["path"],
            component=component_name_for(file_info["path"]),
            content=content,
            masked=_strip_js_comments(content),
        )
        context.imports = _parse_js_imports(root, context.file, context.masked)
        context.router_vars = {match.group("var") for match in _JS_ROUTER_DEF_RE.finditer(context.masked)}
        context.app_vars = {match.group("var") for match in _JS_APP_DEF_RE.finditer(context.masked)}
        _collect_js_use_metadata(context)
        contexts[context.file] = context

    for context in contexts.values():
        for target_file, prefix in context.cross_file_mounts:
            if target_file in contexts:
                contexts[target_file].file_mount_prefixes.append(prefix)

    for context in contexts.values():
        context.file_mount_prefixes = _stable_unique([
            _normalize_route_prefix(prefix) for prefix in context.file_mount_prefixes
        ]) or [""]
        for router_var in list(context.local_mount_prefixes.keys()):
            context.local_mount_prefixes[router_var] = _stable_unique([
                _normalize_route_prefix(prefix) for prefix in context.local_mount_prefixes[router_var]
            ]) or [""]
    return contexts


def _collect_js_use_metadata(context: JSImportContext) -> None:
    for match in _JS_CALL_TOKEN_RE.finditer(context.masked):
        obj = match.group("object")
        method = match.group("method").lower()
        if method != "use":
            continue
        open_paren_index = context.masked.find("(", match.end() - 1)
        if open_paren_index == -1:
            continue
        args_text, _, _ = _capture_balanced_call(context.masked, open_paren_index)
        if args_text is None:
            continue
        args = _split_top_level_args(args_text)
        if not args:
            continue
        first_arg = args[0]
        first_path = _literal_string_from_source(first_arg)
        target_arg = args[1] if len(args) > 1 else None

        if first_path is None:
            target_alias = _alias_from_expression(first_arg)
            if target_alias and target_alias in context.imports:
                context.cross_file_mounts.append((context.imports[target_alias], ""))
                continue
            if target_alias and target_alias in context.router_vars:
                context.local_mount_prefixes[target_alias].append("")
                continue
            if obj in context.router_vars or obj in context.app_vars:
                label = _short_js_symbol(first_arg)
                if label:
                    context.router_middleware[obj].append(label)
            continue

        if target_arg is None:
            continue
        target_alias = _alias_from_expression(target_arg)
        if target_alias and target_alias in context.imports:
            context.cross_file_mounts.append((context.imports[target_alias], first_path))
        elif target_alias and target_alias in context.router_vars:
            context.local_mount_prefixes[target_alias].append(first_path)


def _extract_js_route_candidates(context: JSImportContext) -> list[RouteCandidate]:
    candidates: list[RouteCandidate] = []

    for match in _JS_CALL_TOKEN_RE.finditer(context.masked):
        obj = match.group("object")
        method = match.group("method").lower()
        open_paren_index = context.masked.find("(", match.end() - 1)
        if open_paren_index == -1:
            continue
        args_text, end_index, close_index = _capture_balanced_call(context.masked, open_paren_index)
        if args_text is None:
            continue

        if method == "route":
            if obj not in context.router_vars and obj not in context.app_vars:
                continue
            chain_local_path = _literal_string_from_source(_split_top_level_args(args_text)[0]) if _split_top_level_args(args_text) else None
            if not chain_local_path:
                continue
            candidates.extend(_extract_js_route_chain_candidates(context, obj, chain_local_path, close_index + 1, match.start()))
            continue

        if method not in _JS_ROUTE_METHODS:
            continue
        if obj not in context.router_vars and obj not in context.app_vars:
            continue
        route = _build_js_route_candidate(
            context=context,
            router_var=obj,
            method=method.upper(),
            args_text=args_text,
            match_start=match.start(),
            match_end=end_index,
            rule="js_router_method_call",
        )
        if route is not None:
            candidates.extend(route)

    candidates.extend(_extract_next_api_route_candidates(context))
    return candidates


def _extract_js_route_chain_candidates(
    context: JSImportContext,
    router_var: str,
    local_path: str,
    start_index: int,
    route_call_start: int,
) -> list[RouteCandidate]:
    candidates: list[RouteCandidate] = []
    cursor = start_index
    while cursor < len(context.masked):
        while cursor < len(context.masked) and context.masked[cursor].isspace():
            cursor += 1
        if cursor >= len(context.masked) or context.masked[cursor] != ".":
            break
        cursor += 1
        method_match = re.match(r"\s*([A-Za-z_$][\w$]*)", context.masked[cursor:])
        if not method_match:
            break
        method = method_match.group(1).lower()
        cursor += method_match.end()
        while cursor < len(context.masked) and context.masked[cursor].isspace():
            cursor += 1
        if cursor >= len(context.masked) or context.masked[cursor] != "(":
            break
        args_text, end_index, close_index = _capture_balanced_call(context.masked, cursor)
        if args_text is None:
            break
        if method in _JS_ROUTE_METHODS:
            built = _build_js_route_candidate(
                context=context,
                router_var=router_var,
                method=method.upper(),
                args_text=args_text,
                match_start=route_call_start,
                match_end=end_index,
                rule="js_router_route_chain",
                forced_local_path=local_path,
            )
            if built is not None:
                candidates.extend(built)
        cursor = close_index + 1
    return candidates


def _build_js_route_candidate(
    context: JSImportContext,
    router_var: str,
    method: str,
    args_text: str,
    match_start: int,
    match_end: int,
    rule: str,
    forced_local_path: Optional[str] = None,
) -> Optional[list[RouteCandidate]]:
    args = _split_top_level_args(args_text)
    if not args:
        return None

    local_path = forced_local_path or _literal_string_from_source(args[0])
    if not local_path:
        return None
    local_path = _normalize_route_path(local_path)
    remaining_args = args if forced_local_path is not None else args[1:]

    handler_label = _short_js_symbol(remaining_args[-1]) if remaining_args else None
    controller_name, handler_function = _controller_and_handler_from_label(handler_label)
    middleware_labels = [_short_js_symbol(arg) for arg in remaining_args[:-1]] if len(remaining_args) > 1 else []
    middleware_labels = _clean_hint_list(context.router_middleware.get(router_var, []) + middleware_labels)
    auth_hints = _classify_auth_hints(middleware_labels)
    validation_hints = _classify_validation_hints(middleware_labels)
    line_start, line_end = _line_span_from_indices(context.content, match_start, match_end)

    file_mount_prefixes = context.file_mount_prefixes if router_var not in context.app_vars else [""]
    local_mount_prefixes = context.local_mount_prefixes.get(router_var, [""])

    candidates: list[RouteCandidate] = []
    for file_mount_prefix in file_mount_prefixes:
        for local_mount_prefix in local_mount_prefixes:
            router_prefix = _join_route_path(file_mount_prefix, local_mount_prefix)
            full_path = _join_route_path(router_prefix, local_path)
            confidence = 0.9
            if router_prefix not in {"", "/"}:
                confidence += 0.03
            if handler_function:
                confidence += 0.03
            if line_start is not None:
                confidence += 0.01
            candidates.append(
                RouteCandidate(
                    method=method,
                    path=full_path,
                    local_path=local_path,
                    file=context.file,
                    component=context.component,
                    handler_function=handler_function,
                    controller_name=controller_name,
                    router_prefix=router_prefix,
                    middleware=_stable_unique(middleware_labels),
                    auth_hints=auth_hints,
                    validation_hints=validation_hints,
                    detection_source="js_static_scan",
                    detection_rule=rule,
                    confidence=min(confidence, 0.98),
                    line_start=line_start,
                    line_end=line_end,
                )
            )
    return candidates


def _extract_next_api_route_candidates(context: JSImportContext) -> list[RouteCandidate]:
    normalized_path = context.file.replace("\\", "/")
    if not (normalized_path.startswith("pages/api/") or "/pages/api/" in normalized_path):
        return []
    match = _JS_EXPORT_DEFAULT_FUNCTION_RE.search(context.masked)
    if not match:
        return []
    route_path = "/" + normalized_path.split("/pages/")[-1]
    route_path = route_path.replace("index.ts", "").replace("index.js", "")
    route_path = route_path.replace(".ts", "").replace(".tsx", "").replace(".js", "").replace(".jsx", "")
    route_path = route_path.replace("/api/", "/api/")
    route_path = route_path.replace("//", "/")
    route_path = _normalize_route_path(route_path)
    line_start, line_end = _line_span_from_indices(context.content, match.start(), match.end())
    return [
        RouteCandidate(
            method="ANY",
            path=route_path,
            local_path=route_path,
            file=context.file,
            component=context.component,
            handler_function=match.group("name") or "default",
            detection_source="js_static_scan",
            detection_rule="next_pages_api_default_export",
            confidence=0.8,
            line_start=line_start,
            line_end=line_end,
        )
    ]


def _merge_route_candidates(candidates: list[RouteCandidate]) -> list[RouteCandidate]:
    merged: dict[tuple, RouteCandidate] = {}
    for candidate in candidates:
        key = candidate.dedupe_key()
        existing = merged.get(key)
        if existing is None:
            merged[key] = candidate
            continue
        merged[key] = _merge_two_candidates(existing, candidate)

    second_pass: dict[tuple, RouteCandidate] = {}
    for candidate in merged.values():
        key = (candidate.method, candidate.file, candidate.path)
        existing = second_pass.get(key)
        if existing is None:
            second_pass[key] = candidate
        else:
            second_pass[key] = _merge_two_candidates(existing, candidate)

    return sorted(
        second_pass.values(),
        key=lambda item: (item.file, item.line_start or 0, item.method, item.path),
    )


def _merge_two_candidates(left: RouteCandidate, right: RouteCandidate) -> RouteCandidate:
    primary, secondary = (left, right) if left.strength_key() >= right.strength_key() else (right, left)
    return RouteCandidate(
        method=primary.method,
        path=primary.path if len(primary.path) >= len(secondary.path) else secondary.path,
        local_path=primary.local_path or secondary.local_path,
        file=primary.file,
        component=primary.component or secondary.component,
        handler_function=primary.handler_function or secondary.handler_function,
        controller_name=primary.controller_name or secondary.controller_name,
        router_prefix=primary.router_prefix if len(primary.router_prefix) >= len(secondary.router_prefix) else secondary.router_prefix,
        middleware=_stable_unique(primary.middleware + secondary.middleware),
        auth_hints=_stable_unique(primary.auth_hints + secondary.auth_hints),
        validation_hints=_stable_unique(primary.validation_hints + secondary.validation_hints),
        detection_source=primary.detection_source,
        detection_rule=primary.detection_rule,
        confidence=max(primary.confidence, secondary.confidence),
        line_start=primary.line_start or secondary.line_start,
        line_end=primary.line_end or secondary.line_end,
    )


def _component_name_resolver(components: list[dict]):
    def resolve(path: str) -> str:
        for component in components:
            root_path = component.get("root_path", ".")
            prefix = f"{root_path}/" if root_path != "." else ""
            if prefix and path.startswith(prefix):
                return component.get("name", "")
            if not prefix and root_path == ".":
                return component.get("name", "")
        return ""

    return resolve


def _route_best_target(candidate: RouteCandidate) -> dict:
    anchor_kind = "file"
    target_rank = 60
    selection_reason = "route target falls back to the defining source file"
    if candidate.handler_function and candidate.line_start is not None:
        anchor_kind = "handler_definition"
        target_rank = 100
        selection_reason = "route target includes an explicit handler symbol and line range"
    elif candidate.line_start is not None:
        anchor_kind = "route_line"
        target_rank = 92
        selection_reason = "route target includes an explicit line range"
    elif candidate.handler_function:
        anchor_kind = "handler_symbol"
        target_rank = 86
        selection_reason = "route target includes an explicit handler symbol"
    return {
        "file_path": candidate.file,
        "symbol_name": candidate.handler_function,
        "symbol_kind": "handler" if candidate.handler_function else None,
        "class_name": candidate.controller_name,
        "line_start": candidate.line_start,
        "line_end": candidate.line_end,
        "anchor_kind": anchor_kind,
        "target_rank": target_rank,
        "selection_reason": selection_reason,
        "confidence": round(candidate.confidence, 2),
    }


def _safe_read(filepath: str, max_size: int = 1024 * 1024) -> Optional[str]:
    try:
        if os.path.getsize(filepath) > max_size:
            return None
        with open(filepath, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def _is_test_file(path: str) -> bool:
    if path.endswith(_TEST_FILE_SUFFIXES):
        return True
    parts = path.replace("\\", "/").split("/")
    return bool(set(parts) & _TEST_PATH_SEGMENTS)


def _call_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _keyword_value(call: ast.Call, keyword_name: str) -> Optional[ast.AST]:
    for keyword in call.keywords:
        if keyword.arg == keyword_name:
            return keyword.value
    return None


def _literal_string(node: Optional[ast.AST]) -> Optional[str]:
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _literal_string_list(node: Optional[ast.AST]) -> list[str]:
    if node is None:
        return []
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values: list[str] = []
        for element in node.elts:
            value = _literal_string(element)
            if value:
                values.append(value)
        return values
    return []


def _extract_dependency_names(node: Optional[ast.AST]) -> list[str]:
    if node is None:
        return []
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        names: list[str] = []
        for element in node.elts:
            names.extend(_extract_dependency_names(element))
        return names
    if isinstance(node, ast.Call):
        func_name = _call_name(node.func)
        if func_name == "Depends" and node.args:
            inner_name = _short_expr_name(node.args[0])
            return [inner_name] if inner_name else []
        call_name = _short_expr_name(node)
        return [call_name] if call_name else []
    label = _short_expr_name(node)
    return [label] if label else []


def _python_parent_class_name(node: ast.AST, parent_map: dict[ast.AST, ast.AST]) -> Optional[str]:
    current = parent_map.get(node)
    while current is not None:
        if isinstance(current, ast.ClassDef):
            return current.name
        current = parent_map.get(current)
    return None


def _short_expr_name(node: Optional[ast.AST]) -> Optional[str]:
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _short_expr_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return _short_expr_name(node.func)
    if isinstance(node, ast.Subscript):
        return _short_expr_name(node.value)
    return None


def _looks_like_python_route_decorator(name: str) -> bool:
    tail = name.split(".")[-1].lower()
    return tail in _PY_HTTP_METHODS | {"route", "api_route"}


def _has_django_url_import(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module != "django.urls":
            continue
        for alias in node.names:
            if alias.name in {"path", "re_path"}:
                return True
    return False


def _parse_js_imports(root: str, file_path: str, content: str) -> dict[str, str]:
    imports: dict[str, str] = {}
    for regex in (_JS_REQUIRE_RE, _JS_IMPORT_RE):
        for match in regex.finditer(content):
            alias = match.group("alias")
            resolved = _resolve_relative_module(root, file_path, match.group("path"))
            if resolved is not None:
                imports[alias] = resolved
    return imports


def _resolve_relative_module(root: str, file_path: str, import_path: str) -> Optional[str]:
    if not import_path.startswith("."):
        return None
    base = Path(file_path).parent / import_path
    candidates = [base]
    for suffix in (".js", ".ts", ".jsx", ".tsx", ".mjs"):
        candidates.append(Path(f"{base}{suffix}"))
    for suffix in ("index.js", "index.ts", "index.jsx", "index.tsx", "index.mjs"):
        candidates.append(base / suffix)
    for candidate in candidates:
        full_path = Path(root) / candidate
        if full_path.is_file():
            return candidate.as_posix()
    return None


def _strip_js_comments(content: str) -> str:
    result: list[str] = []
    index = 0
    in_string: Optional[str] = None
    in_line_comment = False
    in_block_comment = False
    escape = False

    while index < len(content):
        char = content[index]
        next_char = content[index + 1] if index + 1 < len(content) else ""

        if in_line_comment:
            if char == "\n":
                in_line_comment = False
                result.append(char)
            else:
                result.append(" ")
            index += 1
            continue

        if in_block_comment:
            if char == "*" and next_char == "/":
                result.extend("  ")
                in_block_comment = False
                index += 2
            else:
                result.append("\n" if char == "\n" else " ")
                index += 1
            continue

        if in_string:
            result.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == in_string:
                in_string = None
            index += 1
            continue

        if char in {"'", '"', "`"}:
            in_string = char
            result.append(char)
            index += 1
            continue

        if char == "/" and next_char == "/":
            result.extend("  ")
            in_line_comment = True
            index += 2
            continue

        if char == "/" and next_char == "*":
            result.extend("  ")
            in_block_comment = True
            index += 2
            continue

        result.append(char)
        index += 1

    return "".join(result)


def _capture_balanced_call(content: str, open_paren_index: int) -> tuple[Optional[str], int, int]:
    depth = 0
    in_string: Optional[str] = None
    escape = False

    for index in range(open_paren_index, len(content)):
        char = content[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == in_string:
                in_string = None
            continue

        if char in {"'", '"', "`"}:
            in_string = char
            continue

        if char == "(":
            depth += 1
            continue
        if char == ")":
            depth -= 1
            if depth == 0:
                return content[open_paren_index + 1:index], index + 1, index

    return None, len(content), len(content)


def _split_top_level_args(source: str) -> list[str]:
    args: list[str] = []
    current: list[str] = []
    depth_paren = 0
    depth_bracket = 0
    depth_brace = 0
    in_string: Optional[str] = None
    escape = False

    for char in source:
        if in_string:
            current.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == in_string:
                in_string = None
            continue

        if char in {"'", '"', "`"}:
            in_string = char
            current.append(char)
            continue

        if char == "(":
            depth_paren += 1
        elif char == ")":
            depth_paren = max(0, depth_paren - 1)
        elif char == "[":
            depth_bracket += 1
        elif char == "]":
            depth_bracket = max(0, depth_bracket - 1)
        elif char == "{":
            depth_brace += 1
        elif char == "}":
            depth_brace = max(0, depth_brace - 1)

        if char == "," and depth_paren == 0 and depth_bracket == 0 and depth_brace == 0:
            fragment = "".join(current).strip()
            if fragment:
                args.append(fragment)
            current = []
            continue

        current.append(char)

    fragment = "".join(current).strip()
    if fragment:
        args.append(fragment)
    return args


def _literal_string_from_source(source: str) -> Optional[str]:
    stripped = source.strip()
    if len(stripped) < 2 or stripped[0] != stripped[-1] or stripped[0] not in {"'", '"', "`"}:
        return None
    if stripped[0] == "`" and "${" in stripped:
        return None
    return stripped[1:-1]


def _alias_from_expression(source: str) -> Optional[str]:
    stripped = source.strip()
    if re.fullmatch(r"[A-Za-z_$][\w$]*", stripped):
        return stripped
    return None


def _short_js_symbol(source: Optional[str]) -> Optional[str]:
    if source is None:
        return None
    stripped = source.strip()
    if re.search(r"\bfunction\b|=>", stripped):
        return None
    stripped = stripped.rstrip(";")
    stripped = re.sub(r"\([^()]*\)$", "", stripped)
    stripped = re.sub(r"\s+as\s+any$", "", stripped)
    if not stripped:
        return None
    if re.fullmatch(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*", stripped):
        return stripped
    return None


def _controller_and_handler_from_label(label: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not label:
        return None, None
    parts = label.split(".")
    if len(parts) >= 2:
        return parts[-2], parts[-1]
    return None, parts[-1]


def _classify_auth_hints(names: list[str]) -> list[str]:
    return _stable_unique([
        name for name in _clean_hint_list(names) if _AUTH_HINT_RE.search(_normalize_hint_label(name))
    ])


def _classify_validation_hints(names: list[str]) -> list[str]:
    return _stable_unique([
        name for name in _clean_hint_list(names) if _VALIDATION_HINT_RE.search(_normalize_hint_label(name))
    ])


def _normalize_hint_label(name: str) -> str:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    normalized = normalized.replace("(", "_").replace(")", "_")
    return normalized.lower()


def _clean_hint_list(names: list[Optional[str]]) -> list[str]:
    cleaned: list[str] = []
    for name in names:
        if not name:
            continue
        normalized = name.strip()
        if not normalized:
            continue
        cleaned.append(normalized)
    return cleaned


def _stable_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _normalize_route_prefix(prefix: Optional[str]) -> str:
    if not prefix:
        return ""
    normalized = prefix.replace("\\", "/").strip()
    if not normalized:
        return ""
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    normalized = normalized.rstrip("/")
    return normalized or ""


def _normalize_route_path(path: str) -> str:
    normalized = (path or "/").replace("\\", "/").strip()
    if not normalized:
        return "/"
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    normalized = re.sub(r"//+", "/", normalized)
    return normalized if normalized == "/" else normalized.rstrip("/")


def _join_route_path(*parts: Optional[str]) -> str:
    segments: list[str] = []
    for part in parts:
        if not part:
            continue
        cleaned = part.replace("\\", "/").strip()
        if not cleaned:
            continue
        segments.append(cleaned.strip("/"))
    if not segments:
        return "/"
    return _normalize_route_path("/" + "/".join(segment for segment in segments if segment))


def _line_span_from_indices(content: str, start_index: int, end_index: int) -> tuple[int, int]:
    line_start = content.count("\n", 0, start_index) + 1
    line_end = content.count("\n", 0, end_index) + 1
    return line_start, line_end
