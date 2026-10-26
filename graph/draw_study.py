"""Draw a study's workflow as a PDF, for a reader who wants to see what one
evaluation of a point does: knobs -> derived values -> geometry file ->
pre-check -> evaluate steps -> objectives. By hand:
  python -m graph.draw_study foilspfbpz_ax
  python -m graph.draw_study /path/to/draft.json -o draft.pdf --dot draft.dot
  python -m graph.draw_study ce_chain --format png    # or -o ce_chain.png
The study file is read as raw JSON, not through the loader, so a draft that
does not load yet still draws. A target is a path (it ends in .json or
contains '/') or the name of a study on the study path (mode_specs/ and
$AUTORESEARCH_STUDY_PATH). Rendering needs Graphviz `dot` on PATH; without
it, pass --dot to get the graph source alone.

Edges: solid = files a step reads from an earlier step (files_from); dashed
= a number taken from an earlier step's metric (params_from); dotted = the
rendered geometry file, or point values mapped into a step's params.
Exit 0: drawn. Exit 1: dot failed or is missing. Exit 2: a bad command line
or target.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import paths  # noqa: E402
import study as st  # noqa: E402

STUDY_PATH_ENV = "AUTORESEARCH_STUDY_PATH"
# Kits that submit simulation jobs, drawn apart from the analysis steps.
JOB_KITS = ("prodtools", "beamkit")
JOB_FIELDS = ("njobs", "events_per_job", "quorum")
FORMATS = ("pdf", "png")
PNG_DPI = "150"


def resolve_target(arg: str) -> Path:
    if arg.endswith(".json") or "/" in arg:
        path = Path(arg)
        if not path.is_file():
            raise ValueError(f"{arg}: no such study file")
        return path
    files = st.study_files(paths.MODES_DIR, os.environ.get(STUDY_PATH_ENV))
    path = st.study_named(files, arg)
    if path is None:
        raise ValueError(f"no study named {arg!r} in mode_specs/ or "
                         f"${STUDY_PATH_ENV}; pass the file's path for a draft")
    return path


def _stage_fcl(entry: Any) -> str:
    """The fcl a prodtools entry runs, or '' when its template is not
    found (a draft may name one that does not exist yet)."""
    if isinstance(entry, dict):
        return str(entry.get("fcl", ""))
    dirs = [paths.REPO_ROOT / "stage_entries"] + [
        Path(d) / "stage_entries"
        for d in os.environ.get(STUDY_PATH_ENV, "").split(":") if d]
    for d in dirs:
        path = d / f"{entry}.json"
        if path.is_file():
            try:
                return str(json.loads(path.read_text()).get("fcl", ""))
            except (json.JSONDecodeError, AttributeError):
                return ""
    return ""


def _e(text: Any) -> str:
    return html.escape(str(text), quote=True)


def _label(title: str, lines: List[str]) -> str:
    """An HTML-like Graphviz label: bold title, then one line per entry."""
    rows = [f"<B>{_e(title)}</B>"] + [_e(line) for line in lines]
    return "<" + '<BR ALIGN="LEFT"/>'.join(rows) + '<BR ALIGN="LEFT"/>>'


def _node(name: str, label: str, **attrs: str) -> str:
    extra = "".join(f', {k}="{v}"' for k, v in attrs.items())
    return f'  "{name}" [label={label}{extra}];'


def _edge(a: str, b: str, label: str = "", **attrs: str) -> str:
    parts = [f'label="{_e(label)}"'] if label else []
    parts += [f'{k}="{v}"' for k, v in attrs.items()]
    return f'  "{a}" -> "{b}" [{", ".join(parts)}];'


def _step_lines(s: Dict[str, Any]) -> List[str]:
    lines = [f"kit: {s['kit']}"]
    fixed = s.get("fixed") or {}
    if s["kit"] == "prodtools" and s.get("entry"):
        name = "inline" if isinstance(s["entry"], dict) else s["entry"]
        lines.append(f"entry: {name}")
        fcl = _stage_fcl(s["entry"])
        if fcl:
            lines.append(f"fcl: {fcl}")
    if "analysis" in fixed:
        lines.append(f"analysis: {fixed['analysis']}")
    job = [f"{k}={fixed[k]}" for k in JOB_FIELDS if k in fixed]
    if job:
        lines.append(", ".join(job))
    other = sorted(set(fixed) - set(JOB_FIELDS) - {"analysis", "memory_mb"})
    lines += [f"{k} = {fixed[k]}" for k in other]
    return lines


def study_dot(doc: Dict[str, Any]) -> str:
    """The Graphviz source of a study document's workflow."""
    out = ["digraph study {",
           '  rankdir=TB; nodesep=0.35; ranksep=0.45;',
           '  node [fontname="Helvetica", fontsize=10, style=filled, '
           'fillcolor=white];',
           '  edge [fontname="Helvetica", fontsize=9];',
           f'  labelloc=t; label={_label("study " + doc.get("name", "?"), [])};']
    knobs = doc.get("knobs") or []
    derive = doc.get("derive") or {}
    geom = doc.get("geom")
    steps = doc.get("evaluate") or []

    # Where point values (knobs and derived names) come from.
    point_src = None
    if knobs:
        lines = [f"{k['name']}  [{k['min']:g}, {k['max']:g}] {k.get('unit', '')}"
                 .rstrip() for k in knobs]
        out.append(_node("knobs", _label(f"knobs ({len(knobs)})", lines),
                         shape="box", fillcolor="#e8f0fe"))
        point_src = "knobs"
    dlines = [f"{k} = {v:g}" if isinstance(v, (int, float)) else f"{k} = {v}"
              for k, v in (derive.get("consts") or {}).items()]
    dlines += [f"{k} = {v}" for k, v in (derive.get("exprs") or {}).items()]
    dlines += [f"{k} = {p['kind']}({', '.join(p['control'])}) x {p['count']}"
               for k, p in (derive.get("profiles") or {}).items()]
    if dlines:
        out.append(_node("derive", _label("derived values", dlines),
                         shape="box", fillcolor="#f1f3f4"))
        if point_src:
            out.append(_edge(point_src, "derive"))
        point_src = "derive"

    if geom:
        n_keys = sum(1 for line in geom.get("lines", []) if "key" in line)
        out.append(_node("geom", _label("geometry file", [
            f"writer: {geom['writer']}", f"base: {geom['base']}",
            f"{n_keys} overridden keys"]), shape="note", fillcolor="#fef7e0"))
        if point_src:
            out.append(_edge(point_src, "geom"))

    pre = doc.get("preflight")
    if pre:
        out.append(_node("preflight", _label("pre-check", [f"kit: {pre['kit']}"]),
                         shape="octagon", fillcolor="#fce8e6"))
        for f in pre.get("files", []):
            out.append(_edge(f, "preflight", style="dotted"))

    for s in steps:
        name = f"step:{s['step']}"
        if s["kit"] in JOB_KITS:
            attrs = dict(shape="box3d", fillcolor="#d2e3fc")
        else:
            attrs = dict(shape="box", style="rounded,filled",
                         fillcolor="#e6f4ea")
        out.append(_node(name, _label(s["step"], _step_lines(s)), **attrs))
        for f in s.get("files", []):
            out.append(_edge(f, name, f, style="dotted", color="gray40"))
        for up in s.get("files_from", []):
            out.append(_edge(f"step:{up}", name, "files"))
        for param, src in sorted((s.get("params_from") or {}).items()):
            up, metric = src.split(".", 1)
            label = metric if metric == param else f"{metric} -> {param}"
            out.append(_edge(f"step:{up}", name, label,
                             style="dashed", color="#b06000"))
        if s.get("params") and point_src:
            mapped = ", ".join(f"{k}={v}" if k != v else k
                               for k, v in s["params"].items())
            out.append(_edge(point_src, name, mapped, style="dotted"))
        # The pre-check gates every step that waits for nothing else.
        if pre and not s.get("files_from") and not s.get("params_from"):
            out.append(_edge("preflight", name, "pass", style="dotted",
                             color="#c5221f"))

    bounds = {c["name"]: c for c in doc.get("constraints") or []}
    for o in doc.get("objectives") or []:
        lines = [o["metric"]]
        if o.get("transform", "none") != "none":
            lines.append(f"transform: {o['transform']}")
        c = bounds.get(o["name"])
        if c:
            side = "max" if "max" in c else "min"
            op = "<=" if side == "max" else ">="
            lines.append(f"constraint: {op} {c[side]:g} ({c['k_sigma']:g} sigma)")
        node = f"obj:{o['name']}"
        out.append(_node(node, _label(f"{o['direction']} {o['name']}", lines),
                         shape="doubleoctagon", fillcolor="#fde293"))
        out.append(_edge(f"step:{o['metric'].split('.', 1)[0]}", node,
                         penwidth="2"))
    for m in doc.get("extra_metrics") or []:
        node = f"extra:{m['name']}"
        out.append(_node(node, _label(m["name"], [m["metric"]]),
                         shape="ellipse", fontsize="9", color="gray50"))
        out.append(_edge(f"step:{m['metric'].split('.', 1)[0]}", node,
                         color="gray50"))
    out.append("}")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Draw a study's workflow graph as a PDF or PNG.")
    ap.add_argument("target", help="study name or path to a study .json")
    ap.add_argument("-o", "--output",
                    help="output file (default: <name>_workflow.<format> "
                         "here); a .pdf or .png suffix sets the format")
    ap.add_argument("--format", choices=FORMATS,
                    help="pdf or png (default: from --output, else pdf)")
    ap.add_argument("--dot", help="also write the Graphviz source here")
    args = ap.parse_args(argv)
    suffix = Path(args.output).suffix.lstrip(".").lower() if args.output else ""
    if args.format and suffix in FORMATS and suffix != args.format:
        ap.error(f"--format {args.format} contradicts --output {args.output}")
    fmt = args.format or (suffix if suffix in FORMATS else "pdf")
    try:
        path = resolve_target(args.target)
        doc = json.loads(path.read_text())
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"draw_study: {exc}", file=sys.stderr)
        return 2
    source = study_dot(doc)
    if args.dot:
        Path(args.dot).write_text(source)
        print(f"wrote {args.dot}")
    dot = shutil.which("dot")
    if dot is None:
        print("draw_study: Graphviz 'dot' is not on PATH; use --dot to write "
              "the source and render it elsewhere", file=sys.stderr)
        return 1
    output = args.output or f"{doc.get('name', path.stem)}_workflow.{fmt}"
    cmd = [dot, f"-T{fmt}", "-o", output]
    if fmt == "png":
        cmd.insert(1, f"-Gdpi={PNG_DPI}")
    proc = subprocess.run(cmd, input=source, text=True, capture_output=True)
    if proc.returncode != 0:
        print(f"draw_study: dot failed:\n{proc.stderr}", file=sys.stderr)
        return 1
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
