from __future__ import annotations

import json
from html.parser import HTMLParser

import pytest

from jev_ci.cli import main
from jev_ci.errors import TraceError
from jev_ci.html_report import _diff_table, export_html, render_html
from jev_ci.trace import verify_pack
from test_protocol import response, run


class Rows(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.rows = []
        self.current = None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.current = {"attrs": dict(attrs), "text": ""}

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"] += data

    def handle_endtag(self, tag):
        if tag == "tr":
            self.rows.append(self.current)
            self.current = None


def test_diff_lines_highlight_only_matching_source_snapshot():
    diff = {
        "id": "d",
        "paths": ["Service.java"],
        "content": "@@ -10,2 +10,3 @@\n-old\n+new\n+extra\n context\n",
    }
    html = _diff_table(
        diff, [{"path": "Service.java", "line": 11, "snapshot": "head"}], {}
    )
    cited = [r for r in Rows(html).rows if "cited" in r["attrs"].get("class", "")]
    assert len(cited) == 1
    assert "+extra" in cited[0]["text"] and "11" in cited[0]["text"]
    html = _diff_table(
        diff, [{"path": "Service.java", "line": 10, "snapshot": "base"}], {}
    )
    cited = [r for r in Rows(html).rows if "cited" in r["attrs"].get("class", "")]
    assert len(cited) == 1 and "-old" in cited[0]["text"]
    html = _diff_table(diff, [{"path": "Service.java", "line": 10}], {})
    assert not any("cited" in r["attrs"].get("class", "") for r in Rows(html).rows)


def test_chunk_citation_and_continuation_never_invent_line_numbers():
    html = _diff_table(
        {
            "paths": ["Service.java"],
            "continuation_before": True,
            "content": "+continuation",
        },
        [{"path": "Service.java", "chunk_id": "d"}],
        {},
    )
    assert "Cited source scope" in html
    assert "did not supply a matching precise line" in html
    assert "Partial file chunk" in html
    assert '<td class="number"></td><td class="number"></td>' in html


def test_report_escapes_source_and_claims_without_scripts_or_external_assets():
    hostile = '</pre><script>alert(1)</script><img src="https://evil.invalid">\x1b'
    html = render_html(
        {
            "status": "completed_with_findings",
            "policies": [
                {
                    "policy_id": hostile,
                    "outcome": "violation",
                    "findings": [
                        {
                            "message": hostile,
                            "finding_id": hostile,
                            "source_anchors": [{"path": hostile}],
                            "related_diff": [
                                {"paths": [hostile], "content": "+" + hostile}
                            ],
                            "evidence": {
                                "type": "GET_FILE",
                                "items": [{"path": hostile, "content": hostile}],
                            },
                        }
                    ],
                }
            ],
        }
    )
    assert "<script>" not in html and '<img src="https:' not in html
    assert "&lt;script&gt;" in html and "\\x1b" in html
    assert "default-src 'none'" in html
    assert "<script" not in html and "<link" not in html


def test_new_pack_html_and_offline_export_preserve_integrity(
    project, tmp_path, monkeypatch, capsys
):
    def mock(request):
        body = json.loads(request.content)
        support = next(
            k for k in body["questions"]["support"]["criteria"] if k != "none"
        )
        return response(body, "violation", support)

    summary, pack = run(project, tmp_path, monkeypatch, mock)
    report = (pack / "report.html").read_text()
    assert "Findings review" in report and "Evaluator decisions" in report
    assert "x + 1" in report
    assert summary["policies"][0]["findings"][0]["finding_id"] in report
    assert "report.html" in json.loads((pack / "checksums.json").read_text())["files"]
    before = (pack / "checksums.json").read_bytes()
    output = tmp_path / "review.html"
    assert main(["report", "--pack", str(pack), "--output", str(output)]) == 0
    assert "HTML report:" in capsys.readouterr().out
    assert output.read_text() == report
    assert (pack / "checksums.json").read_bytes() == before
    assert verify_pack(pack)["status"] == "verified"
    with pytest.raises(TraceError, match="outside"):
        export_html(pack, pack / "extra.html")


def test_legacy_findings_use_saved_diff_manifest_and_uncertainty_stays_visible(
    tmp_path,
):
    pack = tmp_path / "pack"
    (pack / "chunks").mkdir(parents=True)
    (pack / "summary.json").write_text(
        json.dumps(
            {
                "status": "completed_with_findings",
                "policies": [
                    {
                        "policy_id": "duplication",
                        "outcome": "violation",
                        "findings": [
                            {
                                "chunk_id": "d",
                                "message": "Review duplicate rule.",
                                "source_anchors": [{"path": "A.java"}],
                            }
                        ],
                    },
                    {
                        "policy_id": "boundaries",
                        "outcome": "uncertain",
                        "reason": "unit_uncertainty",
                    },
                ],
                "diagnostics": [
                    {
                        "policy_id": "boundaries",
                        "outcome": "uncertain",
                        "reason": "context_budget_exceeded",
                        "calls": 3,
                    }
                ],
            }
        )
    )
    (pack / "chunks" / "manifest.json").write_text(
        json.dumps(
            {
                "chunks": [
                    {
                        "id": "d",
                        "paths": ["A.java"],
                        "content": "@@ -1 +1 @@\n-old\n+new\n",
                    }
                ]
            }
        )
    )
    output = tmp_path / "old-review.html"
    export_html(pack, output)
    report = output.read_text()
    assert "+new" in report
    assert "Not recorded in this historical pack" in report
    assert "context_budget_exceeded" in report and "Assessment unresolved" in report
