# Cover-Type Onboarding and Candidate Mapping Workflow — Design Plan

**Application:** Tribal Forest MapCP
**Status:** Design plan — partially approved. Approved decisions recorded in
section 13 and throughout. Unresolved items reduced per session decisions.
**Authority:** `docs/project-specification.md`, `AGENTS.md`,
`docs/mescalero-cover-type-definitions.md`.
**Last updated:** Session approval of EVC/EVH roles, disturbance treatment,
riparian strategy, and onboarding architecture.

---

## 1. Objective and scope

**Objective:**  
Design the workflow that allows a new Tribal or BIA forestry user to begin a
MapCP project, choose or provide the cover-type system used for candidate
cover-type mapping, receive targeted review questions, and produce an approved
versioned cover-scheme configuration and EVT crosswalk — before any raster
classification runs.

**Central product requirement:**  
Actual preliminary candidate cover-type mapping, not forest/nonforest only.
Candidate forest land is a required companion output, not a substitute.

**Scope:**  
- User-path design for all three input modes (local guide, no guide, plain
  language).  
- Conversation or form flow design.  
- Schema designs for cover-scheme configuration, EVT crosswalk, and
  evidence/rule records.  
- Storage, versioning, and approval record design.  
- Tool boundary definition (internal helpers vs. public MCP outcome tools).  
- Implementation slice sequence.  
- Acceptance criteria for the first slice.  
- Unresolved forestry decisions.  

**Not in scope of this plan:**  
- Raster processing, polygon generalization, ArcGIS package, stand
  delineation, or accessibility screening.  
- Changes to existing boundary and LFPS tools.

---

## 2. Existing behavior to preserve

**Verified** — The following tools exist and pass tests in the current
repository (per `tests/test_server.py` and repository inspection):

- `find_bia_land_area_candidates`
- `download_bia_land_area`
- `find_census_reservation_reference`
- `inspect_mapping_inputs` (boundary geometry check and GeoPackage output)
- `inspect_naip_coverage`
- `download_naip_review_sample`
- `inspect_vegetation_inputs` (LFPS metadata inspection; not LFPS v2 submit)
- `prepare_landfire_v2_sample_request`
- `recover_landfire_v2_job_manifest`
- `check_landfire_v2_sample_job`
- `collect_landfire_v2_sample_result` (ZIP collection and raster inspection)
- `MappingRequest` schema

These tools must not be modified as part of this plan unless a separate
approval is given.

**Verified** — `requested_cover_scheme` in `MappingRequest` currently accepts
only `"broad_candidate_cover_types_v1"` as a Literal. This will need to evolve
to reference an approved saved scheme configuration, but that change is part
of a later slice.

---

## 3. User paths and conversation flow

### 3.1 Three supported entry paths

**Path A — User supplies a local guide.**  
The user has a cover-type guide, inventory manual, Forest Management Plan
table, spreadsheet, PDF, Word document, or pasted table.

**Path B — User has no local guide.**  
The user needs a public regional starter scheme derived from public LANDFIRE
EVT/EVT-NVC, USNVC, and FIA context for their region and ecology.

**Path C — User describes desired distinctions in plain language.**  
The user says something like "We need ponderosa pine, mixed conifer,
pinyon-juniper, oak woodland, grassland, riparian forest, and recent
disturbance."

All three paths converge on the same review, approval, and versioned-save
steps before mapping begins.

### 3.2 Full conversation flow

```
Step 1  Identify entry path
        ↓
Step 2  Extract or draft candidate cover-class table
        ↓
Step 3  Ask targeted forestry follow-up questions
        ↓
Step 4  Flag ambiguities and unsupported criteria
        ↓
Step 5  Present reviewable approval table
        ↓
Step 6  User approves, revises, or rejects
        ↓ (approval required)
Step 7  Save versioned cover-scheme configuration
        ↓
Step 8  Draft EVT-to-candidate-class crosswalk from actual source codes
        ↓
Step 9  User approves crosswalk
        ↓ (approval required)
Step 10 Save versioned crosswalk
        ↓
Step 11 Define EVC/EVH evidence roles and disturbance/NoData rules
        ↓
Step 12 User approves rules
        ↓ (approval required)
Step 13 Save versioned rule record
        ↓
Step 14 Mapping tools consume saved, approved, versioned files only
```

No mapping step begins until steps 6, 9, and 12 have produced user-approved
saved files.

---

## 4. Decision points and exact user questions

### 4.1 Path identification questions (Step 1)

**[Proposed]**

1. "Do you have an existing local cover-type guide, inventory manual, Forest
   Management Plan table, spreadsheet, PDF, or similar document? If yes,
   please paste or describe the cover types and their local definitions."

2. If no: "Would you like MapCP to propose a public regional starter scheme
   based on LANDFIRE EVT/EVT-NVC vegetation types common to your project
   area? This scheme will be labeled preliminary and editable — it is not a
   substitute for a Tribe- or program-approved classification."

3. If plain-language: "You described the following vegetation distinctions:
   [list]. MapCP will attempt to match these to a draft candidate class
   table. Please be aware that some distinctions — such as species
   proportions, crown-cover percentages, overstory/understory composition,
   or site productivity — cannot be directly read from current public
   sources. MapCP will flag these limitations explicitly."

### 4.2 Cover-class review questions (Step 3)

**[Proposed]** — These questions apply to all three paths:

1. "Which of these candidate classes are candidate forest land? Should
   woodland classes be candidate forest land? Should nonstocked classes
   (areas with fewer than 10% crown cover) that had a prior forest type be
   candidate forest land?"

2. "Are there classes that require a minimum crown-cover threshold? What
   threshold applies, and does MapCP have access to a source that can
   approximate it?"

3. "Are any class definitions based on species-specific crown-cover
   percentages, measured basal area, overstory/understory composition, or
   site productivity? If yes, note that MapCP cannot directly measure these
   from current public LANDFIRE sources. MapCP will flag these cells as
   requiring professional review."

4. "How should MapCP treat areas where the source data does not support a
   confident class assignment: preserve as 'candidate_uncertain', assign to
   the most likely adjacent class, or flag for field review?"

5. "How should disturbed forest land be treated? Should recent disturbance
   (fire, harvest, insects) result in an 'NT' or 'NW' class, a disturbance
   overlay flag, or a separate disturbance-review class?"

6. "What minimum mapping unit should MapCP use for generalized review
   polygons? Should any specific class types (riparian, nonstocked, NoData)
   always be preserved regardless of size?"

7. "Should the first mapping pass assign one primary candidate class only,
   or attempt dual typing for complex stands?"

8. "Is there a public or program-approved FIA evaluation geography and year
   range that should inform ecological plausibility checks for this project?
   Note: public FIA coordinates are spatially altered and cannot be used as
   exact pixel or stand labels."

### 4.3 Approval table presentation (Step 5)

**[Proposed]** — After steps 2–4, MapCP presents:

```
Proposed cover-scheme approval table

| Code | Name | Local definition summary | Candidate forest land |
|      |      | LANDFIRE support note    | Source limitation flag |
```

Each row includes:
- The proposed candidate code and name.
- A plain-language summary of the local definition.
- A note on which EVT codes, EVT-NVC group, or source evidence MapCP
  proposes to use.
- A source limitation flag: "species composition not directly measurable,"
  "crown-cover percentage not directly measurable," "requires EVC/EVH
  support," "no direct public source support — retain as uncertain," or
  similar.
- The proposed candidate forest-land designation (Yes/No/Conditional).

The user is asked: "Do you approve this cover-scheme table for the
[project name] pilot? Please indicate any rows to revise or reject before
MapCP saves the approved configuration and proceeds to crosswalk drafting."

**[Proposed]** — MapCP must never proceed to crosswalk drafting or save a
scheme without an explicit "yes" or revised approval from the user.

---

## 5. Proposed cover-scheme configuration schema

