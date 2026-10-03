"""Human-readable summaries for command-line and saved-pack reports."""

from __future__ import annotations

import html
import unicodedata
from typing import Any


def _safe(value: Any) -> str:
    text = str(value)
    chars = []
    for char in text:
        if unicodedata.category(char) in {"Cc", "Cf"}:
            code = ord(char)
            chars.append(f"\\x{code:02x}" if code <= 0xFF else f"\\u{code:04x}")
        else:
            chars.append(char)
    return "".join(chars)


def _markdown(value: Any) -> str:
    text = html.escape(_safe(value))
    for marker in (
        "\\",
        "`",
        "*",
        "_",
        "{",
        "}",
        "[",
        "]",
        "(",
        ")",
        "#",
        "+",
        "-",
        ".",
        "!",
        ">",
        "|",
    ):
        text = text.replace(marker, "\\" + marker)
    return text


def _html_code(value: Any) -> str:
    text = html.escape(_safe(value))
    for marker, entity in (
        ("[", "&#91;"),
        ("]", "&#93;"),
        ("(", "&#40;"),
        (")", "&#41;"),
    ):
        text = text.replace(marker, entity)
    return f"<code>{text}</code>"


def _anchor(anchor: dict) -> str:
    path = _safe(anchor.get("path", "(unknown path)"))
    location = f":{anchor['line']}" if anchor.get("line") is not None else ""
    if anchor.get("raw_range"):
        location += f" (raw range {anchor['raw_range'][0]}–{anchor['raw_range'][1]})"
    return path + location


def _usage_lines(summary: dict) -> list[str]:
    coverage = summary.get("coverage") or {}
    usage = coverage.get("native_usage") or {}
    calls = []
    if coverage.get("calls_used") is not None:
        calls.append(f"used {coverage['calls_used']}")
    if coverage.get("calls_remaining") is not None:
        calls.append(f"remaining {coverage['calls_remaining']}")
    lines = []
    if calls:
        lines.append("Calls: " + ", ".join(calls))
    if coverage:
        lines.append(
            "Coverage: "
            + ", ".join(
                f"{name}={_safe(coverage[name])}"
                for name in ("chunk_status", "chunk_reason", "chunks")
                if coverage.get(name) is not None
            )
        )
    token_parts = []
    for key, label in (("input_tokens", "input"), ("output_tokens", "output")):
        if usage.get(key) is not None:
            token_parts.append(f"{label} {usage[key]}")
    if token_parts:
        lines.append("Reported tokens: " + ", ".join(token_parts))
    if usage.get("cost_reports"):
        cost = usage.get("cost_usd")
        if cost is not None:
            lines.append(
                f"Reported USD cost: ${_safe(cost)} ({usage['cost_reports']} reports)"
            )
    elif usage.get("cost_usd") is not None:
        lines.append(f"Reported USD cost: ${_safe(usage['cost_usd'])}")
    return lines


def _policy_lines(policy: dict) -> list[str]:
    policy_id = _safe(policy.get("policy_id", "(unknown policy)"))
    lines = [
        f"  {policy_id}: {_safe(policy.get('outcome', 'unknown'))} / action {_safe(policy.get('action', 'unknown'))}"
    ]
    findings = policy.get("findings") or []
    for finding in findings:
        message = _safe(finding.get("message", "Violation finding"))
        lines.append(f"    Finding: {message}")
        if finding.get("finding_id"):
            lines.append(f"    Finding ID: {_safe(finding['finding_id'])}")
        if finding.get("policy_statement"):
            lines.append(f"    Rule: {_safe(finding['policy_statement'])}")
        guidance = finding.get("repair_guidance")
        if guidance:
            lines.append(f"    Feedback: {_safe(guidance)}")
        for anchor in finding.get("source_anchors") or []:
            lines.append(f"    Source: {_anchor(anchor)}")
        if finding.get("evidence_id"):
            lines.append(f"    Supporting evidence: {_safe(finding['evidence_id'])}")
        for diff in finding.get("related_diff") or []:
            lines.append("    Related changed diff (bounded scope):")
            lines.extend("      " + _safe(line) for line in diff["content"].split("\n"))
    if policy.get("outcome") == "uncertain":
        if policy.get("reason"):
            lines.append(f"    Reason: {_safe(policy['reason'])}")
        if policy.get("unvisited_chunks"):
            lines.append(
                "    Unvisited chunks: "
                + ", ".join(_safe(x) for x in policy["unvisited_chunks"])
            )
        if policy.get("unsupported_content"):
            lines.append("    Unsupported content: yes")
        if policy.get("incomplete_coverage"):
            lines.append("    Incomplete coverage: yes")
    return lines


def _diagnostic_lines(diagnostics: list[dict]) -> list[str]:
    lines = ["Unit diagnostics:"]
    for item in diagnostics:
        identity = "/".join(
            _safe(value)
            for value in (
                item.get("policy_id"),
                item.get("unit_kind"),
                item.get("unit_id"),
            )
            if value is not None
        )
        detail = f"{identity}: {_safe(item.get('outcome', 'unknown'))}"
        if item.get("reason"):
            detail += f"; reason={_safe(item['reason'])}"
        if item.get("chunk_id"):
            detail += f"; chunk={_safe(item['chunk_id'])}"
        if item.get("calls") is not None:
            detail += f"; calls={_safe(item['calls'])}"
        lines.append(f"  {detail}")
    return lines


