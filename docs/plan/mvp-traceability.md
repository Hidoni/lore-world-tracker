# MVP traceability (1.0.0)

The MVP definition (`docs/product/vision.md`) and every requirement of
`docs/product/requirements.md`, traced to the closed issues that implemented them (#146). Each
issue links its pull requests. Generated from the issues' "Requirements" lines on 2026-10-17;
R-EVT-4 (participants with roles, module link types) is implemented by #50 and #90, which don't
cite it.

## The MVP definition

| An author can, in one Docker deployment… | Issues |
| --- | --- |
| create several vaults, each with several dimensions (time spec and calendars) | #30, #45, #46, #58, #75 |
| define calendars with leap rules and exceptions, intercalary days, week and parallel cycles, eras, reforms and astronomical overlays, and see every date in every calendar | #10–#18, #23–#25, #76, #77, #72 |
| create events with precision/circa dates, relative anchors, sub-events, causal chains, participants and all recurrence types (with per-occurrence changes and sub-events) | #47, #48, #50, #52, #53, #19–#21, #26, #73, #74, #78, #79, #84 |
| edit a calendar and get an impact preview that keeps typed dates by default | #54, #77, #237 |
| use the Locations, Species, Characters, Groups, Languages (with lexicon) and Misc modules, plus images/attachments, interactive maps and custom fields and kinds | #89–#98, #126–#130, #133–#135 |
| give relationships, fields and existence validity periods and browse as of any moment | #100–#105, #308 |
| create alternate timelines, define cross-dimension correspondences and model personal timelines of time travelers | #49, #114–#123, #327 |
| explore via the timeline view, graph view (global and local), hierarchy, causality and family-tree views, backlinks and search | #51, #80–#84, #109–#112, #320, #90, #93, #95, #39, #66, #67 |
| see and configure consistency findings | #55, #85, #106, #123 |
| mark things private/spoiler and run a read-only server (from a published snapshot) for readers | #40, #138–#142 |
| back up and restore a vault, and upgrade the app without losing data | #31, #41, #42, #143, and a golden fixture vault per release (#43 … #137) |

Quality across all of it: accessibility (#145), performance (#144, #241,
#361–#363), end-to-end journeys E1–E13 (#70, #87, #107, #124, #131, #136, #143).

## Requirements

| Requirement | Milestones | Issues |
| --- | --- | --- |
| R-VLT-1 | M2, M4 | #30, #58 |
| R-VLT-2 | M2 | #30 |
| R-VLT-3 | M2, M12 | #41, #69 |
| R-VLT-4 | M2, M4 | #69 |
| R-DIM-1 | M3, M5 | #45, #75 |
| R-DIM-2 | M3 | #45, #75 |
| R-DIM-3 | M3 | #45, #75 |
| R-DIM-4 | M3, M7 | #45, #75, #103 |
| R-DIM-5 | M3, M5 | #46, #50, #75 |
| R-TIME-1 | all | #72 |
| R-TIME-2 | M3 | #47, #73, #74 |
| R-TIME-3 | M3 | #47, #73 |
| R-TIME-4 | M3 | #48 |
| R-TIME-5 | M3, M5 | #54, #77 |
| R-TIME-6 | M1, M3 | #16, #47 |
| R-TIME-7 | M3 | #48 |
| R-CAL-1 | M1, M3 | #8, #46 |
| R-CAL-2 | M1 | #76 |
| R-CAL-3 | M1 | #76 |
| R-CAL-4 | M1 | #13, #76 |
| R-CAL-5 | M1 | #13, #77 |
| R-CAL-6 | M1, M3 | #14 |
| R-CAL-7 | M1 | #14 |
| R-CAL-8 | M1 | #15 |
| R-CAL-9 | M1, M3 | #14, #46, #76 |
| R-CAL-10 | M1 | #17, #77 |
| R-CAL-11 | M1 | #8 |
| R-CAL-12 | M1, M5 | #18, #46, #75 |
| R-CAL-13 | M5 | #76 |
| R-CAL-14 | M5 | #17, #72 |
| R-EVT-1 | M3 | #50, #74, #78, #224 |
| R-EVT-2 | M3, M5 | #53, #83 |
| R-EVT-3 | M3, M5 | #84 |
| R-EVT-4 | M3, M6 | #50, #90 |
| R-EVT-5 | M3 | #50 |
| R-EVT-6 | M5 | #78 |
| R-REC-1 | M1, M3 | #19, #52 |
| R-REC-2 | M1 | #19, #20, #79 |
| R-REC-3 | M1 | #19 |
| R-REC-4 | M1, M3 | #21, #52 |
| R-REC-5 | M3, M5 | #21, #53 |
| R-REC-6 | M3, M5 | #21, #54, #79, #230 |
| R-REC-7 | M5 | #82 |
| R-TL-1 | M3 (infra), M9 | #45, #49, #114 |
| R-TL-2 | M9 | #49, #114, #115 |
| R-TL-3 | M9 | #114 |
| R-TL-4 | M9 | #115, #116, #117 |
| R-XD-1 | M1, M9 | #22, #118, #119, #327 |
| R-XD-2 | M9 | #119 |
| R-XD-3 | M9 | #22, #118, #327 |
| R-WL-1 | M9 | #120, #121, #122 |
| R-WL-2 | M9 | #121 |
| R-WL-3 | M9 | #120, #122 |
| R-WL-4 | M9 | #123 |
| R-ENT-1 | M2 | #34 |
| R-ENT-2 | M2, M4 | #34, #61 |
| R-ENT-3 | M2, M4 | #34, #61 |
| R-ENT-4 | M2, M4 | #37, #68 |
| R-ENT-5 | M2 | #34 |
| R-LNK-1 | M2, M7 | #36, #66, #100, #102, #104 |
| R-LNK-2 | M2, M11 | #36, #69, #135 |
| R-LNK-3 | M4, M8 | #38, #63, #66, #112, #259 |
| R-LNK-4 | M8 | #83, #111 |
| R-TMP-1 | M7 | #101, #104 |
| R-TMP-2 | M7 | #100, #104 |
| R-TMP-3 | M7, M8, M10 | #101, #102, #103, #128 |
| R-TMP-4 | M7 | #105 |
| R-MOD-1 | M2, M4 | #33, #69 |
| R-MOD-2 | M6+ | #89 |
| R-LOC-1 | M6 | #90 |
| R-SPC-1 | M6 | #91 |
| R-CHR-1 | M6, M7 | #92, #93 |
| R-GRP-1 | M6 | #94, #95 |
| R-LNG-1 | M6 | #96 |
| R-LNG-2 | M6 | #97, #98 |
| R-MSC-1 | M6 | #89 |
| R-MED-1 | M10 | #126 |
| R-MAP-1 | M10 | #128 |
| R-CST-1 | M11 | #133, #135 |
| R-CST-2 | M11 | #134, #135 |
| R-UI-1 | M4, M5 | #35, #58, #65, #84 |
| R-UI-2 | M4 | #61, #63, #259 |
| R-UI-3 | M5, M9 | #28, #51, #80, #81, #82, #83, #117 |
| R-UI-4 | M8 | #109, #110, #111 |
| R-UI-5 | M5, M6, M8 | #84, #93, #95 |
| R-UI-6 | M4 | #67 |
| R-UI-7 | M4, M12 | #58, #141, #145 |
| R-SRCH-1 | M2, M4, M6 | #39, #67 |
| R-CON-1 | M3, M5 | #55, #85 |
| R-CON-2 | M3, M7 | #55, #85, #106 |
| R-CON-3 | M3–M9 | #55, #106, #123 |
| R-VIS-1 | M2 (data), M12 (enforcement) | #38, #40, #64, #139 |
| R-VIS-2 | M12 | #40, #141 |
| R-SHR-1 | M12 | #40, #138, #139, #142 |
| R-SHR-2 | M12 | #140 |
| R-SHR-3 | M13 | post-MVP |
| R-DAT-1 | M2 | #31 |
| R-DAT-2 | M1, M2 | #8 |
| R-DAT-3 | M2+ | #31 |
| R-DEP-1 | M0, M12 | #7, #142 |
| R-DEP-2 | M0 | #1 |
| R-NFR-1 | all | #51, #81, #109, #144, #235, #236, #237, #238 |
| R-NFR-2 | M0, M10, M12 | #5, #126 |
| R-NFR-3 | M4+ | #145 |
| R-NFR-4 | M4 | #2 |
| R-NFR-5 | M0 | #1, #2, #167 |