**[Proposed]** — File location: `project_data/cover_schemes/<slug>_cover_scheme_<version>.json`

### 5.1 Top-level fields

```json
{
  "schema_type": "cover_scheme_configuration",
  "scheme_id": "string — short unique identifier, e.g. 'mescalero_v1'",
  "scheme_version": "string — semver or date-based, e.g. '1.0.0' or '2026-01'",
  "scheme_label": "string — display name, e.g. 'Mescalero Pilot Cover Scheme v1'",
  "source_authority": "string — 'local_approved', 'public_starter_proposed', or 'plain_language_draft'",
  "source_document_reference": "string or null — filename, title, or 'none'",
  "project_scope": "string — 'mescalero_pilot' or another identifier",
  "geographic_applicability": "string — 'Mescalero Apache Reservation only' or similar",
  "approved_by": "string — 'user' after explicit approval",
  "approved_at_utc": "string — ISO-8601 timestamp",
  "approval_record": "string — filename of approval record JSON",
  "one_primary_class_only": "boolean",
  "forest_land_policy_notes": "string",
  "nonstocked_policy": "string",
  "woodland_is_forest_land": "boolean",
  "classes": [],
  "limitations": [],
  "change_control": "string — 'Do not modify without user approval and new version'"
}
```

### 5.2 Class record fields

Each element of `"classes"`:

```json
{
  "candidate_code": "string — e.g. 'P', 'PJ', 'G', 'RIP_WOODY'",
  "candidate_name": "string — e.g. 'Ponderosa Pine'",
  "first_pass_candidate_label": "string — the complete initial output label, e.g. 'candidate_P', 'candidate_RIP_WOODY'",
  "candidate_forest_land": "boolean or null — null for RIP_UNCERTAIN and other unknown-forest-land classes",
  "structure_group": "string — 'timberland', 'woodland', 'nonforest', 'nonstocked_timberland', 'nonstocked_woodland', 'riparian_woody_forest', 'riparian_nonforest', 'riparian_uncertain'",
  "local_definition_summary": "string",
  "source_measurability": "string — 'not_directly_measurable', 'approximate_via_evt', 'approximate_via_evt_evc_evh'",
  "first_pass_assignment_status": "string — 'assignable' | 'consolidated_to_broader_class' | 'not_assignable'",
  "first_pass_output_code": "string or null — required (non-null) when first_pass_assignment_status is 'consolidated_to_broader_class'; null otherwise",
  "review_flags_required": ["list of required review flag strings"],
  "protected_from_generalization_merge": "boolean",
  "notes": "string or null"
}
```

Notes on `candidate_forest_land`:
- `true` for all timberland, woodland, nonstocked forest, and riparian woody classes.
- `false` for nonforest classes and `RIP_NONFOREST`.
- `null` for `RIP_UNCERTAIN` and any class where forest-land status cannot be determined
  from the approved source. `null` is not the same as `false`.

Notes on `first_pass_assignment_status`:
- `"assignable"`: this class may be output in the first baseline pass if the
  approved crosswalk supports it. Includes all timberland, woodland, nonforest
  (excluding R), nonstocked, and the three consolidated RIP_* classes.
- `"consolidated_to_broader_class"`: this is a local target code that is not
  individually assigned in the first pass. The crosswalk routes these EVT codes
  to the class identified by `first_pass_output_code`. Applies to CO, RO, SC,
  WI, B (→ RIP_WOODY) and R (→ RIP_NONFOREST).
- `"not_assignable"`: reserved for future approved use. Never output in the
  first pass. Requires `first_pass_output_code = null`,
  `candidate_forest_land = null`, and a non-empty `review_flags_required`
  explaining why assignment is unavailable.

Note on `first_pass_candidate_label`:
- Stores the **complete** initial output label string, not a prefix.
- Examples: `"candidate_P"`, `"candidate_PJ"`, `"candidate_RIP_WOODY"`,
  `"candidate_NT"`, `"candidate_G"`.
- For `consolidated_to_broader_class` entries, must equal the target record's
  `first_pass_candidate_label` (enforced by cross-record validator on
  `CoverSchemeConfig`).

Note on `candidate_forest_land` for riparian records:
- CO, RO, SC, WI, B: `true` (woodland/forest; consolidated to RIP_WOODY)
- R: `false` (nonforested riparian; consolidated to RIP_NONFOREST)
- RIP_WOODY: `true`
- RIP_NONFOREST: `false`
- RIP_UNCERTAIN: `null` (unknown; `null` is not the same as `false`)

Cross-record validation on `CoverSchemeConfig` (enforced as `@model_validator`):
1. Every `first_pass_output_code` in a `consolidated_to_broader_class` record
   must match the `candidate_code` of exactly one other record in `classes`.
2. The referenced target must have `first_pass_assignment_status == "assignable"`.
   Chains and cycles are rejected.
3. The consolidated record's `first_pass_candidate_label` must equal the
   target's `first_pass_candidate_label`.
4. The consolidated record's `candidate_forest_land` must equal the target's
   `candidate_forest_land` (`null` matches only `null`).

### 5.3 Limitation and change-control fields

```json
{
  "limitations": [
    "Species-composition and crown-cover criteria cannot be directly measured from LANDFIRE EVT, EVC, or EVH.",
    "Initial mapping assigns one primary candidate cover type only.",
    "Candidate outputs are preliminary and require professional forestry review.",
    "..."
  ]
}
```

---

## 6. Proposed EVT-to-candidate-class crosswalk schema

**[Proposed]** — File location: `project_data/crosswalks/<slug>_evt_crosswalk_<version>.json`

### 6.1 Top-level fields

```json
{
  "schema_type": "evt_crosswalk",
  "crosswalk_version": "string",
  "scheme_id": "string — must match cover_scheme_configuration.scheme_id",
  "scheme_version": "string — must match cover_scheme_configuration.scheme_version",
  "source_product": "string — e.g. 'LF2025_EVT_CONUS'",
  "source_version": "string — from LFPS delivery manifest",
  "source_metadata_file": "string — XML filename",
  "evt_nvc_product_available": "boolean — false unless a separately collected and validated EVT-NVC source has been approved",
  "evt_nvc_product_reference": "string or null — null unless explicitly approved",
  "approved_by": "string — 'user' after explicit approval",
  "approved_at_utc": "string",
  "approval_record": "string",
  "crosswalk_entries": [],
  "unknown_code_treatment": "string — 'candidate_uncertain_or_nodata'",
  "nodata_treatment": "string — 'candidate_uncertain_or_nodata'",
  "limitations": []
}
```

### 6.2 Crosswalk entry fields

Each element of `"crosswalk_entries"`:

```json
{
  "evt_code": "integer — LANDFIRE EVT value",
  "evt_name": "string — from source XML or value attribute table",
  "evt_nvc_group": "string or null — MUST be null unless a separately collected and validated EVT-NVC source is explicitly approved; do not populate from LF2025 EVT XML alone",
  "candidate_code": "string — target candidate class code",
  "candidate_label": "string — e.g. 'candidate_P'",
  "candidate_forest_land": "boolean",
  "crosswalk_basis": "string — brief rationale using actual LF2025 EVT code and metadata only; do not reference EVT-NVC alliance unless verified available",
  "evc_evh_role": "string — 'conflict_check_and_supporting_evidence' (first pass) | 'required_threshold' (future approved only)",
  "evc_threshold": "number or null — null in first pass; thresholds introduced only via future approved versioned rule",
  "evh_threshold": "number or null — null in first pass; thresholds introduced only via future approved versioned rule",
  "source_limitation_flags": ["list of applicable limitation flags"],
  "review_flags": ["list of required output review flags"],
  "notes": "string or null"
}
```

### 6.3 Limitation examples for crosswalk entries

