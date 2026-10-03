"""Rich-text documents (``frontend.md`` §6): the node schema and validator (``schema``), text,
mention and reference extraction and reader filtering (``extract``), mentions maintenance
(``mentions``), upgraders (``upgrade``) and module node handlers (``handlers``)."""

# The rich-text node schema version stored in ``body_schema_version`` (shared with the frontend).
SCHEMA_VERSION = 1
