"""Test all Aircnc routes through the analysis API."""
import json
import urllib.request
from hashlib import md5

PROJECT_ID = "41c3d967-2aa8-47b0-abe0-f592caca60dd"
BASE = "http://localhost:8000"

# Get scan
scan = json.loads(urllib.request.urlopen(f"{BASE}/projects/{PROJECT_ID}/scans/latest").read())
scan_id = scan["id"]
routes = scan["routes"]
print(f"Scan ID: {scan_id}")
print(f"Total routes: {len(routes)}\n")

# Trigger batch analysis
req = urllib.request.Request(
    f"{BASE}/analyze/routes",
    data=json.dumps({"project_id": PROJECT_ID, "scan_id": scan_id}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST"
)
try:
    resp = json.loads(urllib.request.urlopen(req, timeout=60).read())
    print(f"Batch: {resp.get('analyzed', '?')} analyzed, {resp.get('failed', '?')} failed\n")
except Exception as e:
    print(f"Batch error: {e}\n")

# Fetch all analyses
analyses = json.loads(urllib.request.urlopen(
    f"{BASE}/analyze/routes?project_id={PROJECT_ID}&scan_id={scan_id}"
).read())
print(f"Analyses returned: {len(analyses)}\n")

# Build lookup by route_id
lookup = {a["route_id"]: a for a in analyses}

# Check each route
failures = []
for r in routes:
    method = r["method"]
    path = r["path"]
    comp = r.get("component", "?")
    fpath = r.get("file", "?")
    rid = md5(f"{method}:{path}".encode()).hexdigest()

    match = lookup.get(rid)
    if not match:
        status = "NO_ANALYSIS"
        print(f"  {comp:10s} {method:6s} {path:45s} NO ANALYSIS FOUND")
        failures.append((comp, method, path, "No analysis returned"))
        continue

    phases = match.get("phases", [])
    handler = match.get("handler_function")
    complexity = match.get("complexity", "?")
    total_steps = sum(len(p.get("steps", [])) for p in phases)
    phase_names = [p["phase_id"] for p in phases]
    has_desc = all(bool(p.get("description")) for p in phases)
    participants = match.get("participants", [])
    error_paths = match.get("error_paths", [])

    if phases and handler:
        icon = "OK"
    elif handler and not phases:
        icon = "WARN"
        failures.append((comp, method, path, f"handler={handler} but 0 phases"))
    else:
        icon = "FAIL"
        failures.append((comp, method, path, f"handler={handler}, phases={len(phases)}"))

    print(f"  [{icon:4s}] {comp:10s} {method:6s} {path:45s} handler={str(handler):30s} phases={phase_names} steps={total_steps} complexity={complexity}")
    if not has_desc and phases:
        print(f"         WARNING: Missing descriptions in some phases")
    for p in phases:
        desc = p.get("description", "")
        steps = p.get("steps", [])
        print(f"         {p['phase_id']:12s} ({len(steps)} steps): {desc[:70]}")

# Also check sequence diagram availability
print(f"\n{'='*80}")
print("SEQUENCE DIAGRAM CHECK:")
for r in routes:
    method = r["method"]
    path = r["path"]
    comp = r.get("component", "?")
    rid = md5(f"{method}:{path}".encode()).hexdigest()
    try:
        seq = json.loads(urllib.request.urlopen(
            f"{BASE}/projects/{PROJECT_ID}/sequence?route_id={rid}"
        ).read())
        parts = len(seq.get("participants", []))
        msgs = len(seq.get("messages", []))
        svg = bool(seq.get("svg"))
        print(f"  [{('SVG' if svg else 'NO_SVG'):6s}] {comp:10s} {method:6s} {path:45s} participants={parts} messages={msgs}")
        if not svg and not msgs:
            failures.append((comp, method, path, "No sequence diagram"))
    except Exception as e:
        print(f"  [ERROR ] {comp:10s} {method:6s} {path:45s} {str(e)[:60]}")

print(f"\n{'='*80}")
if failures:
    print(f"FAILURES ({len(failures)}):")
    for comp, method, path, reason in failures:
        print(f"  {comp:10s} {method:6s} {path:45s} {reason}")
else:
    print("ALL ROUTES PASSED!")
