# Mescalero Pilot Cover-Type Definitions

## Status and authority

**Status:** User-provided local reference document for the Mescalero pilot.

This document records the Mescalero cover-type definitions supplied by the
project user. It is the authoritative local reference for the Mescalero pilot
when drafting candidate cover-type configurations, source-to-class crosswalks,
candidate forest-land rules, mapping methods, review questions, and
documentation.

This document is not:

- A claim that Tribal Forest MapCP currently implements these classes.
- A ready-to-run raster classification crosswalk.
- A replacement for professional forestry review.
- A field inventory.
- An authoritative land-status, legal-access, ownership, trust-status,
  productivity, commercial-status, or management-authority determination.
- A universal default for another Tribe, BIA program, project area, or
  geography.

MapCP outputs based on this document must use preliminary labels such as
`candidate_P`, `candidate_PM`, `candidate_MC`, and `candidate_PJ`, not final,
field-verified, or authoritative cover-type labels.

## MapCP policy decisions

The following policy decisions have been approved for the initial Mescalero
pilot workflow:

- Woodland and other forest-cover types are candidate forest land.
- NT, Non-stocked Timber, is candidate forest land.
- NW, Non-stocked Woodland, is candidate forest land.
- A low current tree-crown percentage does not automatically convert approved
  nonstocked forest land into candidate nonforest.
- Candidate forest-land mapping must distinguish current vegetation structure
  from approved forest-land or woodland designation.
- MapCP must not infer tree-growing capability, productivity, commercial
  status, or forest-land designation from LANDFIRE alone.
- The first implementation may assign one primary candidate cover type only.
- The first implementation must include an
  `overstory_understory_not_modeled` review flag because initial public-source
  inputs do not resolve the local overstory/understory typing procedure.
- Initial outputs preserve raw 30 m source evidence, create raw connected
  same-class patches, and create a separate generalized review-polygon layer.
- The initial generalized review-polygon minimum mapping unit is 10,000 square
  meters, approximately 2.47 acres or 1 hectare.
- Small NT, NW, riparian, water, disturbance, uncertain, NoData, and
  mixed/conflicting patches must not be silently removed by polygon
  generalization.

## Important classification limitation

Many Mescalero definitions below depend on species composition and proportions
of crown cover, including distinctions such as:

- Percentage of timber-species crown cover represented by PIPO.
- Presence of PSME, ABCO, or PIST.
- Percentage of crown cover represented by PIEN, ABLA, or PIPU.
- Overstory versus understory crown-cover typing.

Initial MapCP public-source inputs include modeled LANDFIRE vegetation type,
cover, and height evidence, plus NAIP visual-review context and later
FIA-informed regional calibration.

Those sources do not directly measure:

- Species-specific local crown-cover percentages.
- Exact overstory and understory crown-cover proportions.
- Measured basal area.
- Timber volume.
- Merchantability.
- Site productivity.
- Approved timberland designation.
- Field-verified stand composition.

Therefore, MapCP may use these definitions as the target candidate scheme, but
it must preserve limitations, uncertainty, conflicts, unknown source codes, and
review requirements.

## Timberland types

Forested areas typed as timberland must contain at least 10 percent total crown
coverage in timber species.

In two- or multi-canopied stands, definitions are applied to both the overstory
and understory. For stands with both an overstory and understory, first select a
definition that best fits the overstory component only. Then select a definition
that best fits the remaining understory component.

| Code | Name | Local definition | Candidate forest land |
|---|---|---|---:|
| P | Ponderosa Pine | Forest areas in which PIPO is the predominant timber species and makes up at least 75% of the total crown cover of timber species | Yes |
| PM | Pine Mixed | Forest areas in which 40 to 75% of the total crown cover in timber species is PIPO and the remainder of the timber crown cover is in any combination of PSME, PIST, ABCO, PIEN, PIPU, POTR, ABLA, or other incidental species. PSME, ABCO, or PIST must be present | Yes |
| MC | Mixed Conifer | Forest areas in which less than 40% of the timber crown cover is PIPO and most of the crown cover in timber species is in any combination of at least three of PSME, PIST, PIPO, ABCO, PIEN, PIPU, POTR, ABLA, or other incidental species. PSME, ABCO, or PIST must be present | Yes |
| DF | Douglas-fir | Forest areas in which Douglas-fir is the predominant timber species and makes up at least 60% of total crown cover of timber species | Yes |
| WF | White Fir | Forest areas where ABCO is the only timber species present, or where ABCO and one other timber species are present. If PIPO is the other timber species, ABCO must be more than 60% of total timber-species crown cover. If PSME is the other timber species, ABCO must be more than 40%. If the other timber species are neither PIPO nor PSME, ABCO must be more than 25% | Yes |
| A | Aspen | Forest areas in which 75% or more of total crown cover in timber species is POTR | Yes |
| BS | Blue Spruce | Forest areas in which 75% or more of total crown cover in timber species is PIPU | Yes |
| ES | Engelmann Spruce | Forest areas in which 75% or more of total crown cover in timber species is PIEN | Yes |
| SF | Spruce-Fir | Forest areas in which 75% or more of total crown cover in timber species is any combination of PIEN, ABLA, and PIPU | Yes |
| NT | Non-stocked Timber | Non-stocked commercial timberland with less than 10% total crown cover in timber species. Follow NT with the vegetative cover type present. When using NT or NW, record NT or NW as the primary overstory cover type and record the existing cover type before disturbance as the primary understory cover type, if available | Yes |
| AT | Alpine Transition | Forest land occurring at higher elevations, usually above 11,500 feet. Areas are lightly stocked with PIEN, ABLA, and other species and have limited commercial value because of harsh sites and poor growing conditions | Yes |

## Woodland and other forest cover types