```
species_composition_not_directly_measured
crown_cover_percentage_not_directly_measured
overstory_understory_not_modeled
evt_structure_conflict
possible_disturbance_or_source_date_mismatch
candidate_nonstocked_forest_land_review
nodata_or_unknown_coverage
source_evt_code_unknown
riparian_feature_preserved
riparian_subtype_not_resolved
disturbance_not_evaluated
professional_forestry_review_required
```

---

## 7. Proposed evidence and rule schema

**[Proposed]** — File location: `project_data/mapping_rules/<slug>_mapping_rules_<version>.json`

```json
{
  "schema_type": "mapping_rules",
  "rules_version": "string",
  "scheme_id": "string",
  "scheme_version": "string",
  "crosswalk_version": "string",
  "approved_by": "string",
  "approved_at_utc": "string",
  "approval_record": "string",
  "evc_role": "string — approved values: 'conflict_check_and_supporting_evidence' | 'required_threshold' | 'not_used'",
  "evh_role": "string — approved values: 'conflict_check_and_supporting_evidence' | 'required_threshold' | 'not_used'",
  "evc_canopy_cover_threshold": "number or null — MUST be null in first Mescalero pass; set only via future approved rule version",
  "evh_height_threshold": "number or null — MUST be null in first Mescalero pass; set only via future approved rule version",
  "evc_conflict_produces_hard_nonforest": false,
  "evh_conflict_produces_hard_nonforest": false,
  "evc_conflict_review_flags": ["evt_structure_conflict", "possible_disturbance_or_source_date_mismatch", "candidate_nonstocked_forest_land_review"],
  "evh_conflict_review_flags": ["evt_structure_conflict", "possible_disturbance_or_source_date_mismatch", "professional_forestry_review_required"],
  "retain_evt_evc_evh_values_in_output": true,
  "disturbance_product_used": false,
  "disturbance_treatment": "not_evaluated",
  "post_disturbance_history_inferred": false,
  "nodata_treatment": "string — 'candidate_uncertain_or_nodata'",
  "unknown_code_treatment": "string — 'candidate_uncertain_or_nodata'",
  "conflict_treatment": "string — 'preserve_mixed_flag'",
  "minimum_mapping_unit_m2": "number — e.g. 10000",
  "protected_small_patch_classes": ["list of candidate codes always preserved"],
  "merge_rules": {
    "permitted_same_class_merge": "boolean",
    "permitted_compatible_class_merge": "boolean",
    "forbidden_merges": ["list of forbidden pairs, e.g. 'forest+nonforest'"]
  },
  "first_pass_one_class_only": "boolean",
  "overstory_understory_not_modeled_flag_required": "boolean",
  "limitations": [],
  "notes": "string or null"
}
```

---

## 8. Generic starter schemes vs. locally approved schemes

**[Proposed]**

| Property | Generic public starter | Locally approved scheme |
|---|---|---|
| Basis | LANDFIRE EVT-NVC groupings, USNVC alliances, FIA forest-type groups | User-supplied local guide, inventory manual, FMP table |
| Authority | Preliminary, editable, not Tribe- or program-approved | Explicitly approved by user before use |
| Label in outputs | `preliminary_starter_` prefix | `candidate_` prefix |
| Forest-land policy | Must be confirmed by user before use | Confirmed and recorded in scheme config |
| Species-composition criteria | Approximated from EVT-NVC groupings only | Recorded as user-defined; flagged where not measurable from public source |
| Change control | May be revised freely before approval | Version-controlled; requires explicit approval for changes |
| When to use | User has no local guide (Path B) or is exploring options | User has approved their local definitions |

**[Proposed]** — A public starter scheme must always be labeled preliminary
and must not be used for mapping until the user reviews and explicitly approves
it. Approval converts it from a starter to a locally approved scheme.

**[Proposed]** — The Mescalero pilot scheme is a locally approved scheme, not
a generic public starter. It must not be used as a default for any other Tribe,
BIA program, project area, or geography.

---

## 9. Approval, provenance, and version storage

**[Approved]** — Controlled project configuration files (cover-scheme
configs, EVT crosswalks, mapping-rules records, and approval records)
are stored in a `project_data/` directory, not in `outputs/`.

```
project_data/
├── cover_schemes/     ← CoverSchemeConfig JSON files
├── crosswalks/        ← EvtCrosswalk JSON files
├── mapping_rules/     ← MappingRules JSON files
└── approvals/         ← ApprovalRecord JSON files
```

`project_data/` is Git-ignored by default. It contains locally approved
Tribal and program definitions that must not be committed publicly without
deliberate curation.

If a scheme is later approved for public hackathon sharing, a deliberately
curated version is copied to `examples/`. Do not assume local Tribal or
program definitions are automatically appropriate to commit publicly.

`outputs/` remains the directory for GIS processing results: GeoTIFFs,
GeoPackages, QC reports, and LFPS collection artifacts.

### 9.1 Approval record schema

File location: `project_data/approvals/<slug>_approval_<type>_<version>_<run_id>.json`

```json
{
  "schema_type": "approval_record",
  "approval_type": "string — 'cover_scheme', 'evt_crosswalk', 'mapping_rules'",
  "approved_item_file": "string — filename of approved config/crosswalk/rules",
  "scheme_id": "string",
  "version": "string",
  "approved_by": "string — 'user' for explicit user approval",
  "approved_at_utc": "string",
  "approval_method": "string — 'explicit_user_confirmation_in_session'",
  "source_document_reference": "string or null",
  "session_reference": "string or null — brief description of session context",
  "limitations_acknowledged": ["list of limitation strings shown to user at approval time"],
  "unresolved_items_at_approval": ["list of flagged items not yet resolved"],
  "notes": "string or null"
}
```

### 9.2 Version naming

**[Proposed]** — Scheme version identifiers use `v1`, `v2`, etc. as
short identifiers. A new version creates a new file rather than
overwriting the old one. For example:

```
mescalero_v1_cover_scheme_v1.json
mescalero_v1_evt_crosswalk_v1.json
mescalero_v1_mapping_rules_v1.json
```

A revised scheme creates:

```
mescalero_v1_cover_scheme_v2.json
```

Old versions are never overwritten or deleted.

### 9.3 Source document provenance

**[Proposed]** — If the user pastes or references a local guide document,
MapCP records only:

- `source_document_reference`: short title or filename.
- `source_document_received`: true/false.

The document content itself is not persisted in outputs to avoid inadvertent
exposure of Tribal non-public content. The user retains the authoritative copy.

---

## 10. Internal helpers vs. public MCP outcome tools

**[Approved]** — Architecture decisions recorded from session approval.

| Component | Visibility | Rationale |
|---|---|---|
| `propose_cover_scheme_draft()` | Internal helper | Parse user text or starter into draft CoverSchemeConfig; output reviewed before use |
| `validate_cover_scheme()` | Internal helper | Validate draft against schema and flag unmeasurable criteria |
| `propose_evt_crosswalk()` | Internal helper | Draft crosswalk from actual source codes; requires approval before saving |
| `save_approved_cover_scheme()` | Internal helper | Persist only after explicit user approval |
| Crosswalk coverage validator | Internal helper | QC, not a public outcome |
| Cover-scheme config saver/loader | Internal helper | File I/O supporting outcome tools |
| `onboard_cover_scheme` | Optional MCP prompt/template in `prompts.py` (not an eighth public MCP tool) | Drives the user through the three entry paths, review, and approval; implemented after MVP |
| `map_candidate_cover_types` | **Public MCP outcome tool** | Consumes approved saved files only; returns `cover_scheme_approval_required` if no approved scheme/crosswalk exists; produces actual spatial candidate cover-type outputs |
| `map_candidate_forest_land` | **Public MCP outcome tool** | Companion; same approved-files requirement |

**[Approved]** — The seven public outcome tools specified in
`docs/project-specification.md` remain unchanged. `onboard_cover_scheme`
is NOT an eighth public tool. It is implemented later as an optional MCP
prompt template backed by internal helpers.

