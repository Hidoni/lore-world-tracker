"""The MCP endpoint, mounted at ``/api/v1/vaults/{vault_id}/m/mcp`` (``mcp.md`` §2).

Streamable HTTP, stateless, with JSON responses: each request carries one JSON-RPC message and
is answered on its own, so the endpoint keeps no sessions between requests. There is no
server-to-client stream to open, so ``GET`` answers ``405``, as the transport allows. The bearer
token is checked before routing (``BearerAuthMiddleware``), the module's state by
``require_module``.
"""

from fastapi import APIRouter, Response

from lore.core.api.deps import ModuleRegistryDep, SettingsDep, VaultDep
from lore.modules.mcp.server import Endpoint, McpResponse

router = APIRouter(tags=["mcp"])


@router.api_route("", methods=["POST", "DELETE"], include_in_schema=False)
async def mcp_endpoint(
    vault: VaultDep, registry: ModuleRegistryDep, settings: SettingsDep
) -> Response:
    """The vault's MCP server (``Authorization: Bearer <token>``)."""
    return McpResponse(Endpoint(vault, registry, read_only=settings.read_only or vault.read_only))
