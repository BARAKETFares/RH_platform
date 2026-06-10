"""
CLI Flask — commandes de gestion de l'application.

Usage :
    flask db init          # Initialise Alembic
    flask db migrate -m "msg"  # Génère une migration
    flask db upgrade       # Applique les migrations

    flask seed             # Injecte les données de référence
    flask create-admin     # Crée le premier compte Admin
    flask routes           # Liste toutes les routes enregistrées
"""
import click
from flask.cli import with_appcontext
from app import create_app
from app.extensions import db

app = create_app()


@app.cli.command("seed")
@with_appcontext
def seed_database():
    """Injecte les données de référence initiales."""
    from scripts.seed_db import run_seed
    run_seed()
    click.echo("Base de données initialisée avec les données de référence.")


@app.cli.command("create-admin")
@click.option("--email",    prompt="Email Admin",          help="Adresse email")
@click.option("--password", prompt=True, hide_input=True,
              confirmation_prompt=True,                     help="Mot de passe")
@with_appcontext
def create_admin(email: str, password: str):
    """Crée le premier compte Administrateur."""
    from scripts.create_admin import create_admin_user
    create_admin_user(email=email, password=password)
    click.echo(f"Compte Admin créé : {email}")


@app.cli.command("check-config")
@with_appcontext
def check_config():
    """Affiche la configuration active (sans les valeurs secrètes)."""
    from flask import current_app
    safe_keys = [k for k in current_app.config if not any(
        s in k for s in ["SECRET", "PASSWORD", "KEY", "TOKEN"]
    )]
    for key in sorted(safe_keys):
        click.echo(f"  {key:45s} = {current_app.config[key]}")


if __name__ == "__main__":
    app.run()