**[Approved]** — `map_candidate_cover_types` must:
- Require an approved versioned cover-scheme config file reference.
- Require an approved versioned EVT crosswalk file reference.
- Return `{ "status": "cover_scheme_approval_required", "required_next_step": "onboard_cover_scheme" }` if either file is missing or unapproved.
- Never accept free-form cover-class definitions or arbitrary classification rules directly in the tool call.

---

## 11. Implementation vertical slices

**[Proposed]** — Each slice is a separately approved, testable increment.

### Slice 1 — Cover-scheme configuration model and saver (no mapping)

**Intent:** Define the Pydantic models for a cover-scheme configuration,
implement controlled save and load functions writing to `project_data/`,
create a committed generic public test fixture, and write unit tests.
No raster processing. No Mescalero definitions committed publicly.

**Deliverables:**
- `CoverSchemeConfig` and `CoverSchemeClass` Pydantic models in
  `cover_scheme_models.py`. `CoverSchemeClass` includes
  `first_pass_assignment_status` and `first_pass_output_code` fields.
- `save_cover_scheme_config()` internal function (writes to
  `project_data/cover_schemes/`; raises `FileExistsError` if version exists).
- `load_cover_scheme_config()` internal function.
- `project_data/` directory tree with `.gitkeep` files.
- `.gitignore` updated to ignore `project_data/` contents while tracking
  `.gitkeep` files.
- **Committed** generic public test fixture:
  `tests/fixtures/example_southwest_cover_scheme_v1.json`
  — uses fictional/non-sensitive class codes; validates the full schema
  including `first_pass_assignment_status` and `first_pass_output_code`.
- **Local only, not committed:** Mescalero v1 config at
  `project_data/cover_schemes/mescalero_v1_cover_scheme_v1.json`
  — created by the implementer locally; tests must pass without it.
- `tests/test_cover_scheme_models.py` with all named tests.

### Slice 2 — EVT crosswalk schema and saver (no mapping)

**Intent:** Define the Pydantic schema for an EVT crosswalk record, implement
save and load functions, and write tests using a committed generic public
crosswalk fixture. No Mescalero crosswalk committed. No raster processing.

**Deliverables:**
- `EvtCrosswalkRecord` and `EvtCrosswalk` Pydantic models.
- `save_evt_crosswalk()` and `load_evt_crosswalk()` internal functions.
- `evt_nvc_group` and `evt_nvc_alliance` default to `null`; populated only
  when a separately approved EVT-NVC product is available.
- `evt_nvc_product_available` defaults to `false`.
- **Committed** generic public test crosswalk fixture:
  `tests/fixtures/example_southwest_evt_crosswalk_v1.json`
  — five fictional EVT codes; one `consolidated_to_broader_class` entry;
  one unknown-code sentinel entry.
- **Local only, not committed:** Mescalero v1 crosswalk at
  `project_data/crosswalks/mescalero_v1_evt_crosswalk_v1.json`.
- Unit tests: valid round-trip (public fixture), unknown-code treatment
  (`candidate_uncertain_or_nodata`), `scheme_id` mismatch raises error,
  `evt_nvc_group` null when product unavailable. Mescalero crosswalk
  tests skip when file absent.

### Slice 3 — Mapping-rules schema and saver

**Intent:** Define the Pydantic schema for mapping rules, implement save and
load, and add a Mescalero v1 mapping-rules fixture.

**Deliverables:**
- `MappingRules` Pydantic model.
- `save_mapping_rules()` and `load_mapping_rules()` internal functions.
- Mescalero v1 mapping-rules fixture.
- Unit tests: valid round-trip, forbidden-merge rule completeness.

### Slice 4 — Approval record model and save function

**Intent:** Define and test the approval record schema and save function.

**Deliverables:**
- `ApprovalRecord` Pydantic model.
- `save_approval_record()` internal function.
- Unit tests: approval record creation, limitation acknowledgement list
  present, no email patterns in output.

### Slice 5 — Plain-language and user-supplied scheme extractor

**Intent:** Implement a structured extraction function that takes free-form
user text (or a pasted table) and produces a draft CoverSchemeConfig with all
unmeasurable criteria flagged. This is an internal helper only, not a public
tool.

**Deliverables:**
- `extract_draft_cover_scheme()` internal function.
- Returns a CoverSchemeConfig with `source_authority="plain_language_draft"`,
  all species-composition rows flagged, and `approved_by=None`.
- Unit tests: ponderosa pine plain-language input produces a draft with
  `candidate_P` and required limitation flags; unsupported productivity
  criterion is flagged; no forestry thresholds are invented.

### Slice 6 — EVT code inspector and crosswalk drafter

**Intent:** Given an actual LANDFIRE source raster (from a prior LFPS delivery)
and an approved cover-scheme config, read the unique EVT codes present in the
boundary area and draft an EVT crosswalk against the approved scheme.

**Deliverables:**
- `inspect_evt_codes()` internal function: reads unique integer codes from
  EVT band, returns code list with counts.
- `draft_evt_crosswalk()` internal function: proposes candidate class
  assignments from EVT name/NVC group vs. scheme class definitions; flags
  unknown codes as `candidate_uncertain_or_nodata`; flags
  species-composition limitations.
- Unit tests with a synthetic raster fixture: correct code extraction, all
  codes covered, unknown codes flagged.

### Slice 7 — Cover-scheme onboarding prompt template and internal helpers

**Intent:** Implement the four internal helper functions that back the
`onboard_cover_scheme` prompt template. Add `prompts.py` with the
`onboard_cover_scheme` prompt definition. Do NOT add a public MCP tool.
The seven public outcome tools remain the only registered tools.

**Deliverables:**
- `prompts.py` with `onboard_cover_scheme` prompt/template definition
  (registered via `mcp.prompt()` or equivalent, not `mcp.tool()`).
- `propose_cover_scheme_draft()` internal helper.
- `validate_cover_scheme()` internal helper.
- `propose_evt_crosswalk()` internal helper.
- `save_approved_cover_scheme()` internal helper.
- Two-phase flow: draft-and-review → approval-and-save.
- Returns structured draft with class table, limitation flags, required
  questions. Does not begin mapping.
- Unit tests: valid draft response, approval saves three files, rejection
  does not save, plain-language input returns flagged draft.

### Slice 8 — Candidate forest-land mapping (raster, internal)

**Intent:** Implement internal raster classification for candidate forest land
using an approved cover-scheme config and EVT crosswalk. Output: a
GeoTIFF raster with values: 1=candidate_forest_land, 2=candidate_nonforest,
0=candidate_uncertain_or_nodata.

**Deliverables:**
- `classify_candidate_forest_land()` internal function.
- Accepts: source raster path, boundary GeoPackage, approved scheme config,
  approved crosswalk, approved mapping rules.
- Outputs: saved GeoTIFF and QC report.
- NT and NW cells always produce candidate_forest_land=true regardless of
  EVC/EVH values, per approved Mescalero policy.
- EVC/EVH conflict detected → preserve forest-land assignment; add
  `evt_structure_conflict` and related review flags in QC report.
- Disturbance: not evaluated; `disturbance_treatment = "not_evaluated"` in provenance.
- Unit tests with synthetic raster: correct cell counts per class, NoData
  preserved, acreage closure, CRS/alignment match, NT/NW cells are
  candidate_forest_land regardless of EVC value.

### Slice 9 — Candidate cover-type mapping (raster, internal)

**Intent:** Implement internal raster classification for candidate cover types
using the approved crosswalk and rules. Output: a multi-band GeoTIFF retaining
EVT, EVC, and EVH source values alongside candidate class assignments.

**Deliverables:**
- `classify_candidate_cover_types()` internal function.
- Primary classification from EVT crosswalk only.
- EVC/EVH retained as output attributes; used to flag conflicts, not to
  override candidate class assignments.
