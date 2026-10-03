# HTML findings review

Status: implemented in0.5. Presentation only; policy/inference behavior remains protocol0.4.

New `evaluate` runs save `report.html` in the Evidence Pack before sealing its checksums. Open that file directly in a browser; all styling is embedded. No server, credential, script, font service or other network asset is required. The layout provides policy/finding navigation, count cards, outcome/action, policy statement, authored feedback, cited paths, colored unified diffs, supporting source evidence, recorded typed decision rounds and coverage/usage metadata.

## Offline export

```sh
jev-ci report --pack /path/to/saved-pack --output /tmp/review.html
```

The command reads `summary.json`, `chunks/manifest.json` when present, and saved unit results. Legacy findings without `related_diff` are matched to their saved chunk IDs or source paths; no new repository fact is fetched. Missing stable IDs or precise locations remain explicitly unavailable. Export must be outside the sealed pack and does not alter its manifest/checksums. It does not automatically perform protocol replay; use the existing `replay` command if that integrity check is needed.

## Location and score semantics

Green/red diff backgrounds mean added/removed source. Yellow rows indicate selected source-line anchors only when the path, line number and known head/base snapshot match. Commit IDs may establish the snapshot. Target-only or unknown snapshot anchors are not guessed into head/base lines. Chunk/file citations receive a source-scope badge; the report states when no precise matching line exists. Highlighted anchors are evidence references, not independent proof that the line caused a defect.

Unified hunk headers establish old/new line counters. A continuation chunk with no hunk header shows source with blank counters until a header establishes them. Metadata and missing diffs are displayed honestly. Reports preserve the exact recorded delete/add representation, including historical moves; they do not silently perform rename inference or reinterpret a finding as correct/incorrect.

Declared disposition/support probabilities are labelled selected scores, separately from native confidence. The report can expand each recorded decision round and its normalized answer fields, including probability disagreement telemetry when recorded. It does not generate explanations or infer missing probabilities. Unknown usage/cost and unresolved outcomes remain visible. Policy feedback is clearly attributed to authored templates.

## Artifact behavior

Source/model/control text is escaped as data. A restrictive Content Security Policy prevents active content; there is no JavaScript or external stylesheet. Navigation and evidence/round disclosure use native links and details elements. Long source lines scroll within their code frame.

Reviewing HTML does not dismiss a finding or modify an evaluator outcome. Campaign review records and fix/dismiss/unresolved decisions belong to the separate harness contract. Reports from real historical packs can be generated and inspected without paid calls; synthetic renderer fixtures must never be presented as fresh Jev observations.
