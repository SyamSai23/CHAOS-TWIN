"""
Route analysis engine using Python's stdlib ast module.

Reads actual handler functions from source files and extracts
structured information about what each route does — zero AI,
zero pip dependencies.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from openai import AsyncOpenAI

from app.config import OPENAI_API_KEY
from app.services.identity import make_route_id

logger = logging.getLogger(__name__)

# ── Known patterns for call classification ──────────────────────────

_DB_READ_METHODS = {"query", "execute", "get", "scalar", "scalars", "first", "all", "one", "one_or_none"}
_DB_WRITE_METHODS = {"add", "add_all", "delete", "merge", "bulk_save_objects", "bulk_insert_mappings"}
_DB_COMMIT_METHODS = {"commit", "flush", "refresh", "rollback"}
_FS_CALLERS = {"os", "shutil", "zipfile", "open", "pathlib"}
_FS_METHODS = {"remove", "rmtree", "makedirs", "extractall", "write", "read",
               "unlink", "mkdir", "rename", "exists", "listdir", "walk",
               "join", "open", "copy", "copytree"}
_EXTERNAL_CALLERS = {"openai", "anthropic", "boto3", "stripe",
                     "requests", "httpx", "aiohttp", "urllib"}
_SKIP_PARAMS = {"db", "session", "request", "response", "background_tasks"}

# Decorator patterns: @router.get, @app.post, etc.
_ROUTE_DECORATORS = {"get", "post", "put", "delete", "patch", "head", "options"}


def _ast_to_str(node: ast.AST, max_len: int = 80) -> str:
    """Best-effort conversion of an AST node to source string."""
    try:
        return ast.unparse(node)[:max_len]
    except Exception:
        return ""


def _extract_decorator_route(dec: ast.AST) -> tuple[str, str] | None:
    """Extract (method, path) from a route decorator like @router.get("/path")."""
    if not isinstance(dec, ast.Call):
        return None
    func = dec.func
    if not isinstance(func, ast.Attribute):
        return None
    method = func.attr.lower()
    if method not in _ROUTE_DECORATORS:
        return None
    if not dec.args:
        return None
    first_arg = dec.args[0]
    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
        return (method.upper(), first_arg.value)
    return None


def _normalize_path(path: str) -> str:
    """Normalize a route path for comparison.
    /items/{item_id} and /items/{id} should match structurally.
    """
    return re.sub(r"\{[^}]+\}", "{}", path.rstrip("/")) or "/"


async def infer_request_response(route_analysis: dict, file_summary: str) -> dict:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is required for request/response inference")

    phases_summary = "\n".join(
        f"- {phase.get('name') or phase.get('title') or 'Phase'}: {phase.get('description') or ''}".strip()
        for phase in route_analysis.get("phases", [])
        if isinstance(phase, dict)
    ) or "- No execution phases available"

    prompt = f"""You are helping a junior developer understand an API endpoint.

Endpoint: {route_analysis.get('method', 'GET')} {route_analysis.get('path', '/')}
Handler: {route_analysis.get('handler_function') or 'unknown'}
Parameters already known: {json.dumps(route_analysis.get('parameters', []))}
File summary: {file_summary}
Execution phases: {phases_summary}

Infer the most likely request body and response body for this endpoint.
Think from a junior developer perspective — be clear and practical.

