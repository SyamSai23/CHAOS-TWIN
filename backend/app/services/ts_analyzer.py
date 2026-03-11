"""
Multi-language route analysis engine using tree-sitter.

Handles JavaScript, TypeScript, Java, Go, Ruby, and C# routes.
Python routes continue to use stdlib ast in ast_analyzer.py.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import warnings
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        from tree_sitter_languages import get_parser as _get_ts_parser
    _HAS_TREE_SITTER = True
except ImportError:
    _HAS_TREE_SITTER = False
    logger.info("tree-sitter not available; non-Python analysis disabled")


# ── Extension → language mapping ────────────────────────────────────

_EXT_TO_LANG: dict[str, str] = {
    ".js": "javascript", ".jsx": "javascript",
    ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "tsx",
    ".java": "java",
    ".go": "go",
    ".rb": "ruby",
    ".cs": "c_sharp",
}

# ── Call classification patterns ────────────────────────────────────

_DB_READ_METHODS = {
    "find", "findOne", "findById", "findAll", "findByPk",
    "findUnique", "findFirst", "findMany", "findOneAndReplace",
    "aggregate", "count", "countDocuments", "distinct",
    "query", "select", "exec", "populate",
    "getRepository", "createQueryBuilder",
}
_DB_WRITE_METHODS = {
    "create", "save", "insert", "insertOne", "insertMany",
    "update", "updateOne", "updateMany", "upsert",
    "delete", "deleteOne", "deleteMany", "remove", "destroy",
    "bulkCreate", "bulkWrite",
    "findOneAndUpdate", "findOneAndDelete",
    "findByIdAndUpdate", "findByIdAndDelete", "findByIdAndRemove",
}
_DB_COMMIT_METHODS = {"commit", "flush", "rollback", "transaction"}

_EXTERNAL_CALLERS = {
    "fetch", "axios", "got", "superagent",
    "http", "https", "HttpClient", "RestTemplate", "WebClient",
}
_FS_CALLERS = {"fs", "path"}
_FS_METHODS = {
    "readFile", "writeFile", "readFileSync", "writeFileSync",
    "readdir", "readdirSync", "mkdir", "mkdirSync",
    "unlink", "unlinkSync", "rename", "renameSync",
    "stat", "statSync", "exists", "existsSync",
    "createReadStream", "createWriteStream",
    "copyFile", "copyFileSync",
}

_RESPONSE_METHODS = {
    "json", "send", "end", "render", "redirect",
    "sendFile", "sendStatus",
}

_SKIP_CALLERS = {
    "console", "process", "Math", "Date", "JSON", "Promise",
    "Array", "Object", "String", "Number", "RegExp", "Error",
}
_SKIP_METHODS = {
    "log", "error", "warn", "info", "debug",
    "toString", "parseInt", "parseFloat", "isNaN",
    "stringify", "parse",
    "push", "pop", "shift", "unshift", "splice", "slice", "concat",
    "map", "filter", "forEach", "reduce", "some", "every",
    "flat", "flatMap",
    "join", "split", "trim", "toLowerCase", "toUpperCase",
    "includes", "startsWith", "endsWith", "replace", "match", "test",
    "keys", "values", "entries", "assign", "freeze",
    "require", "emit", "next", "then", "catch",
    "bind", "call", "apply",
    "addEventListener", "removeEventListener",
    "setTimeout", "setInterval", "clearTimeout", "clearInterval",
    "resolve", "reject",
}

_SKIP_PARAMS = {
    "req", "res", "request", "response", "next",
    "ctx", "c", "w", "r", "self", "this",
}


def _route_id(method: str, path: str) -> str:
    raw = f"{method.upper()}:{path}"
    return hashlib.md5(raw.encode()).hexdigest()


# ── Tree-sitter node helpers (module-level for reuse) ───────────────

def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _line(node) -> int:
    return node.start_point[0] + 1


def _walk(node):
    """Depth-first generator over all descendants."""
    yield node
    for child in node.children:
        yield from _walk(child)


def _unquote(s: str) -> str:
    if len(s) >= 2 and s[0] in ('"', "'", '`') and s[-1] == s[0]:
        return s[1:-1]
    return s


def _normalize_path(path: str) -> str:
    return re.sub(r"[:{]\w+[}]?", "{}", path.rstrip("/")) or "/"


def _extract_string(node, src: bytes) -> str | None:
    """Extract plain text from a string node (strips quotes)."""
    for child in node.children:
        if child.type == "string_fragment":
            return _text(child, src)
    t = _text(node, src)
    return _unquote(t) if t else None


def _get_body(node):
    """Get the statement_block from a function / arrow / method node."""
    if node is None:
        return None
    if node.type == "statement_block":
        return node
    body = node.child_by_field_name("body")
    if body:
        return body
    for child in node.children:
        if child.type == "statement_block":
            return child
    return None


def _root_caller(node, src: bytes) -> str:
    """Resolve the deepest caller in a chain like res.status(400).json()."""
    if node is None:
        return ""
    if node.type == "identifier":
        return _text(node, src)
    if node.type == "member_expression":
        obj = node.child_by_field_name("object")
        return _root_caller(obj, src) if obj else ""
    if node.type == "call_expression":
        func = node.child_by_field_name("function")
        return _root_caller(func, src) if func else ""
    return _text(node, src)[:20]


# ════════════════════════════════════════════════════════════════════
# TreeSitterAnalyzer
# ════════════════════════════════════════════════════════════════════

class TreeSitterAnalyzer:
    """Analyzes route handlers for non-Python languages via tree-sitter."""

    def __init__(self, workspace_path: str):
        self._ws = Path(workspace_path)
        self._cache: dict[str, tuple | None] = {}
        self._parsers: dict[str, Any] = {}

    @staticmethod
    def available() -> bool:
        return _HAS_TREE_SITTER

    @staticmethod
    def supports(file_rel: str) -> bool:
        return Path(file_rel).suffix.lower() in _EXT_TO_LANG

    # ── Parsing ─────────────────────────────────────────────────

    def _get_parser(self, lang: str):
        if lang not in self._parsers:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", FutureWarning)
                self._parsers[lang] = _get_ts_parser(lang)
        return self._parsers[lang]

    def _parse(self, file_rel: str):
        """Return (tree, source_bytes) or None."""
        if file_rel in self._cache:
            return self._cache[file_rel]
        full = self._ws / file_rel
        if not full.is_file():
            self._cache[file_rel] = None
            return None
        ext = Path(file_rel).suffix.lower()
        lang = _EXT_TO_LANG.get(ext)
        if not lang:
            self._cache[file_rel] = None
            return None
        try:
            source = full.read_bytes()
            parser = self._get_parser(lang)
            tree = parser.parse(source)
            result = (tree, source)
            self._cache[file_rel] = result
            return result
        except Exception:
            logger.warning("tree-sitter parse error: %s", file_rel)
            self._cache[file_rel] = None
            return None

    # ── Handler finding: orchestrator ───────────────────────────

    def _find_handler(self, tree, source, file_rel, method, path):
        """Find handler body node.

        Returns (handler_name, body_node, source_bytes) or None.
        """
        root = tree.root_node
        ext = Path(file_rel).suffix.lower()
        lang = _EXT_TO_LANG.get(ext, "")

        if lang in ("javascript", "typescript", "tsx"):
            r = self._find_exported_handler(root, source, method)
            if r:
                return r
            r = self._find_express_handler(root, source, file_rel, method, path)
            if r:
                return r

        if lang in ("java", "c_sharp"):
            r = self._find_annotated_handler(root, source, method, path)
            if r:
                return r

        if lang == "go":
            r = self._find_go_handler(root, source, method, path)
            if r:
                return r

        if lang == "ruby":
            r = self._find_ruby_handler(root, source, method, path)
            if r:
                return r

        return None

    # ── Strategy 1: Exported method (file-system routing) ───────

    def _find_exported_handler(self, root, src, method):
        """export function GET() or export const POST = async () => ..."""
        mu = method.upper()
        for node in _walk(root):
            if node.type != "export_statement":
                continue
            for child in node.children:
                if child.type == "function_declaration":
                    n = child.child_by_field_name("name")
                    if n and _text(n, src).upper() == mu:
                        body = _get_body(child)
                        if body:
                            return (mu, body, src)
                if child.type == "lexical_declaration":
                    for decl in child.children:
                        if decl.type != "variable_declarator":
                            continue
                        n = decl.child_by_field_name("name")
                        v = decl.child_by_field_name("value")
                        if n and _text(n, src).upper() == mu and v:
                            body = _get_body(v)
                            if body:
                                return (mu, body, src)
        return None

    # ── Strategy 2: Express-style routing ───────────────────────

    def _find_express_handler(self, root, src, file_rel, method, path):
        """routes.post('/path', handler) or router.route('/path').post(…)"""
        ml = method.lower()
        norm = _normalize_path(path)

        for node in _walk(root):
            if node.type != "call_expression":
                continue
            func = node.child_by_field_name("function")
            args = node.child_by_field_name("arguments")
            if not func or not args:
                continue

            handler_arg = None

            # Pattern A: router.get('/path', handler)
            if func.type == "member_expression":
                prop = func.child_by_field_name("property")
                if prop and _text(prop, src).lower() == ml:
                    al = [c for c in args.children
                          if c.type not in ("(", ")", ",")]
                    if al and self._path_matches(al[0], src, norm):
                        handler_arg = al[-1] if len(al) > 1 else None

            # Pattern B: router.route('/path').get(handler)
            if not handler_arg and func.type == "member_expression":
                prop = func.child_by_field_name("property")
                obj = func.child_by_field_name("object")
                if (prop and _text(prop, src).lower() == ml
                        and obj and obj.type == "call_expression"):
                    ifn = obj.child_by_field_name("function")
                    iag = obj.child_by_field_name("arguments")
                    if ifn and ifn.type == "member_expression":
                        ip = ifn.child_by_field_name("property")
                        if ip and _text(ip, src) == "route" and iag:
                            pn = next((c for c in iag.children
                                       if c.type not in ("(", ")", ",")), None)
                            if pn and self._path_matches(pn, src, norm):
                                al = [c for c in args.children
                                      if c.type not in ("(", ")", ",")]
                                handler_arg = al[-1] if al else None

            if handler_arg is None:
                continue

            # Unwrap wrappers like catchErrors(handler)
            handler_arg = self._unwrap_call(handler_arg)

            # Case A: inline arrow / function expression
            body = _get_body(handler_arg)
            if body:
                return ("handler", body, src)

            # Case B: Controller.method reference
            if handler_arg.type == "member_expression":
                on = handler_arg.child_by_field_name("object")
                pn = handler_arg.child_by_field_name("property")
                if on and pn:
                    obj_name = _text(on, src)
                    meth_name = _text(pn, src)
                    found = self._find_method_in_file(
                        root, src, obj_name, meth_name,
                    )
                    if found:
                        return (f"{obj_name}.{meth_name}", found, src)
                    imp = self._resolve_import(root, src, obj_name, file_rel)
                    if imp:
                        parsed = self._parse(imp)
                        if parsed:
                            it, isrc = parsed
                            found = self._find_method_in_file(
                                it.root_node, isrc, None, meth_name,
                            )
                            if found:
                                return (f"{obj_name}.{meth_name}", found, isrc)

            # Case C: plain identifier
            if handler_arg.type == "identifier":
                name = _text(handler_arg, src)
                found = self._find_function_by_name(root, src, name)
                if found:
                    return (name, found, src)

        return None

    # ── Strategy 3: Java / C# annotation-based ─────────────────

    def _find_annotated_handler(self, root, src, method, path):
        mu = method.upper()
        norm = _normalize_path(path)
        ann_map = {
            "GET": {"GetMapping", "HttpGet"},
            "POST": {"PostMapping", "HttpPost"},
            "PUT": {"PutMapping", "HttpPut"},
            "DELETE": {"DeleteMapping", "HttpDelete"},
            "PATCH": {"PatchMapping", "HttpPatch"},
        }
        targets = ann_map.get(mu, set()) | {"RequestMapping"}

        for node in _walk(root):
            if node.type != "method_declaration":
                continue
            for child in node.children:
                hit = self._check_annotation(child, src, targets, mu, norm)
                if hit:
                    body = node.child_by_field_name("body")
                    nn = node.child_by_field_name("name")
                    if body:
                        return (_text(nn, src) if nn else "handler", body, src)
                if child.type == "modifiers":
                    for mod in child.children:
                        hit = self._check_annotation(mod, src, targets, mu, norm)
                        if hit:
                            body = node.child_by_field_name("body")
                            nn = node.child_by_field_name("name")
                            if body:
                                return (_text(nn, src) if nn else "handler", body, src)
        return None

    @staticmethod
    def _check_annotation(node, src, targets, method_upper, norm_path):
        if node.type not in ("annotation", "marker_annotation", "attribute"):
            return False
        at = _text(node, src)
        for t in targets:
            if t not in at:
                continue
            if t == "RequestMapping" and method_upper not in at.upper():
                continue
            if norm_path != "/" and not any(
                _normalize_path(m) == norm_path
                for m in re.findall(r'["\']([^"\']+)["\']', at)
            ):
                continue
            return True
        return False

    # ── Strategy 4: Go ──────────────────────────────────────────

    def _find_go_handler(self, root, src, method, path):
        norm = _normalize_path(path)
        mu = method.upper()
        for node in _walk(root):
            if node.type != "call_expression":
                continue
            func = node.child_by_field_name("function")
            args = node.child_by_field_name("arguments")
            if not func or not args:
                continue
            ft = _text(func, src)
            if not (ft.endswith(f".{mu}") or ft.endswith(".HandleFunc")
                    or ft.endswith(".Handle")):
                continue
            al = [c for c in args.children if c.type not in ("(", ")", ",")]
            if not al or not self._path_matches(al[0], src, norm):
                continue
            if len(al) < 2:
                continue
            h = al[-1]
            if h.type == "func_literal":
                body = _get_body(h)
                if body:
                    return ("handler", body, src)
            if h.type == "identifier":
                name = _text(h, src)
                for n in _walk(root):
                    if n.type == "function_declaration":
                        fn = n.child_by_field_name("name")
                        if fn and _text(fn, src) == name:
                            body = _get_body(n)
                            if body:
                                return (name, body, src)
        return None

    # ── Strategy 5: Ruby ────────────────────────────────────────

    def _find_ruby_handler(self, root, src, method, path):
        ml = method.lower()
        norm = _normalize_path(path)
        for node in _walk(root):
            if node.type != "call" or not node.children:
                continue
            first = node.children[0]
            if first.type != "identifier" or _text(first, src).lower() != ml:
                continue
            for child in node.children:
                if child.type in ("argument_list", "string"):
                    raw = _extract_string(child, src) or _unquote(_text(child, src))
                    if _normalize_path(raw) == norm:
                        for block in node.children:
                            if block.type in ("do_block", "block"):
                                return (f"{ml} {path}", block, src)
        return None

    # ── Handler resolution helpers ──────────────────────────────

    @staticmethod
    def _unwrap_call(node):
        """Unwrap wrappers like catchErrors(handler)."""
        if node.type == "call_expression":
            args = node.child_by_field_name("arguments")
            if args:
                inner = [c for c in args.children
                         if c.type not in ("(", ")", ",")]
                if inner:
                    return TreeSitterAnalyzer._unwrap_call(inner[0])
        return node

    @staticmethod
    def _path_matches(node, src, norm_target):
        for child in node.children:
            if child.type == "string_fragment":
                return _normalize_path(_text(child, src)) == norm_target
        return _normalize_path(_unquote(_text(node, src))) == norm_target

    def _find_function_by_name(self, root, src, name):
        """Find a function/const-arrow by name → return its body."""
        for node in _walk(root):
            if node.type == "function_declaration":
                n = node.child_by_field_name("name")
                if n and _text(n, src) == name:
                    return _get_body(node)
            if node.type == "variable_declarator":
                n = node.child_by_field_name("name")
                v = node.child_by_field_name("value")
                if n and _text(n, src) == name and v:
                    b = _get_body(v)
                    if b:
                        return b
            if node.type == "method_definition":
                n = node.child_by_field_name("name")
                if n and _text(n, src) == name:
                    return _get_body(node)
        return None

    def _find_method_in_file(self, root, src, obj_name, method_name):
        """Find method in module.exports object or class body."""
        for node in _walk(root):
            # module.exports = { method_name() { ... } }
            if node.type == "assignment_expression":
                left = node.child_by_field_name("left")
                right = node.child_by_field_name("right")
                if left and right and right.type == "object":
                    if "exports" in _text(left, src):
                        r = self._find_in_object(right, src, method_name)
                        if r:
                            return r
            # class Name { method() {} }
            if node.type == "class_declaration":
                cn = node.child_by_field_name("name")
                if cn and (not obj_name or _text(cn, src) == obj_name):
                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            if child.type == "method_definition":
                                n = child.child_by_field_name("name")
                                if n and _text(n, src) == method_name:
                                    return _get_body(child)
        return self._find_function_by_name(root, src, method_name)

    @staticmethod
    def _find_in_object(obj_node, src, method_name):
        """Find a method or pair inside an object literal."""
        for child in obj_node.children:
            if child.type == "method_definition":
                n = child.child_by_field_name("name")
                if n and _text(n, src) == method_name:
                    return _get_body(child)
            if child.type == "pair":
                k = child.child_by_field_name("key")
                v = child.child_by_field_name("value")
                if k and _text(k, src) == method_name and v:
                    return _get_body(v) or v
        return None

    # ── Import resolution ───────────────────────────────────────

    def _resolve_import(self, root, src, name, from_file):
        """Resolve where 'name' is imported from → workspace-relative path."""
        for node in _walk(root):
            # const X = require('./path')
            if node.type == "variable_declarator":
                n = node.child_by_field_name("name")
                v = node.child_by_field_name("value")
                if (n and _text(n, src) == name
                        and v and v.type == "call_expression"):
                    fn = v.child_by_field_name("function")
                    if fn and _text(fn, src) == "require":
                        a = v.child_by_field_name("arguments")
                        if a:
                            pn = next(
                                (c for c in a.children
                                 if c.type not in ("(", ")", ",")),
                                None,
                            )
                            if pn:
                                raw = _extract_string(pn, src)
                                if raw:
                                    return self._resolve_path(raw, from_file)
            # import X from './path'
            if node.type == "import_statement":
                sn = node.child_by_field_name("source")
                found = any(
                    c.type == "identifier" and _text(c, src) == name
                    for c in _walk(node)
                )
                if found and sn:
                    raw = _extract_string(sn, src)
                    if raw:
                        return self._resolve_path(raw, from_file)
        return None

    def _resolve_path(self, import_path, from_file):
        if not import_path.startswith("."):
            return None
        from_dir = str(Path(from_file).parent)
        candidate = os.path.normpath(os.path.join(from_dir, import_path))
        for ext in ("", ".js", ".ts", ".jsx", ".tsx",
                     "/index.js", "/index.ts"):
            full = self._ws / (candidate + ext)
            if full.is_file():
                return candidate + ext
        return None

    # ── Step extraction ─────────────────────────────────────────

    def _extract_steps(self, body_node, src):
        steps: list[dict] = []
        counter = [0]

        def make(stype, label, technical, ln, is_error=False):
            counter[0] += 1
            return {
                "step_id": f"s{counter[0]}",
                "type": stype,
                "label": label,
                "technical": technical,
                "line_number": ln,
                "is_error_path": is_error,
            }

        for node in _walk(body_node):
            if node.type == "call_expression":
                # Skip inner calls in chains (parent is member_expression)
                if node.parent and node.parent.type == "member_expression":
                    continue
                step = self._step_from_call(node, src, make)
                if step:
                    steps.append(step)

            elif node.type == "if_statement":
                step = self._step_from_if(node, src, make)
                if step:
                    steps.append(step)

            elif node.type == "catch_clause":
                param = node.child_by_field_name("parameter")
                if not param:
                    for child in node.children:
                        if child.type == "identifier":
                            param = child
                            break
                exc = _text(param, src)[:30] if param else "error"
                steps.append(make(
                    "conditional", f"Handle {exc}",
                    f"catch ({exc})", _line(node), True,
                ))

            elif node.type in (
                "for_statement", "for_in_statement", "while_statement",
                "for_of_statement", "enhanced_for_statement",
                "for_range_statement",
            ):
                summary = _text(node, src).split("\n")[0][:60]
                steps.append(make("loop", summary, summary, _line(node)))

        return steps

    def _step_from_call(self, node, src, make):
        func = node.child_by_field_name("function")
        if not func:
            return None
        ln = _line(node)
        caller = ""
        method_name = ""

        if func.type == "member_expression":
            obj = func.child_by_field_name("object")
            prop = func.child_by_field_name("property")
            if prop:
                method_name = _text(prop, src)
            if obj:
                caller = _root_caller(obj, src)
        elif func.type == "identifier":
            method_name = _text(func, src)
        else:
            return None

        if not method_name:
            return None
        # Skip response calls (handled separately)
        if caller in ("res", "response", "resp") and method_name in _RESPONSE_METHODS:
            return None
        if caller in _SKIP_CALLERS or method_name in _SKIP_METHODS:
            return None

        ct = _classify_call(caller, method_name)
        label = _call_label(caller, method_name, ct)
        tech = f"{caller}.{method_name}()" if caller else f"{method_name}()"
        return make(ct, label, tech, ln)

    @staticmethod
    def _step_from_if(node, src, make):
        cond_node = node.child_by_field_name("condition")
        if not cond_node:
            return None
        cond = _text(cond_node, src)
        if cond.startswith("(") and cond.endswith(")"):
            cond = cond[1:-1]
        cond = cond[:60]
        ln = _line(node)

        consequence = node.child_by_field_name("consequence")
        is_error = False
        status_code = None
        if consequence:
            bt = _text(consequence, src)
            if any(kw in bt for kw in (
                "throw ", "status(4", "status(5", "Error(", '"error"',
            )):
                is_error = True
                m = re.search(r"status\((\d{3})\)", bt)
                if m:
                    status_code = m.group(1)

        if is_error:
            label = f"Check: {cond}"
            tech = f"if ({cond})"
            if status_code:
                tech += f" \u2192 {status_code}"
            return make("conditional", label, tech, ln, True)
        return make("conditional", f"Branch: {cond}", f"if ({cond})", ln)

    # ── Response extraction ─────────────────────────────────────

    @staticmethod
    def _extract_response_steps(body_node, src, start=100):
        steps: list[dict] = []
        ctr = [start]
        seen: set[int] = set()
        for node in _walk(body_node):
            if node.type != "call_expression":
                continue
            func = node.child_by_field_name("function")
            if not func or func.type != "member_expression":
                continue
            prop = func.child_by_field_name("property")
            if not prop:
                continue
            mn = _text(prop, src)
            if mn not in ("json", "send", "render", "sendFile"):
                continue
            obj = func.child_by_field_name("object")
            rc = _root_caller(obj, src) if obj else ""
            if rc not in ("res", "response", "resp"):
                continue
            ln = _line(node)
            if ln in seen:
                continue
            seen.add(ln)
            ctr[0] += 1
            steps.append({
                "step_id": f"s{ctr[0]}",
                "type": "response",
                "label": f"Send response via {mn}()",
                "technical": f"res.{mn}()",
                "line_number": ln,
                "is_error_path": False,
            })
        return steps

    # ── Phase classification ────────────────────────────────────

    @staticmethod
    def _classify_into_phases(steps):
        validation: list[dict] = []
        processing: list[dict] = []
        database: list[dict] = []
        response: list[dict] = []

        total = len(steps)
        early = max(1, total // 3)

        for i, s in enumerate(steps):
            t = s["type"]
            if t == "conditional" and s["is_error_path"]:
                validation.append(s)
            elif t == "conditional":
                processing.append(s)
            elif t == "db_read" and i < early:
                validation.append(s)
            elif t in ("db_read", "db_write", "db_commit"):
                database.append(s)
            elif t == "response":
                response.append(s)
            else:
                processing.append(s)

        all_steps = validation + processing + database + response
        if len(all_steps) <= 2:
            processing = all_steps
            validation, database, response = [], [], []

        phases: list[dict] = []
        if validation:
            phases.append({
                "phase_id": "validation", "name": "Validation",
                "color": "orange", "description": "", "steps": validation,
            })
        if processing:
            phases.append({
                "phase_id": "processing", "name": "Processing",
                "color": "blue", "description": "", "steps": processing,
            })
        if database:
            phases.append({
                "phase_id": "database", "name": "Database",
                "color": "purple", "description": "", "steps": database,
            })
        if response:
            phases.append({
                "phase_id": "response", "name": "Response",
                "color": "green", "description": "", "steps": response,
            })

        for p in phases:
            p["description"] = _describe_phase(p)
        return phases

    # ── Error paths ─────────────────────────────────────────────

    @staticmethod
    def _collect_error_paths(steps):
        errors = []
        for s in steps:
            if not s["is_error_path"]:
                continue
            tech = s.get("technical", "")
            status = None
            m = re.search(r"(\d{3})", tech)
            if m:
                status = int(m.group(1))
            errors.append({
                "trigger": s.get("label", "")[:60],
                "status_code": status,
                "message": tech[:60],
            })
        return errors

    # ── Participants ────────────────────────────────────────────

    @staticmethod
    def _build_participants(component, phases):
        parts = [
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
            for p in phases:
                for s in p["steps"]:
                    if s["type"] == "service":
                        m = re.search(r"(\w+)\(", s.get("technical", ""))
                        name = m.group(1) if m else "service"
                        pid = f"svc_{name}"
                        if pid not in seen:
                            seen.add(pid)
                            parts.append({
                                "id": pid, "label": name, "type": "service",
                            })
                        break
                if len(parts) > 2:
                    break

        if has_db:
            parts.append(
                {"id": "database", "label": "Database", "type": "database"}
            )
        if has_fs:
            parts.append(
                {"id": "filesystem", "label": "Filesystem", "type": "filesystem"}
            )
        if has_ext:
            parts.append(
                {"id": "external", "label": "External API", "type": "external"}
            )
        return parts

    # ── Parameters ──────────────────────────────────────────────

    @staticmethod
    def _extract_params(body_node, src):
        params: list[dict] = []
        parent = body_node.parent
        if not parent:
            return params
        pn = parent.child_by_field_name("parameters")
        if not pn:
            for child in parent.children:
                if child.type in ("formal_parameters", "parameters"):
                    pn = child
                    break
        if not pn:
            return params
        for child in pn.children:
            if child.type == "identifier":
                name = _text(child, src)
                if name not in _SKIP_PARAMS and name not in ("(", ")", ","):
                    params.append({"name": name, "type": None})
            elif child.type in ("required_parameter", "optional_parameter"):
                n = (child.child_by_field_name("pattern")
                     or child.child_by_field_name("name"))
                if n:
                    name = _text(n, src)
                    if name not in _SKIP_PARAMS:
                        tn = child.child_by_field_name("type")
                        params.append({
                            "name": name,
                            "type": _text(tn, src) if tn else None,
                        })
        return params

    # ── Full analysis entry point ───────────────────────────────

    def analyze(self, route: dict) -> dict | None:
        """Analyze a single non-Python route.

        Returns a RouteAnalysis dict, or None if the file can't be parsed.
        """
        method = route.get("method", "GET").upper()
        path = route.get("path", "/")
        file_rel = route.get("file", "")
        component = route.get("component", "unknown")
        rid = _route_id(method, path)

        empty = {
            "route_id": rid, "method": method, "path": path,
            "file": file_rel, "component": component,
            "handler_function": None, "parameters": [],
            "return_type": None, "phases": [], "error_paths": [],
            "participants": [
                {"id": "client", "label": "Client", "type": "client"},
                {"id": f"comp_{component}", "label": component,
                 "type": "component"},
            ],
            "has_database": False, "has_filesystem": False,
            "has_external": False, "complexity": "simple",
        }

        parsed = self._parse(file_rel)
        if parsed is None:
            logger.warning("Cannot parse %s for %s %s", file_rel, method, path)
            return None

        tree, source = parsed

        try:
            result = self._find_handler(tree, source, file_rel, method, path)
        except Exception:
            logger.exception("Handler search failed for %s %s", method, path)
            return empty

        if result is None:
            logger.info("No handler for %s %s in %s", method, path, file_rel)
            return empty

        handler_name, body_node, body_src = result

        try:
            steps = self._extract_steps(body_node, body_src)
            if not any(s["type"] == "response" for s in steps):
                steps.extend(
                    self._extract_response_steps(
                        body_node, body_src, len(steps) + 100,
                    )
                )
            phases = self._classify_into_phases(steps)
            error_paths = self._collect_error_paths(steps)
            participants = self._build_participants(component, phases)
        except Exception:
            logger.exception("Step extraction failed for %s %s", method, path)
            return empty

        total = sum(len(p["steps"]) for p in phases)
        pc = len(phases)
        if pc <= 1 and total < 5:
            complexity = "simple"
        elif pc >= 4 or total > 15:
            complexity = "complex"
        else:
            complexity = "moderate"

        has_db = any(
            s["type"].startswith("db_") for p in phases for s in p["steps"]
        )
        has_fs = any(
            s["type"] == "filesystem" for p in phases for s in p["steps"]
        )
        has_ext = any(
            s["type"] == "external" for p in phases for s in p["steps"]
        )

        return {
            "route_id": rid,
            "method": method,
            "path": path,
            "file": file_rel,
            "component": component,
            "handler_function": handler_name or "handler",
            "parameters": self._extract_params(body_node, body_src),
            "return_type": None,
            "phases": phases,
            "error_paths": error_paths,
            "participants": participants,
            "has_database": has_db,
            "has_filesystem": has_fs,
            "has_external": has_ext,
            "complexity": complexity,
        }


# ── Module-level helpers (shared by step methods) ───────────────────

def _classify_call(caller: str, method_name: str) -> str:
    if method_name in _DB_WRITE_METHODS:
        return "db_write"
    if method_name in _DB_READ_METHODS:
        return "db_read"
    if method_name in _DB_COMMIT_METHODS:
        return "db_commit"
    if caller in _EXTERNAL_CALLERS or method_name == "fetch":
        return "external"
    if caller in _FS_CALLERS or method_name in _FS_METHODS:
        return "filesystem"
    return "service"


def _call_label(caller: str, method: str, call_type: str) -> str:
    if call_type == "db_read":
        return f"Query {caller}.{method}()" if caller else f"Query {method}()"
    if call_type == "db_write":
        return f"Write {caller}.{method}()" if caller else f"Write {method}()"
    if call_type == "db_commit":
        return "Commit transaction"
    if call_type == "filesystem":
        return f"File operation: {method}()"
    if call_type == "external":
        return (f"External call: {caller}.{method}()" if caller
                else f"External call: {method}()")
    name = f"{caller}.{method}" if caller else method
    return f"Call {name}()"


def _describe_phase(phase: dict) -> str:
    pid = phase["phase_id"]
    steps = phase["steps"]
    if not steps:
        return f"Executes {phase['name']} operations"

    if pid == "validation":
        checks = [s for s in steps if s["is_error_path"]]
        reads = [s for s in steps if s["type"] == "db_read"]
        parts: list[str] = []
        if reads:
            parts.append("looks up required resources")
        if checks:
            parts.append(f"validates with {len(checks)} check(s)")
        return (". ".join(p.capitalize() for p in parts)
                if parts else "Validates request parameters")

    if pid == "processing":
        types = {s["type"] for s in steps}
        parts = []
        if "service" in types:
            parts.append("calls service functions")
        if "external" in types:
            parts.append("makes external API calls")
        if "filesystem" in types:
            parts.append("performs file operations")
        if "loop" in types:
            parts.append("iterates over data")
        return (". ".join(p.capitalize() for p in parts)
                if parts else "Processes the request")

    if pid == "database":
        has_w = any(s["type"] == "db_write" for s in steps)
        has_r = any(s["type"] == "db_read" for s in steps)
        if has_w and has_r:
            return "Reads and writes data to the database"
        if has_w:
            return "Writes data to the database"
        return "Reads data from the database"

    if pid == "response":
        return "Returns the response to the caller"

    return f"Executes {phase['name']} operations"
