"""The languages module's Markdown contributor (``docs/modules/languages.md``;
``lore.core.markdown.export``): a ``lexiconRef`` shows its entry's headword, or nothing when the
export's audience may not see the entry."""

from lore.core.errors import NotFoundError
from lore.core.markdown.export import MarkdownExport
from lore.core.markdown.render import escape
from lore.core.richtext.handlers import Node
from lore.modules.languages.lexicon import Lexicon


def export_lexicon_refs(export: MarkdownExport) -> None:
    lexicon = Lexicon(export.context, export.policy)
    headwords: dict[str, str] = {}

    def lexicon_ref(node: Node) -> str:
        entry_id = str((node.get("attrs") or {}).get("entryId", ""))
        if entry_id not in headwords:
            try:
                headwords[entry_id] = lexicon.entry(entry_id).headword
            except NotFoundError:
                headwords[entry_id] = ""
        return f"*{escape(headwords[entry_id])}*" if headwords[entry_id] else ""

    export.nodes["lexiconRef"] = lexicon_ref


__all__ = ["export_lexicon_refs"]