Return ONLY a JSON object, no markdown:
{{
  "request": {{
    "description": "One sentence: what this request does",
    "body": [
      {{"field": "fieldName", "type": "string", "required": true, "description": "what this field is"}}
    ],
    "notes": "Any important notes about the request (optional, null if none)"
  }},
  "response": {{
    "description": "One sentence: what comes back",
    "body": [
      {{"field": "fieldName", "type": "string", "description": "what this field contains"}}
    ],
    "notes": "Any important notes about the response (optional, null if none)"
  }}
}}
If the endpoint has no request body (e.g. GET requests), return an empty body array for request with a note explaining it.
"""

    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "Infer practical request and response shapes for API endpoints. Return only valid JSON objects.",
            },
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    content = response.choices[0].message.content or "{}"
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("Invalid request/response inference payload")
    return parsed


class RouteAnalyzer:
    """Analyzes route handlers using AST introspection."""

    def __init__(self, workspace_path: str):
        self._ws = Path(workspace_path)
        # Cache parsed ASTs per file
        self._ast_cache: dict[str, ast.Module | None] = {}
        # Track imports from services/ folder per file
        self._service_imports: dict[str, set[str]] = {}
        # Lazy tree-sitter analyzer for non-Python files
        self._ts: Any = None

    def _analyze_with_tree_sitter(self, route: dict) -> dict | None:
        """Delegate to TreeSitterAnalyzer for non-Python files."""
        if self._ts is None:
            try:
                from .ts_analyzer import TreeSitterAnalyzer
                if not TreeSitterAnalyzer.available():
                    return None
                self._ts = TreeSitterAnalyzer(str(self._ws))
            except ImportError:
                logger.info("tree-sitter analyzer not available")
                return None
        try:
            return self._ts.analyze(route)
        except Exception:
            logger.exception("tree-sitter analysis failed for %s", route.get("file"))
            return None

    def _analyze_with_gpt(self, route: dict) -> dict | None:
        """
        GPT-powered route analysis fallback.
        Used when AST/tree-sitter analysis fails to find the handler.
        Works for any language or framework.
        """
        import asyncio
        import json
        import re as re_module
        import requests as req_lib

        method = route.get("method", "GET").upper()
        path = route.get("path", "/")
        file_rel = route.get("file", "")
        print(f"[ast_analyzer] GPT fallback triggered for {method} {path} in {file_rel}")
        component = route.get("component", "unknown")
        handler_name = route.get("handler", "")
        rid = make_route_id(method, path, file_rel)

        # Read file content
        file_path = self._ws / file_rel
        if not file_path.exists():
            return None

        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            return None

        try:
            prompt_text = f"""You are analyzing source code to explain an API endpoint to a junior developer.

Endpoint: {method} {path}
Handler: {handler_name}
File: {file_rel}

File content:
{content[:15000]}

Trace exactly what happens when this endpoint is called, step by step.
Be specific — name the actual functions called, database operations, external service calls.
Write for a junior developer who needs to understand this code for the first time.

Return ONLY a JSON object, no markdown:
{{
  "handler_function": "exact function or method name that handles this route",
  "complexity": "simple|moderate|complex",
  "has_database": true,
  "has_external": false,
  "has_filesystem": false,
  "participants": [
    {{"id": "client", "label": "Client", "type": "client"}},
    {{"id": "handler", "label": "HandlerName()", "type": "component"}},
    {{"id": "database", "label": "Database", "type": "database"}}
  ],
  "phases": [
    {{
      "phase_id": "validation",
      "name": "Validation",
      "color": "orange",
      "description": "Plain English: what validation happens",
      "steps": [
        {{
          "step_id": "s1",
          "type": "conditional",
          "label": "Check authentication token",
          "technical": "auth.verify_token()",
          "line_number": 0,
          "is_error_path": false
        }}
      ]
    }}
  ],
  "error_paths": [],
  "parameters": []
}}