- Riparian EVT codes → `candidate_riparian_woody_forest`,
  `candidate_riparian_nonforest`, or `candidate_riparian_uncertain` as
  appropriate; species-subtype (CO/WI/B/RO/SC) not resolved in first pass.
- Preserves uncertain, NoData, and conflict cells with required review flags.
- Outputs: saved GeoTIFF and QC report with per-class cell counts and acres.
- Provenance fields: `disturbance_product_used=false`,
  `disturbance_treatment="not_evaluated"`, `post_disturbance_history_inferred=false`.
- Unit tests: crosswalk coverage, unknown code → candidate_uncertain_or_nodata,
  NoData → candidate_uncertain_or_nodata, EVC conflict does not change
  candidate class, riparian codes produce consolidated riparian outcomes
  (not CO/WI/B), per-class area sum equals total area.

### Slice 10 — Raw patch and generalized polygon creation

**Intent:** Vectorize the classified raster into raw connected patches and
a separate generalized review-polygon layer using the approved minimum
mapping unit. Preserve protected small patches.

**Deliverables:**
- `create_raw_patches()` internal function.
- `create_generalized_polygons()` internal function.
- Unit tests: topology (no gaps, no overlaps), protected-patch preservation,
  forbidden-merge rules enforced, actual polygon area used for MMU test.

### Slice 11 — `map_candidate_cover_types` public tool

**Intent:** Expose slices 8–10 through the `map_candidate_cover_types` public
MCP outcome tool. Accepts approved config, crosswalk, rule file references,
and boundary. Returns structured summary with artifact references.

**Deliverables:**
- `map_candidate_cover_types` public MCP tool.
- Validates that all three approved files exist and match scheme/version.
- Runs slices 8, 9, and 10 internally.
- Returns acreage summary, review flags, provenance, crosswalk version, and
  artifact paths.
- Does not accept free-form classification instructions.

---

## 12. Acceptance criteria and tests for Slice 1

**[Proposed — awaiting final approval]**

### A. CoverSchemeClass model — fields

`CoverSchemeClass` has three fields whose valid values depend on each other.
All constraints are enforced as Pydantic model validators on `CoverSchemeClass`
plus a `CoverSchemeConfig`-level cross-record validator.

**`first_pass_assignment_status`**
```python
Literal[
    "assignable",                    # may be output in first baseline pass if crosswalk supports it
    "consolidated_to_broader_class", # local target code; not individually assigned; routes to first_pass_output_code
    "not_assignable",                # reserved for future approved use; never output in first pass
]
```

**`first_pass_output_code`**
```python
str | None
```

Per-record constraints (enforced at `CoverSchemeClass` level):

| `first_pass_assignment_status` | `first_pass_output_code` | `candidate_forest_land` |
|---|---|---|
| `"assignable"` | must be `null` | any valid value (bool or null) |
| `"consolidated_to_broader_class"` | must be non-null string | must match target's `candidate_forest_land` (see §A cross-record) |
| `"not_assignable"` | must be `null` | must be `null` |

`not_assignable` additionally requires at least one entry in
`review_flags_required` that explains why first-pass assignment is
unavailable (e.g. `"first_pass_assignment_not_supported_pending_approval"`).

**`first_pass_candidate_label`** *(renamed from `candidate_label_prefix`)*
- Stores the **complete** initial output label string, not a prefix.
- Examples: `"candidate_P"`, `"candidate_RIP_WOODY"`, `"candidate_NT"`.
- For `consolidated_to_broader_class` entries, must equal the target record's
  `first_pass_candidate_label` (enforced by cross-record validator).

**`candidate_forest_land`** — `Optional[bool]`

Explicit required values for all riparian-related records:

| Code | `candidate_forest_land` |
|---|---|
| CO, RO, SC, WI, B | `true` |
| R | `false` |
| RIP_WOODY | `true` |
| RIP_NONFOREST | `false` |
| RIP_UNCERTAIN | `null` |

### A.1 Cross-record validation on `CoverSchemeConfig`

A `@model_validator` on `CoverSchemeConfig` enforces these rules across the
`classes` list after all individual records pass field-level validation:

1. **Target exists:** every `first_pass_output_code` value in any
   `consolidated_to_broader_class` record must match the `candidate_code` of
   exactly one other record in the same `classes` list. Missing targets are
   rejected.

2. **Target is assignable:** the referenced target record must have
   `first_pass_assignment_status == "assignable"`. A `consolidated_to_broader_class`
   target that is itself `consolidated_to_broader_class` or `not_assignable` is
   rejected (no chains, no cycles).

3. **Label consistency:** the `first_pass_candidate_label` of the
   consolidated record must equal the `first_pass_candidate_label` of the
   target record. Mismatches are rejected.

4. **Forest-land consistency:** the `candidate_forest_land` of the
   consolidated record must equal the `candidate_forest_land` of the
   target record. Mismatches are rejected. (`null == null` passes;
   `true == false` fails; `null == true` fails.)

### B. Mescalero class-count

The Mescalero scheme has **29** local target codes:
- 11 timberland: P, PM, MC, DF, WF, A, BS, ES, SF, NT, AT
- 10 woodland/other forest: PJ, W, CO, RO, SC, WI, NW, B, IH, OK
- 8 nonforest: G, O, NR, R, AG, U, BR, WA

The local Mescalero config (not committed) contains all 29, plus three
first-pass consolidated records: RIP_WOODY, RIP_NONFOREST, RIP_UNCERTAIN
(32 entries total).

### C. First-pass consolidated riparian records — full specification

| `candidate_code` | `first_pass_assignment_status` | `first_pass_output_code` | `first_pass_candidate_label` | `candidate_forest_land` |
|---|---|---|---|---|
| `RIP_WOODY` | `assignable` | `null` | `"candidate_RIP_WOODY"` | `true` |
| `RIP_NONFOREST` | `assignable` | `null` | `"candidate_RIP_NONFOREST"` | `false` |
| `RIP_UNCERTAIN` | `assignable` | `null` | `"candidate_RIP_UNCERTAIN"` | `null` |
| CO | `consolidated_to_broader_class` | `"RIP_WOODY"` | `"candidate_RIP_WOODY"` | `true` |
| RO | `consolidated_to_broader_class` | `"RIP_WOODY"` | `"candidate_RIP_WOODY"` | `true` |
| SC | `consolidated_to_broader_class` | `"RIP_WOODY"` | `"candidate_RIP_WOODY"` | `true` |
| WI | `consolidated_to_broader_class` | `"RIP_WOODY"` | `"candidate_RIP_WOODY"` | `true` |
| B | `consolidated_to_broader_class` | `"RIP_WOODY"` | `"candidate_RIP_WOODY"` | `true` |
| R | `consolidated_to_broader_class` | `"RIP_NONFOREST"` | `"candidate_RIP_NONFOREST"` | `false` |

`RIP_WOODY` requires `review_flags_required`:
`["riparian_subtype_not_resolved", "species_review_required"]`.

`RIP_UNCERTAIN` has `candidate_forest_land = null` — schema field is
`Optional[bool]`, not `bool`. `null` means forest-land status is unknown;
it is not the same as `false`.

R is **not** independently assigned as `candidate_R` in the first pass.
It is always routed to `RIP_NONFOREST` via `first_pass_output_code`.

### D. Test fixture separation

**Committed public test fixture:**

`tests/fixtures/example_southwest_cover_scheme_v1.json`
- Uses generic fictional class codes (`PP`, `MX`, `NF`, `RIPA_W`, `RIPA_NF`,
  `RIPA_XX`) that do not replicate Mescalero local definitions.
- Includes:
  - At least one `assignable` entry with `candidate_forest_land = true`.
  - At least one `assignable` entry with `candidate_forest_land = false`.
  - At least one `assignable` entry with `candidate_forest_land = null`.
  - At least one `consolidated_to_broader_class` entry with a valid
    `first_pass_output_code`, matching `first_pass_candidate_label`, and
    matching `candidate_forest_land`.
  - At least one `not_assignable` entry with `first_pass_output_code = null`,
    `candidate_forest_land = null`, and a non-empty `review_flags_required`.
