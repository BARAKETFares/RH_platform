"""Utilitaires de gestion des fichiers uploadés."""
import os
import uuid
import imghdr
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import current_app


def allowed_file(filename: str) -> bool:
    """Vérifie que l'extension est dans la liste blanche."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in current_app.config["ALLOWED_EXTENSIONS"]


def save_upload(file, subfolder: str) -> str:
    """
    Sauvegarde un fichier uploadé de manière sécurisée.

    Returns:
        Chemin relatif du fichier depuis UPLOAD_FOLDER.
    """
    if not file or not allowed_file(file.filename):
        raise ValueError("Fichier invalide ou extension non autorisée")

    original_name = secure_filename(file.filename)
    ext = original_name.rsplit(".", 1)[-1].lower()
    unique_name = f"{uuid.uuid4().hex}.{ext}"

    dest_dir = Path(current_app.config["UPLOAD_FOLDER"]) / subfolder
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest_path = dest_dir / unique_name
    file.save(dest_path)

    return str(Path(subfolder) / unique_name)


def format_file_size(size_bytes: int | None) -> str:
    """Filtre Jinja2 : formate une taille en octets lisiblement."""
    if not size_bytes:
        return "—"
    for unit in ["o", "Ko", "Mo", "Go"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} To"
