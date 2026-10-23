"""The MCP endpoint, mounted at ``/api/v1/vaults/{vault_id}/m/mcp`` (``mcp.md`` §2), and the
server token for Settings → AI access (``mcp.md`` §4).

Streamable HTTP, stateless, with JSON responses: each request carries one JSON-RPC message and
is answered on its own, so the endpoint keeps no sessions between requests. There is no
server-to-client stream to open, so ``GET`` answers ``405``, as the transport allows. The bearer
token is checked before routing (``BearerAuthMiddleware``), the module's state by
``require_module``.

The token routes are the author's (readers and a read-only server get ``404``): the token gives
every vault of the server to whoever holds it, so the app shows it only to the author.
"""

from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from lore.core.api.bearer import ServerToken
from lore.core.api.deps import (
    ModuleRegistryDep,
    PolicyDep,
    ServerTokenDep,
    SettingsDep,
    VaultDep,
    WritableVaultDep,
)
from lore.modules.mcp.server import Endpoint, McpResponse

router = APIRouter(tags=["mcp"])


@router.api_route("", methods=["POST", "DELETE"], include_in_schema=False)
async def mcp_endpoint(
    vault: VaultDep, registry: ModuleRegistryDep, settings: SettingsDep
) -> Response:
    """The vault's MCP server (``Authorization: Bearer <token>``)."""
    return McpResponse(Endpoint(vault, registry, read_only=settings.read_only or vault.read_only))


class McpToken(BaseModel):
    token: str | None = Field(description="The server's token (null: it can't be read or made).")
    source: Literal["environment", "file"] = Field(
        description="`environment`: `LORE_MCP_TOKEN` sets it (it can't be regenerated here); "
        "`file`: the data directory's `secrets/mcp-token`."
    )


def _out(token: ServerToken, value: str | None) -> McpToken:
    return McpToken(token=value, source="environment" if token.from_environment else "file")


@router.get("/token", name="token")
def get_token(vault: VaultDep, policy: PolicyDep, token: ServerTokenDep) -> McpToken:
    """The server's bearer token for MCP clients (author-only)."""
    del vault
    policy.require_author("The token isn't available to readers.")
    return _out(token, token.value())


@router.post("/token/regenerate", name="regenerate_token")
def regenerate_token(vault: WritableVaultDep, policy: PolicyDep, token: ServerTokenDep) -> McpToken:
    """A new token: clients with the old one get ``401`` (``409 token_from_environment`` when
    ``LORE_MCP_TOKEN`` sets it)."""
    del vault
    policy.require_author("The token isn't available to readers.")
    return _out(token, token.regenerate())