- `woodland_is_forest_land: true`.
- `source_authority: "public_starter_proposed"`, `approved_by: null`.
- Passes full `CoverSchemeConfig` model and cross-record validation.

**Local Mescalero config** (not committed):

`project_data/cover_schemes/mescalero_v1_cover_scheme_v1.json`
- 32 entries: 29 local codes + RIP_WOODY, RIP_NONFOREST, RIP_UNCERTAIN.
- All riparian `candidate_forest_land` values per §C table.
- Passes all cross-record validators.
- Tests skip when file absent.

### E. Required behavior

**Field-level (CoverSchemeClass):**

1. `CoverSchemeConfig` rejects unknown fields (`extra = "forbid"`).
2. `CoverSchemeConfig` rejects `source_authority = "local_approved"` when
   `approved_by` is `None`.
3. `CoverSchemeClass` rejects `first_pass_output_code` non-null when
   `first_pass_assignment_status != "consolidated_to_broader_class"`.
4. `CoverSchemeClass` rejects `first_pass_output_code = null` when
   `first_pass_assignment_status == "consolidated_to_broader_class"`.
5. `CoverSchemeClass` rejects `first_pass_output_code` non-null when
   `first_pass_assignment_status == "not_assignable"`.
6. `CoverSchemeClass` rejects `candidate_forest_land` non-null when
   `first_pass_assignment_status == "not_assignable"`.
7. `CoverSchemeClass` rejects empty `review_flags_required` when
   `first_pass_assignment_status == "not_assignable"`.

**Cross-record (CoverSchemeConfig model validator):**

8. `CoverSchemeConfig` rejects a `consolidated_to_broader_class` record whose
   `first_pass_output_code` does not match any `candidate_code` in `classes`.
9. `CoverSchemeConfig` rejects a `consolidated_to_broader_class` record whose
   target has `first_pass_assignment_status != "assignable"` (blocks chains
   and cycles).
10. `CoverSchemeConfig` rejects a `consolidated_to_broader_class` record whose
    `first_pass_candidate_label` does not match the target's
    `first_pass_candidate_label`.
11. `CoverSchemeConfig` rejects a `consolidated_to_broader_class` record whose
    `candidate_forest_land` does not match the target's `candidate_forest_land`
    (including `null` identity: `null` matches only `null`).

**Save/load:**

12. `save_cover_scheme_config()` writes to `project_data/cover_schemes/`.
13. `save_cover_scheme_config()` raises `FileExistsError` if version file exists.
14. `load_cover_scheme_config()` returns a model equal to the original.
15. The committed public fixture loads and validates without error.
16. No new external dependencies are added.
17. `server.py` and `tests/test_server.py` are unchanged.
18. `.gitignore` uses the four-line nested `.gitkeep`-preserving pattern.
    `git check-ignore -v` confirms:
    - `project_data/cover_schemes/.gitkeep` is **not** ignored.
    - `project_data/cover_schemes/mescalero_v1_cover_scheme_v1.json` is ignored.

### F. Named tests

**Committed — 19 tests, must all pass on fresh clone:**

| Test name | Fixture | What it verifies |
|---|---|---|
| `test_cover_scheme_config_valid_round_trip` | public fixture | Full serialize/deserialize identity |
| `test_cover_scheme_config_rejects_extra_fields` | inline dict | `extra = "forbid"` |
| `test_cover_scheme_config_rejects_unapproved_local_scheme` | inline dict | `local_approved` + `approved_by=None` rejected |
| `test_cover_scheme_class_rejects_null_output_code_when_consolidated` | inline dict | Field rule 4 |
| `test_cover_scheme_class_rejects_nonnull_output_code_when_assignable` | inline dict | Field rule 3 |
| `test_cover_scheme_class_rejects_nonnull_output_code_when_not_assignable` | inline dict | Field rule 5 |
| `test_cover_scheme_class_rejects_nonnull_forest_land_when_not_assignable` | inline dict | Field rule 6 |
| `test_cover_scheme_class_rejects_empty_flags_when_not_assignable` | inline dict | Field rule 7 |
| `test_cover_scheme_class_first_pass_candidate_label_used_not_prefix` | inline dict | Field is present; old name absent |
| `test_config_rejects_consolidated_with_missing_target` | inline dict | Cross-record rule 8 |
| `test_config_rejects_consolidated_targeting_non_assignable` | inline dict | Cross-record rule 9 |
| `test_config_rejects_consolidated_with_label_mismatch` | inline dict | Cross-record rule 10 |
| `test_config_rejects_consolidated_with_forest_land_mismatch` | inline dict | Cross-record rule 11 |
| `test_save_creates_file_in_project_data` | public fixture | File written to `project_data/cover_schemes/` |
| `test_save_does_not_overwrite_existing_version` | public fixture | `FileExistsError` raised |
| `test_load_returns_identical_model` | public fixture | Round-trip identity |
| `test_public_fixture_passes_full_validation` | public fixture | Full model + cross-record validation |
| `test_public_fixture_has_consolidated_entry_with_output_code` | public fixture | Fixture exercises consolidation path |
| `test_public_fixture_has_not_assignable_entry_with_null_forest_land` | public fixture | Fixture exercises `not_assignable` path |

**Conditional — 8 tests, skip when `project_data/` absent:**

| Test name | What it verifies |
|---|---|
| `test_mescalero_v1_fixture_passes_validation` | Full model + cross-record validation |
| `test_mescalero_v1_fixture_has_29_local_codes` | Exactly 29 local target codes present |
| `test_mescalero_v1_fixture_nt_nw_are_forest_land` | NT and NW: `candidate_forest_land = true` |
| `test_mescalero_v1_fixture_woodland_is_forest_land` | Top-level `woodland_is_forest_land = true` |
| `test_mescalero_v1_fixture_co_ro_sc_wi_b_consolidated_to_rip_woody` | CO/RO/SC/WI/B have correct consolidation and matching forest-land |
| `test_mescalero_v1_fixture_r_consolidated_to_rip_nonforest` | R consolidates to RIP_NONFOREST; `candidate_forest_land = false` matches target |
| `test_mescalero_v1_fixture_rip_uncertain_has_null_forest_land` | RIP_UNCERTAIN `candidate_forest_land = null` |
| `test_mescalero_v1_fixture_required_review_flags_present` | Required flags on P/PM/MC/RIP_WOODY/RIP_UNCERTAIN present |

### G. Evidence of completion

- All 19 committed tests pass on a fresh clone with no `project_data/` present.
- `project_data/` appears in `.gitignore` with the four-line nested
  `.gitkeep`-preserving pattern. `git check-ignore -v` confirms:
  - `project_data/cover_schemes/.gitkeep` is **not** ignored.
  - `project_data/cover_schemes/mescalero_v1_cover_scheme_v1.json` is ignored.
- `tests/fixtures/example_southwest_cover_scheme_v1.json` is committed and
  tracked. It exercises `assignable`, `consolidated_to_broader_class`,
  and `not_assignable` paths including `null` forest-land.
- No machine-readable Mescalero configuration fixture is committed in
  `tests/fixtures/`, `examples/`, or other public fixture locations unless the
  user explicitly approves public sharing. `docs/mescalero-cover-type-definitions.md`
  remains the intentional committed human-readable reference.
- The local machine-readable Mescalero config remains under `project_data/`
  and is Git-ignored by default.
- No raster, GIS, network, or MCP tool code is introduced.
- `cover_scheme_models.py` imports cleanly with `pydantic>=2.0` and no
  new dependencies.
- `server.py` and `tests/test_server.py` are unchanged.

---

## 13. Forestry decisions — approved and unresolved

### 13.1 Forest-land policy for new users (non-Mescalero)
**[Approved]** — No automatic forest-land policy is applied.

