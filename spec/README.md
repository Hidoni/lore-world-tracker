# spec/

Language-neutral artifacts shared by both chronology engines (`backend/src/lore/chronology` and
`packages/chronology`):

- `chronology/schema/`: JSON Schemas exported from the Pydantic models in
  `backend/src/lore/chronology/schema.py` (`make gen`; never edit by hand). One file per top-level
  type plus `bundle.json`, from which `packages/chronology/src/schema.gen.ts` is generated.
- `chronology/conformance/`: conformance vectors run against both engines (format: its
  `README.md`).
- `chronology/presets/`: calendar presets (arrive with #18).

Also, shared by the frontend editor and the backend's rich-text validator:

- `richtext/fixtures/`: documents the editor produces, which the server must accept without loss
  (`frontend/src/editor/fixtures.test.ts` regenerates them with `UPDATE_FIXTURES=1`;
  `backend/tests/test_richtext.py` validates them; `frontend.md` §6).

See `docs/architecture/chronology-engine.md` §1 and §14.
The Docker image copies this directory to `/app/spec` (`LORE_SPEC_DIR`).
