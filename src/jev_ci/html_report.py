"""Self-contained, offline finding review with honest diff localization."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

from .errors import TraceError
from .reporting import _anchor, _safe, _usage_lines
from .trace import inspect_pack
from .util import atomic_bytes


STYLE = """
:root{color-scheme:light;--ink:#182538;--muted:#65748a;--line:#dfe5ec;--bg:#f5f7fa;--blue:#2165c7;--red:#ba3548;--amber:#956414;--green:#247449}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:24px}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}code,pre,.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}code{font-size:12px;overflow-wrap:anywhere}h1,h2,h3,p{margin:0}h1{font-size:30px;letter-spacing:-.8px;line-height:1.2}h2{font-size:20px;letter-spacing:-.3px}h3{font-size:15px}p+p{margin-top:10px}small,.muted{color:var(--muted)}.shell{display:grid;grid-template-columns:252px minmax(0,1fr);min-height:100vh}.sidebar{background:#fff;border-right:1px solid var(--line);padding:28px 20px;position:sticky;top:0;height:100vh;overflow:auto}.brand{font-size:20px;font-weight:750;letter-spacing:-.5px;display:flex;align-items:center;gap:10px}.logo{width:30px;height:30px;border-radius:8px;background:var(--blue);color:#fff;display:grid;place-items:center;font-size:15px}.eyebrow{text-transform:uppercase;letter-spacing:1.4px;font-size:10px;font-weight:700;color:var(--muted)}.sidebar .eyebrow{margin:32px 8px 10px}.nav-link{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:11px 10px;color:var(--ink);border-radius:7px;font-size:12px;overflow-wrap:anywhere}.nav-link:hover{background:#f0f5fc;text-decoration:none}.nav-link span:first-child{min-width:0}.nav-finding{display:block;padding:5px 10px 5px 20px;font-size:11px;color:var(--muted);overflow-wrap:anywhere}.nav-count.zero{color:var(--muted);background:#edf1f6}.nav-count{font-weight:700;color:var(--red);background:#fff0f2;border-radius:5px;padding:1px 7px}.side-note{margin-top:28px;padding:14px;border:1px solid var(--line);border-radius:8px;font-size:12px;color:var(--muted)}main{padding:38px 42px 64px;max-width:1450px;width:100%;margin:auto}.title-row{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;margin-top:9px}.subtitle{margin-top:10px;color:var(--muted)}.meta{display:flex;flex-wrap:wrap;gap:8px 22px;font-size:12px;margin-top:18px;color:var(--muted)}.meta code{color:var(--ink)}.badge{display:inline-flex;align-items:center;border-radius:6px;padding:4px 9px;font-size:11px;font-weight:650;white-space:nowrap}.violation{color:var(--red);background:#fff0f2}.uncertain,.cited-badge{color:var(--amber);background:#fff4d9}.compliant{color:var(--green);background:#eaf7ef}.neutral{color:var(--muted);background:#edf1f6}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:28px 0}.metric{background:#fff;border:1px solid var(--line);border-radius:10px;padding:17px 20px}.metric strong{font-size:28px;display:block;line-height:1.25;margin-bottom:4px}.metric small{font-size:11px}.policy{margin-top:32px;scroll-margin-top:24px}.section-title{display:flex;gap:12px;align-items:center;margin-bottom:14px;flex-wrap:wrap}.section-title h2{overflow-wrap:anywhere}.card{background:#fff;border:1px solid var(--line);border-radius:10px;overflow:hidden;margin:14px 0;box-shadow:0 2px 4px #18253803}.finding-head{padding:22px 24px;border-bottom:1px solid var(--line)}.finding-head h3{font-size:17px;margin:12px 0 7px}.rule{color:var(--muted);font-size:13px}.finding-body{padding:20px 24px}.source-list{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0}.source-chip{background:#f1f4f8;border:1px solid var(--line);border-radius:5px;padding:4px 7px;font-size:11px}.feedback{padding:13px 16px;background:#f5f8fd;border-left:3px solid #8cb4e9;border-radius:0 6px 6px 0;font-size:13px;margin-bottom:16px}.feedback b{display:block;font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--muted);margin-bottom:4px}.localization{color:var(--muted);font-size:12px;margin:10px 0 14px}.diff{border:1px solid var(--line);border-radius:7px;overflow:hidden;margin:14px 0}.file-head{background:#f7f9fc;border-bottom:1px solid var(--line);padding:10px 14px;display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap}.file-head code{font-weight:600}.code-scroll{overflow-x:auto}.code-table{border-collapse:collapse;width:100%;font:12px/1.65 ui-monospace,SFMono-Regular,Consolas,monospace}.code-table td{vertical-align:top;padding:0 9px}.code-table th{text-align:left;padding:5px 9px;background:#f7f9fc;color:var(--muted);font:10px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;border-bottom:1px solid var(--line)}.code-table .number{width:44px;min-width:44px;text-align:right;color:#8a95a4;background:#f7f9fc;user-select:none;border-right:1px solid #edf0f5;font-size:11px}.code-table .code{white-space:pre;tab-size:4}.code-table .added{background:#edf9ef}.code-table .removed{background:#fff0f0}.code-table .hunk{background:#eaf2ff;color:#4773a5}.code-table .metadata{color:#7d8898;background:#fafbfd}.code-table .cited{box-shadow:inset 4px 0 #e8b53e;background:#fff4d9}.diff-foot{padding:8px 14px;border-top:1px solid var(--line);background:#fafbfd;color:var(--muted);font-size:11px}.legend{display:flex;gap:18px;font-size:11px;color:var(--muted);margin:14px 0}.dot{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px}.dot.add{background:#a8dfb0}.dot.remove{background:#f2b9bc}.dot.cite{background:#e8b53e}details{margin:14px 0;border:1px solid var(--line);border-radius:7px;background:#fff}summary{cursor:pointer;padding:11px 14px;font-size:12px;font-weight:600}details[open]>summary{border-bottom:1px solid var(--line);background:#f8fafd}.details-body{padding:14px;min-width:0}pre{white-space:pre;overflow:auto;font-size:11px;line-height:1.65;margin:0}.data-table{border-collapse:collapse;width:100%;font-size:12px}.data-table th{text-align:left;color:var(--muted);font-weight:600;background:#f7f9fc}.data-table td,.data-table th{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}.data-table tr:last-child td{border:0}.data-table code{font-size:10px}.empty{padding:20px 24px;color:var(--muted)}.notice{padding:15px 18px;border:1px solid #ecd9ac;background:#fffaf0;border-radius:8px;font-size:12px;margin-top:16px}.notice.error{border-color:#efc8ce;background:#fff5f6}.notice ul{margin-bottom:0;padding-left:18px}.footer{margin-top:32px;padding-top:18px;border-top:1px solid var(--line);font-size:11px;color:var(--muted)}.break{overflow-wrap:anywhere}.score{font-size:11px;color:var(--muted)}.finding-id{margin-top:15px;font-size:10px;color:var(--muted)}
@media(max-width:1050px){main{padding:28px 24px}.shell{grid-template-columns:210px minmax(0,1fr)}.sidebar{padding:24px 12px}.metrics{gap:9px}.metric{padding:14px}}
@media(max-width:720px){.shell{display:block}.sidebar{position:static;height:auto;border-right:0;border-bottom:1px solid var(--line);padding:16px 20px}.sidebar nav{display:flex;flex-wrap:wrap;margin-top:10px}.sidebar .eyebrow,.side-note{display:none}.nav-link{padding:6px 9px}.brand{font-size:17px}main{padding:24px 16px}.metrics{grid-template-columns:repeat(2,1fr);margin:20px 0}.title-row{display:block}.title-row>.badge{margin-top:12px}h1{font-size:25px}.finding-head,.finding-body{padding:18px 16px}.data-table td,.data-table th{padding:8px}.code-table{font-size:11px}}
@media print{.sidebar{display:none}.shell{display:block}main{padding:0;max-width:none}.card{break-inside:avoid;box-shadow:none}.code-scroll{overflow:visible}.code-table .code{white-space:pre-wrap}details{break-inside:avoid}}
"""


def esc(value: object) -> str:
    return html.escape(_safe(value), quote=True)


def badge(value: str) -> str:
    tone = value if value in {"violation", "uncertain", "compliant"} else "neutral"
    return f'<span class="badge {tone}">{esc(value.replace("_", " "))}</span>'


def _score(value: object) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.0%}"
    return "unavailable"


def _anchor_side(anchor: dict, comparison: dict) -> str | None:
    snapshot = anchor.get("snapshot")
    if (
        snapshot == "head"
        or anchor.get("commit") == comparison.get("source")
        and anchor.get("commit")
    ):
        return "new"
    if (
        snapshot == "base"
        or anchor.get("commit") == comparison.get("base")
        and anchor.get("commit")
    ):
        return "old"
    if snapshot == "target" and comparison.get("target") == comparison.get("base"):
        return "old"
    return None


def _diff_table(diff: dict, anchors: list[dict], comparison: dict) -> str:
    paths = diff.get("paths", [])
    relevant = [a for a in anchors if a.get("path") in paths]
    old = new = None
    rows = []
    highlights = 0
    for line in diff.get("content", "").split("\n"):
        hunk = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
        before = after = None
        if hunk:
            old, new = map(int, hunk.groups())
            kind = "hunk"
        elif line.startswith("diff --git "):
            old = new = None
            kind = "metadata"
        elif old is None and new is None:
            kind = (
                "added"
                if line.startswith("+") and not line.startswith("+++")
                else "removed"
                if line.startswith("-") and not line.startswith("---")
                else "metadata"
            )
        elif line.startswith("+"):
            kind, after = "added", new
            new += 1
        elif line.startswith("-"):
            kind, before = "removed", old
            old += 1
        elif line.startswith(" "):
            kind, before, after = "context", old, new
            old += 1
            new += 1
        else:
            kind = "metadata"
        cited = any(
            a.get("line") is not None
            and (
                _anchor_side(a, comparison) == "new"
                and a["line"] == after
                or _anchor_side(a, comparison) == "old"
                and a["line"] == before
            )
            for a in relevant
        )
        highlights += int(cited)
        css = kind + (" cited" if cited else "")
        title = ' title="Cited source line"' if cited else ""
        rows.append(
            f'<tr class="{css}"{title}><td class="number">{before if before is not None else ""}</td><td class="number">{after if after is not None else ""}</td><td class="code">{esc(line.expandtabs(4))}</td></tr>'
        )
    marker = (
        '<span class="badge cited-badge">Cited source scope</span>'
        if relevant
        else '<span class="badge neutral">Related change</span>'
    )
    note = (
        "Highlighted rows match Jev's selected source anchors; they are evidence references, not independently proven causal lines."
        if highlights
        else "Jev did not supply a matching precise line in this diff. Review the cited file/chunk and supporting evidence."
    )
    if diff.get("continuation_before") or diff.get("continuation_after"):
        note += " Partial file chunk; line numbers are shown only where a hunk header establishes them."
    return f'<div class="diff"><div class="file-head"><code>{esc(", ".join(paths) or "Changed source")}</code>{marker}</div><div class="code-scroll"><table class="code-table" aria-label="Changed diff; old and new line numbers"><thead><tr><th scope="col">Old</th><th scope="col">New</th><th scope="col">Changed source</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div><div class="diff-foot">{esc(note)}</div></div>'


def _evidence_diffs(evidence: dict) -> list[dict]:
    if evidence.get("type") == "PRIOR_FINDING":
        prior = evidence.get("finding", {})
        return prior.get("related_diff") or _evidence_diffs(prior.get("evidence", {}))
    if evidence.get("type") != "GET_DIFF_CHUNK":
        return []
    if isinstance(evidence.get("content"), dict):
        return [evidence["content"]]
    return [
        item["content"]
        for item in evidence.get("items", [])
        if isinstance(item, dict) and isinstance(item.get("content"), dict)
    ]


def _related(finding: dict, chunks: list[dict]) -> list[dict]:
    if finding.get("related_diff"):
        return finding["related_diff"]
    ids = {
        finding.get("chunk_id"),
        *(a.get("chunk_id") for a in finding.get("source_anchors", [])),
    }
    by_id = [c for c in chunks if c.get("id") in ids]
    if by_id:
        return by_id
    supported = _evidence_diffs(finding.get("evidence", {}))
    if supported:
        return supported
    paths = {a.get("path") for a in finding.get("source_anchors", [])}
    return [c for c in chunks if paths.intersection(c.get("paths", []))]


def _support(finding: dict) -> str:
    evidence = finding.get("evidence", {})
    if evidence.get("type") == "PRIOR_FINDING":
        return _support(evidence.get("finding", {}))
    parts = []
    for item in evidence.get("items", []):
        if isinstance(item, dict) and isinstance(item.get("content"), str):
            text = "\n".join(
                esc(line.expandtabs(4)) for line in item["content"].split("\n")
            )
            path = item.get("path", "Source excerpt")
            location = f" · line {item['line']}" if item.get("line") is not None else ""
            snapshot = item.get("snapshot", evidence.get("target", {}).get("snapshot"))
            label = f"{path}{location}" + (f" · {snapshot}" if snapshot else "")
            parts.append(f'<h3 class="break">{esc(label)}</h3><pre>{text}</pre>')
    if not parts:
        parts.append(
            "<pre>"
            + "\n".join(
                esc(line)
                for line in json.dumps(
                    evidence, ensure_ascii=False, indent=2, sort_keys=True
                ).split("\n")
            )
            + "</pre>"
        )
    return (
        "<details><summary>Supporting evidence · "
        + esc(finding.get("evidence_id", "not recorded"))
        + '</summary><div class="details-body">'
        + "".join(parts)
        + "</div></details>"
    )


def _decisions(unit: dict) -> str:
    rounds = unit.get("rounds", [])
    if not rounds:
        return ""
    parts = []
    for step in rounds:
        answers = step.get("answers", {})
        verdict = answers.get("disposition", {})
        raw = "\n".join(
            esc(line)
            for line in json.dumps(
                answers, ensure_ascii=False, indent=2, sort_keys=True
            ).split("\n")
        )
        mismatch = any(a.get("choice_probability_mismatch") for a in answers.values())
        note = " · declared-choice score disagreement" if mismatch else ""
        parts.append(
            f'<details><summary>Round {esc(step.get("round", "?"))} · {esc(verdict.get("choice", "unknown"))} · selected score {_score(verdict.get("selected_probability"))}{note}</summary><div class="details-body"><pre>{raw}</pre></div></details>'
        )
    return f'<details><summary>Evaluator decisions · {len(rounds)} rounds / {esc(unit.get("calls", "?"))} calls</summary><div class="details-body">{"".join(parts)}</div></details>'


def render_html(
    summary: dict, *, chunks: list[dict] | None = None, units: list[dict] | None = None
) -> str:
    """Render only preserved outputs. No source fetch, inference or external assets."""
    policies = [p for p in summary.get("policies", []) if isinstance(p, dict)]
    units_by_id = {u["id"]: u for u in units or []}
    finding_count = sum(len(p.get("findings", [])) for p in policies)
    uncertain = sum(p.get("outcome") == "uncertain" for p in policies)
    comparison = summary.get("comparison", {})
    nav, sections = [], []
    for index, policy in enumerate(policies):
        pid = policy.get("policy_id", "Unknown policy")
        outcome = policy.get("outcome", "unknown")
        findings = policy.get("findings", [])
        nav.append(
            f'<a class="nav-link" href="#policy-{index}"><span>{esc(pid)}</span><span class="nav-count{" zero" if not findings else ""}">{len(findings)}</span></a>'
        )
        cards = []
        for number, finding in enumerate(findings, 1):
            anchors = finding.get("source_anchors", [])
            first_path = next((a["path"] for a in anchors if a.get("path")), "Finding")
            nav.append(
                f'<a class="nav-finding" href="#finding-{index}-{number}" title="{esc(first_path)}">{number}. {esc(first_path.rsplit("/", 1)[-1])}</a>'
            )
            sources = "".join(
                f'<span class="source-chip"><code>{esc(_anchor(a))}</code></span>'
                for a in anchors
            )
            diffs = "".join(
                _diff_table(d, anchors, comparison)
                for d in _related(finding, chunks or [])
            )
            if not diffs:
                diffs = '<div class="notice">No changed diff was preserved for this finding. Inspect the supporting evidence below.</div>'
            fid = finding.get("finding_id", "Not recorded in this historical pack")
            guide = (
                f'<div class="feedback"><b>Policy-authored repair guidance</b>{esc(finding["repair_guidance"])}</div>'
                if finding.get("repair_guidance")
                else ""
            )
            scores = f"Declared violation score {_score(finding.get('selected_probability'))} · support score {_score(finding.get('support_probability'))}"
            cards.append(
                f'<article class="card" id="finding-{index}-{number}"><div class="finding-head">{badge("violation")} <span class="score">{esc(scores)}</span><h3>{esc(finding.get("message", "Policy violation finding"))}</h3><p class="rule">{esc(finding.get("policy_statement", pid))}</p><div class="source-list">{sources}</div><p class="localization">Localization: {esc(finding.get("localization", "not recorded"))} · Feedback is authored by the policy; Jev selected the verdict and support.</p></div><div class="finding-body">{guide}<div class="legend"><span><i class="dot add"></i>Added</span><span><i class="dot remove"></i>Removed</span><span><i class="dot cite"></i>Cited source line</span></div>{diffs}{_support(finding)}{_decisions(units_by_id.get(finding.get("unit_id"), {}))}<p class="finding-id">Finding ID <code>{esc(fid)}</code></p></div></article>'
            )
        diagnostics = [
            d
            for d in summary.get("diagnostics", [])
            if d.get("policy_id") == pid and d.get("outcome") == "uncertain"
        ]
        if outcome == "uncertain":
            cards.append(
                f'<div class="notice"><b>Assessment unresolved</b><p>Aggregate reason: {esc(policy.get("reason", "not recorded"))}. Uncertainty is not a violation or proof of compliance.</p>'
                + "".join(
                    f'<p class="break"><code>{esc(d.get("unit_id", ""))}</code> · {esc(d.get("reason", "unresolved"))} · {esc(d.get("calls", "?"))} calls</p>{_decisions(units_by_id.get(d.get("unit_id"), {}))}'
                    for d in diagnostics
                )
                + "</div>"
            )
        elif not findings:
            cards.append(
                f'<div class="card empty">No findings were emitted for this policy. Recorded outcome: <b>{esc(outcome)}</b>.</div>'
            )
        sections.append(
            f'<section class="policy" id="policy-{index}"><div class="section-title"><h2>{esc(pid)}</h2>{badge(outcome)}<span class="muted">action {esc(policy.get("action", "unknown"))}</span></div>{"".join(cards)}</section>'
        )
    coverage = summary.get("coverage", {})
    metrics = [
        (finding_count, "Emitted findings"),
        (uncertain, "Uncertain policies"),
        (len(policies), "Policy outcomes"),
        (coverage.get("calls_used", "—"), "Evaluator calls"),
    ]
    tiles = "".join(
        f'<div class="metric"><strong>{esc(value)}</strong><small>{label}</small></div>'
        for value, label in metrics
    )
    usage = "".join(f"<tr><td>{esc(line)}</td></tr>" for line in _usage_lines(summary))
    errors = (
        '<div class="notice error"><b>Operational errors</b><ul>'
        + "".join(f"<li>{esc(error)}</li>" for error in summary.get("errors", []))
        + "</ul></div>"
        if summary.get("errors")
        else ""
    )
    if not policies:
        sections.append(
            '<div class="card empty">No policy outcomes are available in this saved result.</div>'
        )
    repo = comparison.get("repo", "Saved Evidence Pack")
    source = comparison.get("source", "not recorded")
    base = comparison.get("base", "not recorded")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"><title>Jev CI · Findings review</title><style>{STYLE}</style></head>
<body><div class="shell"><aside class="sidebar"><a class="brand" href="#overview"><span class="logo">J</span>Jev CI</a><p class="muted" style="margin:10px 0 0;font-size:12px">Findings review</p><div class="eyebrow">Policy results</div><nav aria-label="Policy results">{"".join(nav)}</nav><div class="side-note">A finding is a model assessment. Inspect the change and source evidence before deciding to fix, dismiss or leave it unresolved.</div></aside>
<main id="overview"><div class="eyebrow">Saved evaluation / offline review</div><div class="title-row"><div><h1>Findings review</h1><p class="subtitle break">{esc(repo)}</p></div>{badge(summary.get("status", "unknown"))}</div><div class="meta"><span>Source <code>{esc(source)}</code></span><span>Base <code>{esc(base)}</code></span><span>Run <code>{esc(summary.get("run_id", "not recorded"))}</code></span></div><div class="metrics">{tiles}</div>{errors}{"".join(sections)}<section class="policy" id="run-details"><h2>Coverage &amp; reported usage</h2><div class="card"><table class="data-table"><tbody>{usage or "<tr><td>Usage was not recorded.</td></tr>"}</tbody></table></div></section><footer class="footer">Generated from preserved Jev CI outputs. No new evaluation or source retrieval. Declared option probabilities are scores, not a measured accuracy estimate. Review decisions do not modify the saved evaluator result.</footer></main></div></body></html>\n"""


def export_html(pack: Path, output: Path) -> None:
    """Generate a review copy without changing a checksummed Evidence Pack."""
    if output.resolve().is_relative_to(pack.resolve()):
        raise TraceError("HTML export must be outside the sealed Evidence Pack")
    try:
        summary = inspect_pack(pack)
        manifest_path = pack / "chunks" / "manifest.json"
        chunks = (
            json.loads(manifest_path.read_bytes()).get("chunks", [])
            if manifest_path.exists()
            else []
        )
        units = [
            json.loads(p.read_bytes())
            for p in sorted((pack / "evaluations").glob("*/result.json"))
        ]
        atomic_bytes(
            output, render_html(summary, chunks=chunks, units=units).encode("utf-8")
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise TraceError(f"cannot export HTML report: {exc}") from exc
