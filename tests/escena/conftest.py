"""Fixtures del motor de escena (F6.2a). Las herramientas están en `utiles_escena.py`."""

from __future__ import annotations

from pathlib import Path

import pytest
from utiles_escena import CSS_PRUEBA, dibuja_assets, guion_min

from lib.escena import compone


@pytest.fixture(scope="session")
def assets_min(tmp_path_factory) -> dict[str, Path]:
    """Las imágenes del GUION mínimo, dibujadas una vez por sesión."""
    return dibuja_assets(tmp_path_factory.mktemp("assets-min"))


@pytest.fixture
def composicion(tmp_path, assets_min) -> Path:
    """La composición del GUION mínimo con el CSS del canal de prueba, recién escrita. Devuelve su carpeta."""
    return compone.compone(guion_min(), assets_min, CSS_PRUEBA, tmp_path / "comp").parent
