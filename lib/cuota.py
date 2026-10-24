"""Ledger de cuota de la YouTube Data API v3 (decisión cerrada nº 8).

Toda llamada real a la API pasa por aquí: se registra endpoint, coste, resumen
de parámetros (nunca la clave) y resultado HTTP — la API cobra la unidad
también cuando la llamada falla, así que el fallo se registra igual.
El presupuesto de search.list (100 unidades/llamada) es 0 por defecto: sin búsquedas. Nada de la
fábrica llama a search.list; el guardián se queda por si algo vuelve a hacerlo.

Vivía en `lib/lectura_youtube/quota.py`, el paquete de lectura del buscador del estudio. Pasó aquí en
OC1.1 (fila 302), al borrarse el buscador, porque la fábrica también lo usa: `canal.py` lee el estado
público del canal (`channels.list`, 1 unidad) a través de este ledger.

Prohibido el reintento automático contra la API (lista negra del proyecto):
este módulo no reintenta jamás; registrar el fallo y decidir si se sigue o se
para es del llamante.
"""

from __future__ import annotations

from datetime import datetime, timezone

# Costes oficiales por endpoint (unidades de cuota)
ENDPOINT_COSTS = {
    "videos.list": 1,
    "channels.list": 1,
    "playlistItems.list": 1,
    "search.list": 100,
}

DAILY_QUOTA = 10_000


class SearchBudgetExceeded(RuntimeError):
    """El presupuesto configurado para search.list no cubre una llamada más."""


class QuotaLedger:
    """Registro en memoria del gasto de cuota; se embebe en el JSON de salida."""

    def __init__(self, search_budget_units: int = 0) -> None:
        self.search_budget_units = int(search_budget_units)
        self.calls: list[dict] = []
        self.skipped: list[dict] = []
        self.served_from_cache: list[dict] = []
        self.total_units = 0
        self.search_units_spent = 0
        self.cache_hits = 0

    def cost_of(self, endpoint: str) -> int:
        return ENDPOINT_COSTS.get(endpoint, 1)

    def check_search_budget(self) -> None:
        """Comprueba ANTES de llamar que search.list cabe en el presupuesto; si no, lanza excepción."""
        cost = self.cost_of("search.list")
        if self.search_units_spent + cost > self.search_budget_units:
            raise SearchBudgetExceeded(
                f"search.list cuesta {cost} u y el presupuesto es {self.search_budget_units} u "
                f"(gastadas {self.search_units_spent} u): no se llama"
            )

    def record_call(
        self, endpoint: str, params_summary: str, http_status: int | None, error: str | None = None
    ) -> None:
        """Registra una llamada REAL a la API, con o sin éxito."""
        cost = self.cost_of(endpoint)
        self.total_units += cost
        if endpoint == "search.list":
            self.search_units_spent += cost
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "endpoint": endpoint,
            "params": params_summary,
            "coste": cost,
            "http_status": http_status,
        }
        if error:
            entry["error"] = error
        self.calls.append(entry)

    def record_skipped(self, endpoint: str, reason: str) -> None:
        """Registra una llamada NO hecha (presupuesto insuficiente): la decisión también es auditable."""
        self.skipped.append(
            {
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "endpoint": endpoint,
                "coste_evitado": self.cost_of(endpoint),
                "motivo": reason,
            }
        )

    def record_cache_hit(self, endpoint: str = "", params_summary: str = "") -> None:
        """Una respuesta servida desde la caché local: coste 0, pero queda anotada.

        Se registra qué se pidió y no se pagó para que un JSON regenerado desde
        caché no parezca un run que nunca llamó a la API: la unidad se gastó en
        el run anterior y el ledger lo dice.
        """
        self.cache_hits += 1
        if endpoint:
            self.served_from_cache.append(
                {
                    "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "endpoint": endpoint,
                    "params": params_summary,
                    "coste": 0,
                    "coste_si_no_hubiera_cache": self.cost_of(endpoint),
                }
            )

    def cache_only_notice(self) -> str | None:
        """Aviso para el artefacto cuando TODA la evidencia se regeneró desde caché.

        Sin él, `unidades_consumidas: 0` se lee como «este run nunca llamó a la API»,
        cuando lo cierto es que el run original sí pagó esas unidades.
        """
        saved = sum(c["coste_si_no_hubiera_cache"] for c in self.served_from_cache)
        if self.calls or not self.served_from_cache or not saved:
            return None
        return (
            f"regenerado 100 % desde caché: 0 u ahora, {saved} u pagadas en el run original "
            "(ver llamadas_servidas_desde_cache)"
        )

    def to_dict(self) -> dict:
        return {
            "presupuesto_diario": DAILY_QUOTA,
            "presupuesto_search": self.search_budget_units,
            "unidades_consumidas": self.total_units,
            "unidades_search": self.search_units_spent,
            "aciertos_de_cache": self.cache_hits,
            "unidades_ahorradas_por_cache": sum(c["coste_si_no_hubiera_cache"] for c in self.served_from_cache),
            "politica_reintentos": "prohibido el reintento automático contra la API (lista negra)",
            "llamadas": self.calls,
            "llamadas_servidas_desde_cache": self.served_from_cache,
            "llamadas_omitidas_por_presupuesto": self.skipped,
        }
