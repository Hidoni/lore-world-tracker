"""Alembic environment: the caller (``lore.core.db.migrate``) supplies the connection, inside a
transaction it owns, plus the target metadata and the object filter."""

from alembic import context

config = context.config
connection = config.attributes.get("connection")
if connection is None:
    raise RuntimeError(
        "Lore migrations run through lore.core.db.migrate (`lore vault migrate`, `lore db ...`)"
    )

context.configure(
    connection=connection,
    target_metadata=config.attributes["target_metadata"],
    include_object=config.attributes["include_object"],
    render_as_batch=True,
    compare_type=True,
)

with context.begin_transaction():
    context.run_migrations()
