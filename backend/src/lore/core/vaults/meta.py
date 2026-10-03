"""``vault_meta``: key/value metadata inside the vault database (``data-model.md`` §2)."""

from typing import Any

from sqlalchemy import JSON, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from lore.core.db.base import Base


class VaultMeta(Base):
    __tablename__ = "vault_meta"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)


def get_meta(session: Session, key: str) -> Any:
    return session.scalar(select(VaultMeta.value).where(VaultMeta.key == key))


def set_meta(session: Session, key: str, value: Any) -> None:
    row = session.get(VaultMeta, key)
    if row is None:
        session.add(VaultMeta(key=key, value=value))
    else:
        row.value = value