def render_text(summary: dict) -> str:
    """Render a concise terminal-safe summary without changing its source data."""
    lines = [f"jev-ci: {_safe(summary.get('status', 'unknown'))}"]
    if summary.get("exit_code") is not None:
        lines.append(f"Exit code: {_safe(summary['exit_code'])}")
    if summary.get("output"):
        lines.append(f"Evidence Pack: {_safe(summary['output'])}")
    policies = summary.get("policies") or []
    if policies:
        lines.append("Policies:")
        if isinstance(policies[0], dict):
            for policy in policies:
                lines.extend(_policy_lines(policy))
        else:
            lines.extend(f"  {_safe(policy)}" for policy in policies)
    diagnostics = summary.get("diagnostics") or []
    if diagnostics:
        lines.extend(_diagnostic_lines(diagnostics))
    lines.extend(_usage_lines(summary))
    for error in summary.get("errors") or []:
        lines.append(f"Error: {_safe(error)}")
    return "\n".join(lines)


def render_markdown(summary: dict) -> str:
    """Render a Markdown report with escaped text and source paths."""
    lines = [f"# Jev CI: {_markdown(summary.get('status', 'unknown'))}"]
    if summary.get("exit_code") is not None:
        lines.append(f"\nExit code: **{_markdown(summary['exit_code'])}**")
    if summary.get("output"):
        lines.append(f"\nEvidence Pack: {_html_code(summary['output'])}")
    policies = summary.get("policies") or []
    if policies:
        lines.append("\n## Policies")
        for policy in policies:
            if not isinstance(policy, dict):
                lines.append(f"\n- {_markdown(policy)}")
                continue
            lines.append(
                f"\n### {_markdown(policy.get('policy_id', '(unknown policy)'))}"
                f" — {_markdown(policy.get('outcome', 'unknown'))}; action {_markdown(policy.get('action', 'unknown'))}"
            )
            for finding in policy.get("findings") or []:
                lines.append(
                    f"\n- **Finding:** {_markdown(finding.get('message', 'Violation finding'))}"
                )
                if finding.get("finding_id"):
                    lines.append(
                        f"  - **Finding ID:** {_html_code(finding['finding_id'])}"
                    )
                if finding.get("policy_statement"):
                    lines.append(
                        f"  - **Rule:** {_markdown(finding['policy_statement'])}"
                    )
                if finding.get("repair_guidance"):
                    lines.append(
                        f"  - **Feedback:** {_markdown(finding['repair_guidance'])}"
                    )
                for anchor in finding.get("source_anchors") or []:
                    lines.append(f"  - **Source:** {_html_code(_anchor(anchor))}")
                if finding.get("evidence_id"):
                    lines.append(
                        f"  - **Supporting evidence:** {_html_code(finding['evidence_id'])}"
                    )
                for diff in finding.get("related_diff") or []:
                    lines.append("\n**Related changed diff (bounded scope):**")
                    content = "\n".join(
                        _safe(line) for line in diff["content"].split("\n")
                    )
                    lines.append("\n<pre>" + html.escape(content) + "</pre>\n")
            if policy.get("outcome") == "uncertain":
                details = []
                if policy.get("reason"):
                    details.append(f"reason: {_safe(policy['reason'])}")
                if policy.get("unvisited_chunks"):
                    details.append(
                        "unvisited: "
                        + ", ".join(_safe(x) for x in policy["unvisited_chunks"])
                    )
                if policy.get("unsupported_content"):
                    details.append("unsupported content")
                if policy.get("incomplete_coverage"):
                    details.append("incomplete coverage")
                if details:
                    lines.append("\n- **Uncertain:** " + _markdown("; ".join(details)))
    diagnostics = summary.get("diagnostics") or []
    if diagnostics:
        lines.append("\n## Unit diagnostics")
        for item in diagnostics:
            identity = " / ".join(
                _markdown(value)
                for value in (
                    item.get("policy_id"),
                    item.get("unit_kind"),
                    item.get("unit_id"),
                )
                if value is not None
            )
            detail = f"{identity}: {_markdown(item.get('outcome', 'unknown'))}"
            if item.get("reason"):
                detail += f"; reason={_markdown(item['reason'])}"
            if item.get("chunk_id"):
                detail += f"; chunk={_markdown(item['chunk_id'])}"
            if item.get("calls") is not None:
                detail += f"; calls={_markdown(item['calls'])}"
            lines.append(f"\n- {detail}")
    usage = _usage_lines(summary)
    if usage:
        lines.append("\n## Coverage and usage")
        lines.extend(f"\n- {_markdown(line)}" for line in usage)
    if summary.get("errors"):
        lines.append("\n## Errors")
        lines.extend(f"\n- {_markdown(error)}" for error in summary["errors"])
    return "\n".join(lines) + "\n"