Step types must be one of: db_read, db_write, service_call, external, conditional, response, filesystem
Participant types must be one of: client, component, database, external
Include 2-4 phases that tell the complete story of what this endpoint does.
"""
            print(f"[ast_analyzer] calling OpenAI for {method} {path}")
            headers = {
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "gpt-4o",
                "max_tokens": 2000,
                "messages": [{"role": "user", "content": prompt_text}]
            }
            http_response = req_lib.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=60
            )
            http_response.raise_for_status()
            print(f"[ast_analyzer] OpenAI responded for {method} {path}")

            raw = http_response.json()["choices"][0]["message"]["content"].strip()
            raw = re_module.sub(r'```json|```', '', raw).strip()
            result = json.loads(raw)

            if not isinstance(result, dict):
                return None

            # Ensure required fields
            result['route_id'] = rid
            result['method'] = method
            result['path'] = path
            result['file'] = file_rel
            result['component'] = component

            logger.info("GPT fallback analysis succeeded for %s %s", method, path)
            return result

        except json.JSONDecodeError as e:
            print(f"[ast_analyzer] JSON decode error for {method} {path}: {e}")
            return None
        except Exception as e:
            import traceback
            print(f"[ast_analyzer] GPT fallback exception for {method} {path}: {e}")
            print(traceback.format_exc())
            return None

    # ── Public API ──────────────────────────────────────────────────

    def analyze_route(self, route: dict) -> dict | None:
        """Analyze a single route and return a RouteAnalysis dict.

        Returns None if the file cannot be parsed or handler not found.
        """
        method = route.get("method", "GET").upper()
        path = route.get("path", "/")
        file_rel = route.get("file", "")
        component = route.get("component", "unknown")
        rid = make_route_id(method, path, file_rel)

        # Dispatch non-Python files to tree-sitter analyzer
        ext = Path(file_rel).suffix.lower()
        if ext != ".py":
            return self._analyze_with_tree_sitter(route)

        # Step 1: parse file
        tree = self._parse_file(file_rel)
        if tree is None:
            logger.warning("Cannot parse %s for route %s %s", file_rel, method, path)
            return None

        # Collect service imports for this file
        self._collect_service_imports(file_rel, tree)

        # Step 1: find handler
        handler = self._find_handler(tree, method, path)
        if handler is None:
            logger.warning("No handler found for %s %s in %s", method, path, file_rel)
            # Try GPT fallback before giving up
            gpt_result = self._analyze_with_gpt(route)
            if gpt_result is not None:
                return gpt_result
            return self._empty_analysis(rid, method, path, file_rel, component)

        # Step 2: extract signature
        params = self._extract_params(handler)
        return_type = self._extract_return_type(handler)

        # Step 3: walk body
        calls = self._extract_calls(handler, file_rel)
        conditionals = self._extract_conditionals(handler)
        try_blocks = self._extract_try_blocks(handler)
        loops = self._extract_loops(handler)
        returns = self._extract_returns(handler)

        # Step 4: classify into phases
        body_len = len(handler.body)
        all_steps, phases = self._classify_phases(
            calls, conditionals, try_blocks, loops, returns, body_len, handler
        )

        # Step 5: error paths
        error_paths = self._collect_error_paths(conditionals, try_blocks)

        # Step 6: plain English descriptions
        for phase in phases:
            phase["description"] = self._describe_phase(phase)

        # Build participants
        participants = self._build_participants(component, phases)

        # Complexity
        total_steps = sum(len(p["steps"]) for p in phases)
        phase_count = len(phases)
        if phase_count <= 1 and total_steps < 5:
            complexity = "simple"
        elif phase_count >= 4 or total_steps > 15:
            complexity = "complex"
        else:
            complexity = "moderate"

        has_db = any(s["type"].startswith("db_") for p in phases for s in p["steps"])
        has_fs = any(s["type"] == "filesystem" for p in phases for s in p["steps"])
        has_ext = any(s["type"] == "external" for p in phases for s in p["steps"])

        return {
            "route_id": rid,
            "method": method,
            "path": path,
            "file": file_rel,
            "component": component,
            "handler_function": handler.name,
            "parameters": params,
            "return_type": return_type,
            "phases": phases,
            "error_paths": error_paths,
            "participants": participants,
            "has_database": has_db,
            "has_filesystem": has_fs,
            "has_external": has_ext,
            "complexity": complexity,
        }

    # ── Step 1: Parsing & Handler Finding ───────────────────────────

    def _parse_file(self, file_rel: str) -> ast.Module | None:
        if file_rel in self._ast_cache:
            return self._ast_cache[file_rel]

        full_path = self._ws / file_rel
        if not full_path.is_file():
            self._ast_cache[file_rel] = None
            return None

        try:
            source = full_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=file_rel)
            self._ast_cache[file_rel] = tree
            return tree
        except SyntaxError:
            logger.warning("SyntaxError parsing %s", file_rel)
            self._ast_cache[file_rel] = None
            return None

    def _find_handler(
        self, tree: ast.Module, method: str, path: str
    ) -> ast.FunctionDef | None:
        norm_target = _normalize_path(path)

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                result = _extract_decorator_route(dec)
                if result is None:
                    continue
                dec_method, dec_path = result
                if dec_method == method and _normalize_path(dec_path) == norm_target:
                    return node
        return None

    def _collect_service_imports(self, file_rel: str, tree: ast.Module) -> None:
        """Track which names are imported from services/ modules."""
        if file_rel in self._service_imports:
            return
        names: set[str] = set()
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if "services" in node.module or "service" in node.module:
                    for alias in node.names:
                        names.add(alias.asname or alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "services" in alias.name or "service" in alias.name:
                        names.add(alias.asname or alias.name)
        self._service_imports[file_rel] = names

    # ── Step 2: Signature Extraction ────────────────────────────────

    def _extract_params(self, func: ast.FunctionDef) -> list[dict]:
        params = []
        for arg in func.args.args:
            name = arg.arg
            if name == "self" or name.lower() in _SKIP_PARAMS:
                continue
            ann = _ast_to_str(arg.annotation) if arg.annotation else None
            params.append({"name": name, "type": ann})
        return params

    def _extract_return_type(self, func: ast.FunctionDef) -> str | None:
        if func.returns:
            return _ast_to_str(func.returns)
        return None

    # ── Step 3: Body Walking ────────────────────────────────────────

    def _classify_call(self, caller: str, method_name: str, file_rel: str) -> str:
        caller_low = caller.lower()
        method_low = method_name.lower()

        if caller_low in ("db", "session") and method_low in _DB_READ_METHODS:
            return "db_read"
        if caller_low in ("db", "session") and method_low in _DB_WRITE_METHODS:
            return "db_write"
        if method_low in _DB_COMMIT_METHODS:
            return "db_commit"
        if caller_low in _FS_CALLERS or method_low in _FS_METHODS:
            return "filesystem"
        if caller_low in _EXTERNAL_CALLERS:
            return "external"
        # Check if it's a call to a service function
        svc_names = self._service_imports.get(file_rel, set())
        if caller_low in {s.lower() for s in svc_names} or method_name in svc_names:
            return "service"
        # Plain function call to a known service import
        if not caller and method_name in svc_names:
            return "service"
        return "internal"

    def _extract_calls(self, func: ast.FunctionDef, file_rel: str) -> list[dict]:
        calls = []
        for node in ast.walk(func):
            if not isinstance(node, ast.Call):
                continue
            caller, method_name, full_call = self._dissect_call(node)
            if not method_name and not caller:
                continue
            call_type = self._classify_call(caller, method_name, file_rel)
            # First arg summary
            args_summary = None
            if node.args:
                args_summary = _ast_to_str(node.args[0], 60)
            line = getattr(node, "lineno", None)
            label = self._call_label(caller, method_name, call_type)
            calls.append({
                "caller": caller,
                "method": method_name,
                "full_call": full_call,
                "args_summary": args_summary,
                "type": call_type,
                "label": label,
                "technical": full_call,
                "line_number": line,
                "is_error_path": False,
            })
        return calls

    def _dissect_call(self, node: ast.Call) -> tuple[str, str, str]:
        """Return (caller, method, full_call) from a Call node."""
        func = node.func
        if isinstance(func, ast.Attribute):
            caller = _ast_to_str(func.value, 40)
            method_name = func.attr
            full_call = f"{caller}.{method_name}()"
            return (caller, method_name, full_call)
        elif isinstance(func, ast.Name):
            return ("", func.id, f"{func.id}()")
        elif isinstance(func, ast.Call):
            # Chained call like db.query(X).filter(Y).first()
            inner_caller, inner_method, _ = self._dissect_call(func)
            if isinstance(node.func, ast.Attribute):
                outer_method = node.func.attr
                full_call = f"{inner_caller}.{inner_method}().{outer_method}()"
                return (inner_caller, outer_method, full_call)
        return ("", "", "")

    @staticmethod
    def _call_label(caller: str, method: str, call_type: str) -> str:
        if call_type == "db_read":
            return f"Query {caller}.{method}()"
        if call_type == "db_write":
            return f"Write {caller}.{method}()"
        if call_type == "db_commit":
            return f"Commit transaction"
        if call_type == "filesystem":
            return f"File operation: {method}()"
        if call_type == "external":
            return f"External call: {caller}.{method}()"
        if call_type == "service":
            name = method or caller
            return f"Call service: {name}()"
        return f"Call {method}()" if method else "function call"

    def _extract_conditionals(self, func: ast.FunctionDef) -> list[dict]:
        conds = []
        for node in ast.walk(func):
            if not isinstance(node, ast.If):
                continue
            condition = _ast_to_str(node.test, 60)
            then_summary = self._branch_summary(node.body)
            else_summary = self._branch_summary(node.orelse) if node.orelse else None
            line = getattr(node, "lineno", None)

            # Look for HTTPException raises
            http_exc = self._find_http_exception(node.body)
            is_error = http_exc is not None

            conds.append({
                "condition": condition,
                "then_summary": then_summary,
                "else_summary": else_summary,
                "http_exception": http_exc,
                "line_number": line,
                "is_error_path": is_error,
            })
        return conds

    def _branch_summary(self, body: list[ast.stmt]) -> str:
        if not body:
            return "empty"
        first = body[0]
        if isinstance(first, ast.Raise):
            return f"raise {_ast_to_str(first, 60)}"
        if isinstance(first, ast.Return):
            return f"return {_ast_to_str(first.value, 40) if first.value else 'None'}"
        return _ast_to_str(first, 50)

    def _find_http_exception(self, body: list[ast.stmt]) -> dict | None:
        """Look for raise HTTPException(status_code=X, detail=Y)."""
        for node in ast.walk(ast.Module(body=body, type_ignores=[])):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue
            exc = node.exc
            if not isinstance(exc, ast.Call):
                continue
            func_name = _ast_to_str(exc.func, 30)
            if "HTTPException" not in func_name:
                continue
            status_code = None
            detail = None
            for kw in exc.keywords:
                if kw.arg == "status_code" and isinstance(kw.value, ast.Constant):
                    status_code = kw.value.value
                elif kw.arg == "detail" and isinstance(kw.value, ast.Constant):
                    detail = str(kw.value.value)
            # Also check positional args
            if exc.args and isinstance(exc.args[0], ast.Constant):
                status_code = status_code or exc.args[0].value
            return {"status_code": status_code, "detail": detail}
        return None

    def _extract_try_blocks(self, func: ast.FunctionDef) -> list[dict]:
        blocks = []
        for node in ast.walk(func):
            if not isinstance(node, ast.Try):
                continue
            for handler in node.handlers:
                exc_type = _ast_to_str(handler.type, 40) if handler.type else "Exception"
                action = self._branch_summary(handler.body)
                blocks.append({
                    "exception_type": exc_type,
                    "error_action": action,
                    "line_number": getattr(handler, "lineno", None),
                    "is_error_path": True,
                })
        return blocks

    def _extract_loops(self, func: ast.FunctionDef) -> list[dict]:
        loops = []
        for node in ast.walk(func):
            if isinstance(node, ast.For):
                target = _ast_to_str(node.target, 30)
                iterable = _ast_to_str(node.iter, 40)
                body_sum = self._branch_summary(node.body)
                loops.append({
                    "loop_summary": f"for {target} in {iterable}",
                    "body_summary": body_sum,
                    "line_number": getattr(node, "lineno", None),
                    "type": "loop",
                })
            elif isinstance(node, ast.While):
                test = _ast_to_str(node.test, 40)
                body_sum = self._branch_summary(node.body)
                loops.append({
                    "loop_summary": f"while {test}",
                    "body_summary": body_sum,
                    "line_number": getattr(node, "lineno", None),
                    "type": "loop",
                })
        return loops

    def _extract_returns(self, func: ast.FunctionDef) -> list[dict]:
        returns = []
        # Only top-level returns (direct children of the function body)
        for node in func.body:
            if isinstance(node, ast.Return):
                value = _ast_to_str(node.value, 60) if node.value else "None"
                returns.append({
                    "return_type": value,
                    "line_number": getattr(node, "lineno", None),
                })
        # Also check last statement if it's a return nested in try/if
        last = func.body[-1] if func.body else None
        if isinstance(last, (ast.If, ast.Try)):
            for node in ast.walk(last):
                if isinstance(node, ast.Return):
                    value = _ast_to_str(node.value, 60) if node.value else "None"
                    returns.append({
                        "return_type": value,
                        "line_number": getattr(node, "lineno", None),
                    })
                    break
        return returns

    # ── Step 4: Phase Classification ────────────────────────────────

    def _classify_phases(
        self,
        calls: list[dict],
        conditionals: list[dict],
        try_blocks: list[dict],
        loops: list[dict],
        returns: list[dict],
        body_len: int,
        func: ast.FunctionDef,
    ) -> tuple[list[dict], list[dict]]:
        """Assign every extracted step into one of 4 phases."""
        validation_steps: list[dict] = []
        processing_steps: list[dict] = []
        database_steps: list[dict] = []
        response_steps: list[dict] = []

        func_start = func.lineno
        func_end = func.end_lineno or (func_start + body_len)
        early_cutoff = func_start + (func_end - func_start) * 0.3

        step_counter = 0

        def make_step(
            stype: str, label: str, technical: str,
            line: int | None, is_error: bool = False
        ) -> dict:
            nonlocal step_counter
            step_counter += 1
            return {
                "step_id": f"s{step_counter}",
                "type": stype,
                "label": label,
                "technical": technical,
                "line_number": line,
                "is_error_path": is_error,
            }

        # Classify calls
        for c in calls:
            line = c.get("line_number") or 0
            ct = c["type"]
            step = make_step(ct, c["label"], c["technical"], c["line_number"], c["is_error_path"])

            if ct == "db_read" and line <= early_cutoff:
                validation_steps.append(step)
            elif ct in ("db_write", "db_commit"):
                database_steps.append(step)
            elif ct == "db_read":
                database_steps.append(step)
            elif ct in ("service", "filesystem", "external", "internal"):
                processing_steps.append(step)
            else:
                processing_steps.append(step)

        # Classify conditionals
        for cond in conditionals:
            if cond["is_error_path"]:
                exc = cond["http_exception"] or {}
                status = exc.get("status_code", "")
                detail = exc.get("detail", cond["condition"])
                label = f"Check: {cond['condition']}"
                tech = f"if {cond['condition']}: raise HTTPException({status})"
                step = make_step("conditional", label, tech, cond["line_number"], True)
                validation_steps.append(step)
            else:
                label = f"Branch: {cond['condition']}"
                tech = f"if {cond['condition']}"
                step = make_step("conditional", label, tech, cond["line_number"])
                processing_steps.append(step)

        # Classify try/except
        for tb in try_blocks:
            label = f"Handle {tb['exception_type']}"
            tech = f"except {tb['exception_type']}: {tb['error_action']}"
            step = make_step("conditional", label, tech, tb["line_number"], True)
            validation_steps.append(step)

        # Classify loops
        for lp in loops:
            label = lp["loop_summary"]
            tech = f"{lp['loop_summary']}: {lp['body_summary']}"
            step = make_step("loop", label, tech, lp["line_number"])
            processing_steps.append(step)

        # Response from returns
        for ret in returns:
            label = f"Return {ret['return_type']}"
            step = make_step("response", label, f"return {ret['return_type']}", ret["line_number"])
            response_steps.append(step)

        # Build phases (skip empty)
        all_steps = (
            validation_steps + processing_steps + database_steps + response_steps
        )

        # If very few steps, collapse into PROCESSING
        if len(all_steps) <= 2:
            processing_steps = all_steps
            validation_steps = []
            database_steps = []
            response_steps = []

        phases = []
        if validation_steps:
            phases.append({
                "phase_id": "validation",
                "name": "Validation",
                "color": "orange",
                "description": "",
                "steps": validation_steps,
            })
        if processing_steps:
            phases.append({
                "phase_id": "processing",
                "name": "Processing",
                "color": "blue",
                "description": "",
                "steps": processing_steps,
            })
        if database_steps:
            phases.append({
                "phase_id": "database",
                "name": "Database",
                "color": "purple",
                "description": "",
                "steps": database_steps,
            })
        if response_steps:
            phases.append({
                "phase_id": "response",
                "name": "Response",
                "color": "green",
                "description": "",
                "steps": response_steps,
            })

        return all_steps, phases

    # ── Step 5: Error Paths ─────────────────────────────────────────

    def _collect_error_paths(
        self, conditionals: list[dict], try_blocks: list[dict]
    ) -> list[dict]:
        errors = []
        for cond in conditionals:
            if not cond["is_error_path"]:
                continue
            exc = cond.get("http_exception") or {}
            errors.append({
                "trigger": cond["condition"][:60],
                "status_code": exc.get("status_code"),
                "message": exc.get("detail"),
            })
        for tb in try_blocks:
            errors.append({
                "trigger": f"exception: {tb['exception_type']}"[:60],
                "status_code": None,
                "message": tb["error_action"][:60] if tb["error_action"] else None,
            })
        return errors

    # ── Step 6: Plain English Descriptions ──────────────────────────

    @staticmethod
    def _has_python_syntax(text: str) -> bool:
        """Return True if text contains Python-like syntax."""
        if re.search(r"[{}\"]", text):
            return True
        if re.search(r"\bif\b.*\belse\b", text):
            return True
        if re.search(r"\bfor\b.*\bin\b", text):
            return True
        if re.search(r"'[^']*'", text):
            return True
        if re.search(r"'\s*:", text):
            return True
        # Catch dict variable references like {'key': variable, 'key2': variable}
        if re.search(r"\{['\"]?\w+['\"]?\s*:", text):
            return True
        return False

    _PHASE_FALLBACKS: dict[str, str] = {
        "validation": "Validates input and checks resources",
        "processing": "Executes request processing logic",
        "database": "Reads or writes data to the database",
        "response": "Returns the result to the caller",
    }

    def _describe_phase(self, phase: dict) -> str:
        pid = phase["phase_id"]
        steps = phase["steps"]
        if not steps:
            return f"Executes {phase['name']} operations"

        if pid == "validation":
            desc = self._describe_validation(steps)
        elif pid == "processing":
            desc = self._describe_processing(steps)
        elif pid == "database":
            desc = self._describe_database(steps)
        elif pid == "response":
            desc = self._describe_response(steps)
        else:
            desc = f"Executes {phase['name']} operations"

        if self._has_python_syntax(desc):
            return self._PHASE_FALLBACKS.get(pid, f"Executes {phase['name']} operations")
        return desc

    @staticmethod
    def _describe_validation(steps: list[dict]) -> str:
        parts = []
        for s in steps:
            if s["type"] == "db_read":
                # Extract resource name from technical string
                tech = s.get("technical", "")
                match = re.search(r"query\((\w+)\)", tech, re.IGNORECASE)
                resource = match.group(1) if match else "resource"
                parts.append(f"verifies {resource} exists")
            elif s["type"] == "conditional" and s["is_error_path"]:
                # Extract status code
                match = re.search(r"HTTPException\((\d+)\)", s.get("technical", ""))
                code = match.group(1) if match else "error"
                parts.append(f"returns {code} if check fails")
        if not parts:
            return "Validates request parameters before proceeding"
        return ". ".join(p.capitalize() for p in parts[:3])

    @staticmethod
    def _describe_processing(steps: list[dict]) -> str:
        parts = []
        for s in steps:
            if s["type"] == "service":
                name = re.search(r"(\w+)\(\)", s.get("technical", ""))
                fn = name.group(1) if name else "service"
                parts.append(f"calls {fn}")
            elif s["type"] == "filesystem":
                parts.append("performs file operations")
            elif s["type"] == "external":
                parts.append("calls external API")
            elif s["type"] == "loop":
                parts.append("iterates over data")
        if not parts:
            return "Processes the request"
        seen: set[str] = set()
        unique = []
        for p in parts:
            if p not in seen:
                seen.add(p)
                unique.append(p)
        return ". ".join(p.capitalize() for p in unique[:3])

    @staticmethod
    def _describe_database(steps: list[dict]) -> str:
        has_write = any(s["type"] == "db_write" for s in steps)
        has_commit = any(s["type"] == "db_commit" for s in steps)
        has_read = any(s["type"] == "db_read" for s in steps)

        # Try to extract model name
        model = None
        for s in steps:
            match = re.search(r"(?:query|add|delete)\((\w+)", s.get("technical", ""))
            if match:
                model = match.group(1)
                break

        resource = model or "records"
        if has_write and has_commit:
            return f"Saves {resource} to database and commits transaction"
        if has_write:
            return f"Writes {resource} to database"
        if has_read:
            return f"Fetches {resource} from database"
        return "Performs database operations"

    @staticmethod
    def _describe_response(steps: list[dict]) -> str:
        if steps:
            ret = steps[-1].get("technical", "")
            match = re.search(r"return (.+)", ret)
            if match:
                val = match.group(1).strip()[:40]
                # Don't expose raw Python expressions
                if re.search(r"[{}'\"]|\bif\b.*\belse\b", val):
                    return "Returns response data"
                return f"Returns {val}"
        return "Returns response"

    # ── Participants ────────────────────────────────────────────────

    @staticmethod
    def _build_participants(component: str, phases: list[dict]) -> list[dict]:
        participants = [
            {"id": "client", "label": "Client", "type": "client"},
            {"id": f"comp_{component}", "label": component, "type": "component"},
        ]
        seen = {"client", f"comp_{component}"}

        has_db = any(
            s["type"].startswith("db_") for p in phases for s in p["steps"]
        )
        has_fs = any(
            s["type"] == "filesystem" for p in phases for s in p["steps"]
        )
        has_ext = any(
            s["type"] == "external" for p in phases for s in p["steps"]
        )
        has_svc = any(
            s["type"] == "service" for p in phases for s in p["steps"]
        )

        if has_svc:
            # Find the first service name
            for p in phases:
                for s in p["steps"]:
                    if s["type"] == "service":
                        match = re.search(r"(\w+)\(\)", s.get("technical", ""))
                        name = match.group(1) if match else "service"
                        pid = f"svc_{name}"
                        if pid not in seen:
                            seen.add(pid)
                            participants.append(
                                {"id": pid, "label": name, "type": "service"}
                            )
                        break
                if len(participants) > 2:
                    break

        if has_db:
            participants.append(
                {"id": "database", "label": "Database", "type": "database"}
            )
        if has_fs:
            participants.append(
                {"id": "filesystem", "label": "Filesystem", "type": "filesystem"}
            )
        if has_ext:
            participants.append(
                {"id": "external", "label": "External API", "type": "external"}
            )
        return participants

    # ── Helpers ─────────────────────────────────────────────────────

    def _empty_analysis(
        self, rid: str, method: str, path: str, file: str, component: str
    ) -> dict:
        return {
            "route_id": rid,
            "method": method,
            "path": path,
            "file": file,
            "component": component,
            "handler_function": None,
            "parameters": [],
            "return_type": None,
            "phases": [],
            "error_paths": [],
            "participants": [
                {"id": "client", "label": "Client", "type": "client"},
                {"id": f"comp_{component}", "label": component, "type": "component"},
            ],
            "has_database": False,
            "has_filesystem": False,
            "has_external": False,
            "complexity": "simple",
        }
