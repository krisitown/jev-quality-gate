# Public example policy pack

Reserved location for the basic YAML policies used by the experiment and intended for publication with jev-ci. The evaluator also accepts any other user-supplied policy folder.

The reviewed format is in [the policy design](../../docs/design/policy-schema.md). The CLI loads `.yaml` and `.yml` files only; this README is not a policy. The folder is currently empty of runnable policies and must fail validation as an empty pack.

After the application constitution is established, add approximately 5–8 bounded policies with explicit definitions/exceptions, document-binding instructions, authored repair guidance, and labelled calibration examples. Start with business-decision placement, abstraction reuse, semantic persistence leakage, responsibility drift, duplicated business rules, and semantic boundary bypass; merge overlapping questions where appropriate.

Publish the same files/version that the experiment pins. Keep corpus labels and treatment configuration in the research workspace, and distinguish illustrative drafts from calibrated profiles. No sample policy has been calibrated or published yet.
