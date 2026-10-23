"""The mcp module's spec."""

from lore.core.modules import ModuleSpec
from lore.modules.mcp.router import router
from lore.modules.mcp.settings import MODULE_ID, McpSettings

MODULE = ModuleSpec(
    id=MODULE_ID,
    name="AI assistants (MCP)",
    description="Lets AI assistants (Claude Desktop, Claude Code, any MCP client) search and "
    "read this vault, and write to it if you allow it, over the Model Context Protocol.",
    default_enabled=False,
    routers=(router,),
    bearer_routes=("",),
    settings_model=McpSettings,
)