- MapCP may propose a clearly labeled **preliminary** policy, but the user
  must explicitly approve woodland treatment, nonstocked treatment, and the
  forest/nonforest definition before `map_candidate_forest_land` runs.
- If no forest-land policy is approved when `map_candidate_forest_land` is
  called, return:
  `{ "status": "forest_land_policy_approval_required" }`
- The labeled preliminary policy suggestion must be shown to the user as a
  proposal only, not applied automatically.

### 13.2 EVC and EVH roles in Mescalero first pass
**[Approved]** — EVC and EVH are used as conflict-check and
supporting-evidence inputs only.

- Primary candidate cover-type assignment comes from the approved LF2025
  EVT/EVT-NVC crosswalk.
- EVC and EVH are not used as hard preliminary classification thresholds.
- EVT, EVC, and EVH source values are retained in output attributes.
- Per-cell/polygon output records whether EVC/EVH are structurally
  consistent, conflicting, NoData, or not evaluated relative to the
  candidate class.
- EVC must not be treated as equivalent to Mescalero timber-species crown
  cover. `evc >= 10%` must not be used as the Mescalero timberland
  definition.
- EVH must not be treated as species identity, overstory/understory
  structure, basal area, merchantability, productivity, or field-measured
  tree height.
- If EVT indicates a candidate forest or woodland type but EVC/EVH indicate
  inconsistent low, shrub, herbaceous, or missing structure, preserve the
  candidate class and add review flags:
  `evt_structure_conflict`, `possible_disturbance_or_source_date_mismatch`,
  `candidate_nonstocked_forest_land_review`, `nodata_or_unknown_coverage`,
  `professional_forestry_review_required` as appropriate.
- Conflict cells are never automatically converted to nonforest.
- EVC/EVH threshold options will be proposed after first source-value
  inspection, NAIP review, and FIA-informed calibration design — as
  explicit versioned rules requiring user approval.
- `mapping_rules.evc_role = "conflict_check_and_supporting_evidence"`
- `mapping_rules.evh_role = "conflict_check_and_supporting_evidence"`
- `mapping_rules.evc_canopy_cover_threshold = null`
- `mapping_rules.evh_height_threshold = null`
- `mapping_rules.evc_conflict_produces_hard_nonforest = false`
- `mapping_rules.evh_conflict_produces_hard_nonforest = false`

### 13.3 Disturbance input for Mescalero first pass
**[Approved]** — `disturbance_treatment = "not_evaluated"`. No separate
disturbance product is added in the first pass.

- The initial workflow maps current candidate cover type and candidate
  forest-land condition using the approved LF2025 EVT/EVC/EVH crosswalk.
- MapCP must not infer or claim: disturbance cause, disturbance date,
  disturbance severity, pre-disturbance cover type, recovery trajectory, or
  fire/harvest/insect/treatment history.
- If EVT candidate class conflicts with EVC/EVH structure, preserve the
  candidate class and add neutral review flags:
  `evt_structure_conflict`, `current_structure_low_or_sparse`,
  `possible_nonstocked_forest_land`, `possible_recent_change_review_required`,
  `professional_forestry_review_required`.
- A cell must not be labeled "disturbed" unless a future approved
  disturbance source and approved disturbance rules are added.
- NT and NW retain `candidate_forest_land = true` regardless of low
  current canopy.
- Required provenance fields: `disturbance_product_used = false`,
  `disturbance_treatment = "not_evaluated"`,
  `post_disturbance_history_inferred = false`.

### 13.4 Compatible class merge rules for generalization
**[Approved]** — For the initial Mescalero pass, merge only **exact same
candidate cover codes**.

- Do not merge `candidate_P` with `candidate_PM`, `candidate_PM` with
  `candidate_MC`, `candidate_PJ` with `candidate_W`, or any other
  different local codes in the first polygon-generalization pass.
- Different-code compatibility rules may be proposed after ArcGIS review,
  but require separate forestry approval before implementation.
- Continue preserving all protected classes and conditions regardless of
  size: NT, NW, riparian, water, uncertain, NoData, mixed/conflicting, and
  review-required patches.
- This decision applies to the Mescalero pilot only. A new geography
  requires its own approved merge rules.

### 13.5 Riparian class strategy for Mescalero first pass
**[Approved]** — Three broad consolidated riparian outcomes for the first
pass:

1. **`candidate_riparian_woody_forest`**
   - `candidate_forest_land = true`
   - Review flags: `species_review_required`, `riparian_subtype_not_resolved`
   - Corresponds to woody riparian EVT codes where forest/woodland structure
     is supported.

2. **`candidate_riparian_nonforest`**
   - `candidate_forest_land = false`
   - Used only when approved EVT evidence supports nonforested riparian (R).

3. **`candidate_riparian_uncertain`**
   - `candidate_forest_land = null` (unknown)
   - Used for unsupported, mixed, conflicting, or NoData riparian evidence.

- `candidate_B_riparian_mixed` must NOT be used as the generic consolidated
  class; Mescalero B (Bosque Mixed) is a specific local type requiring
  supporting POPU/SALIX evidence.
- CO, RO, SC, WI, and B are not assigned in the first pass from LF2025
  EVT/EVC/EVH alone.
- Source EVT code/name, EVC, EVH, and any future NVC evidence are retained
  as attributes to support a later approved riparian-refinement workflow.
- EVT-NVC availability in the current LFPS bundle is not assumed; adding an
  EVT-NVC source is a separate approved source-inspection task.

### 13.6 Minimum mapping unit — all projects
**[Approved]** — No universal MMU is applied automatically.

- The user must choose and explicitly approve an MMU before generalized
  polygons are created.
- MapCP may display 10,000 m² / 1 hectare / approximately 2.47 acres as a
  **suggested default**, labeled **proposed** — not applied until approved.
- If an MMU is not approved when polygon generalization is requested,
  MapCP produces raw raster and raw connected patches only. Generalized
  polygons are not created.
- The Mescalero pilot approved MMU (10,000 m²) applies only to the
  Mescalero project; it is not automatically applied to other projects.

### 13.7 FIA calibration geography and years for Mescalero
**[Approved]** — FIA calibration is deferred to its own approved slice.

- For the initial baseline mapping pass, record:
  `fia_calibration_applied = false`
  `fia_calibration_status = "deferred_pending_approved_geography_and_years"`
- When FIA work begins: inspect actual public FIA availability, inventory
  years, sampling context, and appropriate regional or ecological geography
  before proposing any filters for user approval.
- Do not use the Reservation boundary or public FIA coordinates as exact
  local training or validation geography. Public FIA coordinates are
  spatially altered.

### 13.8 Plain-language scheme: adaptive two-stage question flow
**[Approved]** — Use an adaptive two-stage workflow.

**Minimum first screen (always asked):**
1. Do you have an existing local cover-type guide?
2. What is the project geography and mapping objective?
3. Which broad candidate classes and forest-land policy matter for your
   program?
4. Do you want a public regional starter scheme or to define a local scheme?

