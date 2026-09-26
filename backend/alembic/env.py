import os

from sqlalchemy import engine_from_config, pool

from alembic import context
from vibecheck.db.models import Base

config = context.config
target_metadata = Base.metadata

# URL priority: passed in by vibecheck > VIBECHECK_DATABASE_URL > alembic.ini.
_url = config.attributes.get("vibecheck_url") or os.environ.get("VIBECHECK_DATABASE_URL")
if _url:
    config.set_main_option("sqlalchemy.url", _url.replace("%", "%%"))


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
