# Orchestrate skill checkpoint — November 10, 2026

## Scope and evidence

This note summarizes the user's CLI output and exported draft-preview model nodes
reviewed during the session. It is not a live service audit or an end-to-end GIS test.
No classification-accuracy estimate or full-regression result was produced here.

## Verified operations

- Cloud Shell Python: 3.12.15; Orchestrate ADK: 2.19.1.
- CLI installed in the user environment and invoked as `~/.local/bin/orchestrate`.
  The attempted virtual-environment installation instead used user site-packages;
  isolated CLI packaging remains a separate housekeeping issue.
- Existing hosted MapCP agent accessed and exported; not a newly created agent.
- Runtime skill `candidate-cover-mapping-review` imported, attached, and updated.
- Explicit loading succeeded. After a targeted main-instruction change, an ordinary
  workflow request also selected the skill in a tested draft conversation.
- Post-load model input contained the full skill and the revised
  `Resume from an existing collection` subsection.
- Model reported in the trace: `openai/gpt-oss-120b`.

## Test prompt

> Help me resume candidate cover-type mapping from an existing LFPS v2 collection
> manifest. Before any processing, explain what information and prerequisites you
> need. I have not supplied the manifest filename yet. Do not run MapCP inspection,
> mapping, acquisition, generalization, or export tools, and do not invent filenames.

## Observed result after the skill update

| Criterion | Result |
|---|---|
| Automatic skill selection and successful loading | Passed in the reviewed run |
| Revised skill body present in model input | Passed |
| Ask for exact collection manifest | Passed |
| Identify inspection prerequisite | Improved; response required inspection |
| No invented manifest filename | Failed |
| Restrict initial response to immediate missing inputs | Failed; later export requirements included |
| Avoid premature mapping approval request | Failed |
| GIS execution, delivery, and professional review | Not tested |

## Disposition

Skill installation, attachment, selection, and instruction injection worked.
Procedural compliance remained incomplete. Tuning was paused at the user's request;
no model comparison was performed because the user reported only one available model.
Do not describe the skill update as having resolved agent reliability.

## Backup and restoration requirements

Preserve the fresh post-instruction-change agent export and revised skill separately
from the original before-change backup. Restore skill registration and verify agent
bindings in the intended environment. Tool/knowledge dependencies and credentials
require separate approved setup; agent-only YAML is not a complete service backup.
No live deployment or end-to-end processing was validated by this checkpoint.

Use sanitized summaries instead of raw trace exports in Git. Keep credentials,
contact email, signed URLs, and restricted data out of the repository. Review
configuration/tool bindings before publishing.
