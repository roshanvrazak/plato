import asyncio
import secrets
import typer
import asyncpg
from .settings import settings
from .auth import hash_api_key

cli = typer.Typer()


async def _create_tenant(name: str, budget: int, models: list[str]) -> str:
    api_key = "plato_" + secrets.token_urlsafe(32)
    key_hash = hash_api_key(api_key)
    conn = await asyncpg.connect(settings.database_url)
    try:
        await conn.execute(
            "INSERT INTO tenants (name, api_key_hash, daily_token_budget, allowed_models) "
            "VALUES ($1, $2, $3, $4)",
            name, key_hash, budget, models,
        )
    finally:
        await conn.close()
    return api_key


@cli.command()
def create(
    name: str,
    budget: int = typer.Option(100000),
    model: list[str] = typer.Option(["local-llama3"]),
):
    """Create a tenant. The API key is printed ONCE — store it."""
    api_key = asyncio.run(_create_tenant(name, budget, model))
    typer.echo(f"Tenant '{name}' created.")
    typer.echo(f"API key (store this now, it won't be shown again):\n  {api_key}")


if __name__ == "__main__":
    cli()