**Extended follow-up (asked only when relevant to the user's answers):**
- Woodland and nonstocked treatment.
- Species-composition and crown-cover definitions.
- Riparian treatment.
- Disturbance treatment.
- NoData and unknown-code handling.
- Minimum mapping unit.
- Protected small patches.
- FIA calibration interest.
- Overstory/understory requirements.

MapCP must not ask all extended questions if the user's first-screen answers
make them irrelevant.

### 13.9 Onboarding conversation driver name and implementation
**[Approved]** — Named `onboard_cover_scheme`. Implemented as an optional
MCP prompt/template in `prompts.py`, not as a public MCP tool. The seven
public outcome tools remain unchanged.

---

## 14. LANDFIRE species-composition limitation requirements

The following practices are required for all Mescalero pilot mapping.

1. **[Approved]** — Every crosswalk entry whose target class depends on
   species-specific crown-cover percentages (P, PM, MC, DF, WF, A, BS, ES,
   SF, PJ) must include `"species_composition_not_directly_measured"` in
   `source_limitation_flags`.

2. **[Approved]** — Every output polygon/raster cell assigned to those
   classes must carry `"species_composition_not_directly_measured"` and
   `"crown_cover_percentage_not_directly_measured"` in its attribute
   review flags.

3. **[Approved from Mescalero pilot policy]** — First mapping pass:
   `first_pass_one_class_only = true`. Dual typing is deferred.

4. **[Approved from Mescalero pilot policy]** —
   `overstory_understory_not_modeled` review flag is required on all
   candidate output polygons in the first pass.

5. **[Approved]** — EVT-NVC alliance names from actual XML metadata are
   the primary crosswalk basis for species affinity. EVT integer codes
   alone are not sufficient. EVT-NVC availability in the current LFPS
   bundle must be verified before it is used; it is not assumed to be
   present.

6. **[Approved]** — EVC is used for conflict-flagging only
   (`evc_role = "conflict_check_and_supporting_evidence"`). It must not
   substitute for measured species-specific crown-cover proportions. EVC
   conflict does not override the EVT-derived candidate class assignment.

7. **[Proposed]** — Public FIA data for the Mescalero area may support
   ecological plausibility checks but never as pixel- or stand-level
   labels. FIA coordinates are spatially altered. FIA plausibility notes
   must state evaluation group, years, filters, and uncertainty.

8. **[Approved]** — No confidence percentage may be reported for
   species-composition assignments. Review flags are used instead of
   numeric confidence scores.

---

## 15. Files likely to change

| File | Proposed change | Slice |
|---|---|---|
| `server.py` | Add new internal functions after existing tools | 1–11 |
| `tests/test_server.py` | Add test classes for new schemas and functions | 1–11 |
| `.gitignore` | Add `project_data/` entry | 1 |
| `docs/mescalero-cover-type-definitions.md` | No change without separate approval | — |
| `docs/project-specification.md` | No change without separate approval | — |

New files proposed (to be approved before creation):

| File | Committed to Git? | Purpose |
|---|---|---|
| `cover_scheme_models.py` | Yes | Pydantic models: `CoverSchemeConfig`, `CoverSchemeClass`, save/load functions |
| `tests/test_cover_scheme_models.py` | Yes | Slice 1 unit tests |
| `tests/fixtures/example_southwest_cover_scheme_v1.json` | Yes | Generic public test fixture — no Tribal definitions |
| `tests/fixtures/example_southwest_evt_crosswalk_v1.json` | Yes | Generic public crosswalk fixture (Slice 2) |
| `prompts.py` | Yes | `onboard_cover_scheme` prompt/template (Slice 7; not a public MCP tool) |
| `project_data/cover_schemes/mescalero_v1_cover_scheme_v1.json` | **No — Git-ignored** | Mescalero pilot cover-scheme config (29 local codes + 3 RIP_* records); local only |
| `project_data/crosswalks/mescalero_v1_evt_crosswalk_v1.json` | **No — Git-ignored** | Mescalero pilot EVT crosswalk; local only |
| `project_data/mapping_rules/mescalero_v1_mapping_rules_v1.json` | **No — Git-ignored** | Mescalero pilot mapping rules; local only |
| `project_data/approvals/` | `.gitkeep` only | Directory for approval records; records created at runtime |
| `examples/` | (Later, after explicit approval) | Deliberately curated public-sharing copies only |

---

## 16. Dependencies and environment assumptions

**[Verified]** — Existing: `pydantic>=2.0`, `rasterio>=1.4`,
`geopandas>=1.0`, `shapely>=2.0`, `pyproj>=3.6`, `pytest>=8.0`.

**[Proposed]** — Slices 1–7 require only `pydantic` and `json`/`pathlib`;
no new dependencies are needed.

**[Proposed]** — Slices 8–9 require `rasterio` (already declared); no new
dependencies are needed.

**[Approved]** — `scipy` is treated as **unverified and optional**.
- Do not install `scipy` now. Do not make it a dependency of Slices 1–9.
- Before Slice 10: inspect the actual IBM Bob / RHEL environment and
  determine whether `scipy` is available and compatible.
- Design polygon-generalization processing (Slice 10) so that `scipy` may
  be used as an optional acceleration backend (e.g., `scipy.ndimage.label`
  for connected-component labeling) if available, but an alternative
  implementation path (e.g., `rasterio` + `shapely` connectivity) must
  work without it.
- `scipy` must not be the sole implementation path for any required feature.

---

## 17. Risks and rollback

**[Proposed]** — Risks:

1. **Crosswalk completeness risk:** EVT codes present in the actual Mescalero
   raster may not all be covered by a draft crosswalk, producing uncovered
   cells. Mitigation: unknown codes always fall through to
   `candidate_uncertain_or_nodata`; coverage is validated before mapping runs.

2. **Species-composition over-assignment:** If EVT-NVC name matching is too
   broad, some cells may be assigned to specific species-composition classes
   (e.g., P or PM) when the source evidence is only loosely related.
   Mitigation: all such cells carry required review flags; no accuracy claims
   are made.

3. **File overwrite:** If a version identifier is reused, a previous approved
   config could be overwritten. Mitigation: `save` functions check for file
   existence and raise an error if the file already exists.

4. **Mescalero definitions applied to another geography:** If Mescalero
   scheme files are loaded in a non-Mescalero project, incorrect results will
   occur silently. Mitigation: `geographic_applicability` field is present;
   the onboarding tool must check that the loaded scheme matches the current
   project boundary.

**[Proposed]** — Rollback: All new functions and models are additive. Existing
tools are not changed. If a slice is rejected, its code can be removed or
disabled without affecting existing tests.


## 19. Approved implementation-architecture details

### 19.1 Controlled project configuration storage
**[Approved]** — Cover-scheme configurations, EVT crosswalks, mapping-rules
records, and approval records are stored under `project_data/`, not in
`outputs/`. (Full specification in §9.)

Key rules:
- `project_data/` is added to `.gitignore` in Slice 1.
- Files are never auto-committed or auto-pushed.
- If a scheme is approved for public hackathon sharing, a deliberately
  curated copy is placed in `examples/` only — not by moving the original.
- `outputs/` is reserved for GIS processing results (GeoTIFFs, GeoPackages,
  QC reports, LFPS artifacts). No cover-scheme or crosswalk JSON files
  belong in `outputs/`.

### 19.2 EVT-NVC availability — do not assume
**[Approved]** — The current collected LF2025 source bundle includes
LF2025_EVT_CONUS, LF2025_EVC_CONUS, and LF2025_EVH_CONUS. It does not
include a separately collected and validated EVT-NVC product.

Key rules:
- Use actual LF2025 EVT code and available XML metadata as the initial
  crosswalk basis.
- `evt_nvc_group` and `evt_nvc_alliance` fields in crosswalk entries must
  remain `null` unless a separate current EVT-NVC source has been
  explicitly requested, collected, validated, and approved.
- The crosswalk schema includes `evt_nvc_product_available` (boolean) and
  `evt_nvc_product_reference` (string or null) at the top level. Both are
  `false` / `null` in the initial Mescalero crosswalk.
- `crosswalk_basis` must reference actual LF2025 EVT code and metadata
  only; do not reference EVT-NVC alliances in Slice 2 or 6 unless the
  product has been separately approved.
- Adding an EVT-NVC source is a separate approved source-inspection and
  validation task, to be planned and submitted for approval when needed.

---


---

## 18. Status legend

| Label | Meaning |
|---|---|
| **Verified** | Confirmed by reading actual repository files in this session |
| **Proposed** | Recommended design or implementation choice; requires approval |
| **Assumed** | Assumed to be true based on project context; should be confirmed |
| **Unresolved** | Requires explicit user decision before implementation |
