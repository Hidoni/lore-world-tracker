"""The module's settings (``mcp.md`` §3), stored in the vault (``ModuleSpec.settings_model``)."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

MODULE_ID = "mcp"


class McpSettings(BaseModel):
    """``access``: what assistants see (``readers``: the readers' policy, ``author``:
    everything). ``writes``: whether the write tools work (only with ``author`` access)."""

    model_config = ConfigDict(extra="forbid")

    access: Literal["readers", "author"] = "readers"
    writes: Literal["off", "on"] = "off"

    @model_validator(mode="after")
    def _writes_need_author_access(self) -> Self:
        if self.writes == "on" and self.access != "author":
            msg = "writes need access = author"
            raise ValueError(msg)
        return self
