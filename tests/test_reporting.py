from jev_ci.reporting import render_markdown, render_text


def test_reports_include_findings_sources_uncertainty_and_usage():
    summary = {
        "status": "completed_with_findings",
        "exit_code": 0,
        "output": "/tmp/pack",
        "policies": [
            {
                "policy_id": "ownership",
                "outcome": "violation",
                "action": "warn",
                "findings": [
                    {
                        "message": "Move the decision into Service.",
                        "repair_guidance": "Keep ownership in Service.",
                        "source_anchors": [{"path": "src/Service.java", "line": 18}],
                    }
                ],
            },
            {
                "policy_id": "coverage",
                "outcome": "uncertain",
                "action": "report",
                "reason": "incomplete_coverage",
                "unvisited_chunks": ["chunk-2"],
                "unsupported_content": True,
                "incomplete_coverage": True,
            },
        ],
        "diagnostics": [
            {
                "policy_id": "coverage",
                "unit_id": "reconciliation-7",
                "unit_kind": "reconciliation",
                "chunk_id": None,
                "outcome": "uncertain",
                "reason": "candidate_gap",
                "calls": 1,
            }
        ],
        "coverage": {
            "chunk_status": "incomplete",
            "chunk_reason": "diff_limit_exceeded",
            "chunks": 2,
            "calls_used": 3,
            "calls_remaining": 7,
            "native_usage": {
                "input_tokens": 100,
                "output_tokens": 25,
                "cost_usd": "0.0042",
                "cost_reports": 2,
            },
        },
        "errors": [],
    }
    text = render_text(summary)
    markdown = render_markdown(summary)
    for expected in (
        "ownership: violation / action warn",
        "Keep ownership in Service.",
        "src/Service.java:18",
        "Unvisited chunks: chunk-2",
        "Unsupported content: yes",
        "Calls: used 3, remaining 7",
        "Reported USD cost: $0.0042 (2 reports)",
        "Evidence Pack: /tmp/pack",
        "coverage/reconciliation/reconciliation-7: uncertain; reason=candidate_gap; calls=1",
    ):
        assert expected in text
    assert "## Policies" in markdown
    assert "Reported tokens: input 100, output 25" in markdown
    assert "<code>src/Service.java:18</code>" in markdown
    assert "reason=candidate\\_gap" in markdown


def test_reports_escape_control_characters_and_markdown_injection():
    hostile_path = "src/bad\x1b[31m</code><script>[x](javascript:alert(1)).java"
    summary = {
        "status": "error\nforged\u202estatus",
        "output": "/tmp/pack\x1b[2J",
        "policies": [
            {
                "policy_id": "p",
                "outcome": "violation",
                "action": "warn",
                "findings": [
                    {
                        "message": "bad\x07claim [click](javascript:alert(1)) `code`",
                        "repair_guidance": "[open](javascript:alert(1))",
                        "source_anchors": [{"path": hostile_path}],
                    }
                ],
            }
        ],
        "errors": ["failure\r\nforged"],
        "diagnostics": [
            {
                "policy_id": "[link](javascript:alert(1))",
                "unit_id": "unit\x1b\u202e",
                "unit_kind": "chunk",
                "chunk_id": "chunk-1",
                "outcome": "uncertain",
                "reason": "[run](javascript:alert(1))\r\nforged",
                "calls": 2,
            }
        ],
    }
    text = render_text(summary)
    markdown = render_markdown(summary)
    assert "\x1b" not in text and "\x07" not in text and "\r" not in text
    assert "error\\x0aforged\\u202estatus" in text
    assert "src/bad\\x1b[31m</code><script>[x](javascript:alert(1)).java" in text
    assert "<script>" not in markdown
    assert "&lt;/code&gt;&lt;script&gt;" in markdown
    assert "[click](javascript:alert(1))" not in markdown
    assert r"\[click\]" in markdown
    assert "[open](javascript:alert(1))" not in markdown
    assert "[run](javascript:alert(1))" not in markdown
    assert "## Unit diagnostics" in markdown
    assert "\\u202e" in text and "\\u202e" in markdown
    assert r"\\x0d\\x0aforged" in markdown