Woodland and other forest-cover types are forest areas containing less than 10%
total crown cover in timber species and more than 10% total crown cover in other
tree species.

For the Mescalero pilot, all woodland and other forest-cover types below are
candidate forest land.

| Code | Name | Local definition | Candidate forest land |
|---|---|---|---:|
| PJ | Pinyon and Juniper | Forest lands in which 75% or more of crown cover is made up of a combination of pinyon pine and various juniper species. The juniper component is less than 75% of the pinyon/juniper crown cover | Yes |
| W | Juniper | Forest lands in which 75% or more of crown cover is made up of juniper species | Yes |
| CO | Cottonwood | Riparian forest lands in which 75% or more of crown cover is made up of riparian Populus species, including Fremontii, angustifolia, and acuminata | Yes |
| RO | Russian Olive | Riparian forest lands in which 75% or more of crown cover is made up of Russian Olive, Elaeagnus angustifolia | Yes |
| SC | Salt Cedar | Riparian forest lands in which 75% or more of crown cover is made up of salt cedar, Tamarix pentandra | Yes |
| WI | Willow | Riparian forest lands in which 75% or more of crown cover is made up of riparian Salix species, including exigua, nivalis, bebbiana, goodingii, scouleri, lasiandra, irrorata, and subcoerulea | Yes |
| NW | Non-stocked Woodland | Non-stocked woodland with less than 10% total crown cover in woodland species. Follow NW with the vegetative cover type present. When using NT or NW, record NT or NW as the primary overstory cover type and record the existing cover type before disturbance as the primary understory cover type, if available | Yes |
| B | Bosque Mixed | Forest lands in which crown cover is made up of a mix of riparian vegetation consisting of POPU, SALIX, and other species components | Yes |
| IH | Intermountain Hardwoods | Forest lands in which predominant crown cover is made up of a combination of ACER, QUER, and FRAX | Yes |
| OK | Oak | Land consisting primarily of Gambel oak crown cover | Yes |

## Nonforested areas

Nonforested areas consist of less than 10% tree crown cover. Nonforest
vegetative cover may or may not exist.

| Code | Name | Local definition | Candidate forest land |
|---|---|---|---:|
| G | Grass | Open nonforested land with a vadose ecosystem yielding significant amounts of graminoid vegetation | No |
| O | Barren | Land containing little or no vegetative cover; for example, land that is 90% barren | No |
| NR | Non-commercial Rocky | Land consisting predominantly of rocky ground cover to an extent where vegetative growth is severely inhibited | No |
| R | Riparian Vegetation | Nonforested areas, other than Bosque, that support a phreatic ecosystem | No |
| AG | Agriculture | Agricultural land used for growing crops other than grass | No |
| U | Urban | Land developed for commercial and/or residential purposes | No |
| BR | Brush | Land areas supporting brush cover such as sagebrush, oak brush, or other brushy species | No |
| WA | Water | Water | No |

## Classification workflow requirements

Before MapCP maps a candidate class from this scheme, it must:

1. Inspect actual LANDFIRE EVT codes and XML metadata present in the selected
   project area.
2. Document the source code, source class name, source version, and source
   lineage.
3. Draft a source-to-Mescalero-candidate-class crosswalk.
4. Identify where a public source does not support a Mescalero species,
   crown-cover, overstory/understory, or disturbance criterion.
5. Ask the user to approve, revise, or reject the draft crosswalk.
6. Define whether EVC and EVH act as supporting evidence, conflict flags, or
   approved preliminary thresholds.
7. Define treatment of disturbance, NoData, unknown EVT codes, and conflicting
   evidence.
8. Save the approved scheme and crosswalk with version identifiers.
9. Produce candidate outputs with review flags, provenance, acreage summaries,
   and limitations.
10. Preserve unclassified or unsupported cells as
    `candidate_uncertain_or_nodata` rather than forcing an unsupported type.

## Required candidate review flags

Initial Mescalero candidate mapping must support flags such as:

```text
overstory_understory_not_modeled
species_composition_not_directly_measured
crown_cover_percentage_not_directly_measured
source_evt_code_unknown
source_evt_crosswalk_unapproved
evc_evh_structure_conflict
disturbance_not_evaluated
candidate_nonstocked_timberland
candidate_nonstocked_woodland
riparian_feature_preserved
small_protected_patch_preserved
nodata_or_unknown_coverage
professional_forestry_review_required
```

## Related output classes

Initial MapCP outputs should retain separate fields for:

```text
candidate_cover_code
candidate_cover_name
candidate_forest_land
candidate_structure_group
candidate_nonstocked_status
candidate_uncertainty_flag
candidate_disturbance_flag
review_flags
cover_scheme_version
crosswalk_version
rule_version
source_provenance_reference
```

Candidate forest-land aggregation for this Mescalero pilot is:

```text
Candidate forest land:
P, PM, MC, DF, WF, A, BS, ES, SF, NT, AT,
PJ, W, CO, RO, SC, WI, NW, B, IH, OK

Candidate nonforest:
G, O, NR, R, AG, U, BR, WA

Candidate uncertain:
NoData, unknown source code, unsupported crosswalk, mixed/conflicting
evidence, or any location retained for professional review
```

## Change control

Changes to this document require user approval and must be versioned.

Do not silently change:

- Cover-type code meanings.
- Forest-land policy.
- NT or NW treatment.
- Species abbreviations.
- Crown-cover criteria.
- Overstory/understory logic.
- Nonforest definitions.
- Minimum mapping unit.
- Protected-patch rules.
- Source-to-class crosswalks.
- Thresholds or review-flag semantics.

A future approved revision should create a new document version, such as:

```text
mescalero-cover-type-definitions-v2.md
```

rather than overwriting the meaning of a previously used scheme.