"""Los flags del CLI llegan a donde dicen que llegan.

Nace el 14-09-2026 de un defecto que costó una producción entera: `--run-all --forzar-subida`
**aceptaba el flag y lo ignoraba**. `argparse` lo declaraba, `--run-all` no protestaba, y dentro
`run_all` llamaba a `stage_upload(run_id)` sin él, así que la guarda de idempotencia paraba la
subida. El episodio rehecho de un canal se quedó en disco 25 minutos mientras el canal conservaba el
vídeo viejo, con el log diciendo «Este run YA está subido».

**Un flag inerte es peor que uno ausente**: con uno ausente el comando falla y te enteras; con uno
inerte el comando sale con éxito y hace otra cosa. Es el mismo patrón que el perfil de ese canal llama
«un punto de inyección inerte», y que el proyecto ya decidió no tolerar en los datos — esto lo
extiende al CLI.

Se comprueba leyendo el AST y no ejecutando el pipeline: `stage_upload` sube a YouTube de verdad, y
una prueba no puede depender de eso.
"""

import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PIPELINE = RAIZ / "pipeline.py"


def _arbol() -> ast.Module:
    return ast.parse(PIPELINE.read_text(encoding="utf-8"))


def _funcion(nombre: str) -> ast.FunctionDef:
    return next(n for n in ast.walk(_arbol()) if isinstance(n, ast.FunctionDef) and n.name == nombre)


def test_run_all_acepta_forzar_subida():
    """Si `run_all` no lo acepta, el flag no puede llegar: es el primer eslabón."""
    argumentos = {a.arg for a in _funcion("run_all").args.args}
    assert "forzar_subida" in argumentos, (
        "`run_all` no acepta `forzar_subida`: el CLI declara --forzar-subida y el flag se perdería "
        "en silencio, que es el defecto del 14-09"
    )


def test_run_all_PROPAGA_el_flag_a_la_subida():
    """El eslabón que faltaba: aceptarlo y no pasarlo es exactamente lo que pasó.

    Se busca la llamada a `stage_upload` dentro de `run_all` y se exige que lleve `forzar=`.
    """
    llamadas = [
        n
        for n in ast.walk(_funcion("run_all"))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "stage_upload"
    ]
    assert llamadas, "`run_all` ya no llama a `stage_upload`: si la subida se movió, actualiza esta prueba"
    for llamada in llamadas:
        claves = {k.arg for k in llamada.keywords}
        assert "forzar" in claves, (
            f"la llamada a `stage_upload` de la línea {llamada.lineno} no pasa `forzar=`: el flag "
            "llega al pipeline y muere ahí"
        )


def test_el_CLI_pasa_forzar_subida_a_run_all():
    """El tercer eslabón: que `main` no se olvide al llamar a `run_all`."""
    fuente = PIPELINE.read_text(encoding="utf-8")
    llamadas = [
        n
        for n in ast.walk(ast.parse(fuente))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "run_all"
    ]
    assert llamadas, "nadie llama a `run_all`"
    assert any("forzar_subida" in {k.arg for k in n.keywords} for n in llamadas), (
        "ninguna llamada a `run_all` pasa `forzar_subida`: el flag se queda en el parser"
    )


def test_CONTROL_sin_subida_tambien_llega_entero():
    """Control de que la prueba mide la cadena y no una casualidad de `forzar_subida`.

    `--sin-subida` recorre exactamente el mismo camino y ya funcionaba: si esta prueba se pusiera
    roja, el problema sería del método de comprobación y no del flag nuevo.
    """
    argumentos = {a.arg for a in _funcion("run_all").args.args}
    assert "sin_subida" in argumentos
    fuente = PIPELINE.read_text(encoding="utf-8")
    llamadas = [
        n
        for n in ast.walk(ast.parse(fuente))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "run_all"
    ]
    assert any("sin_subida" in {k.arg for k in n.keywords} for n in llamadas)
