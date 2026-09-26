"""Operator map endpoints: GeoJSON layers plus the Leaflet UI page (EM-072)."""
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse

from src.database import Database
from src.services.map_layers import MapLayerError, build_layer, layer_catalog

# Shipped with the package: src/routes/../static/operator_map.html
MAP_PAGE = Path(__file__).resolve().parent.parent / "static" / "operator_map.html"


def register_map_layer_routes(api: FastAPI, database: Database, settings: Any) -> None:
    """Attach the operator map page and its toggleable GeoJSON layer feeds."""

    @api.get("/", tags=["ui"], include_in_schema=False)
    def root() -> RedirectResponse:
        """Send operators straight to the main map."""
        return RedirectResponse(url="/ui")

    @api.get("/ui", tags=["ui"], response_class=FileResponse)
    def operator_map() -> FileResponse:
        """Main operator map: fires, horizon polygons, fuel, silent zones,
        resources and roads with layer toggles and a 30/60/120-min slider."""
        return FileResponse(MAP_PAGE, media_type="text/html")

    @api.get("/api/v1/map/layers", tags=["map"])
    def map_layers() -> dict[str, Any]:
        """Catalog of the toggleable layers rendered on the operator map."""
        layers = layer_catalog()
        return {"count": len(layers), "layers": layers}

    @api.get("/api/v1/map/layers/{layer_key}", tags=["map"])
    def map_layer_features(
        layer_key: str,
        horizon_minutes: int | None = Query(default=None, ge=1),
        event_key: str | None = None,
    ) -> dict[str, Any]:
        """GeoJSON FeatureCollection for one layer (forecasts are filterable)."""
        try:
            with database.session() as session:
                return build_layer(
                    session, settings, layer_key, horizon_minutes, event_key
                )
        except MapLayerError as exc:
            raise HTTPException(
                status_code=404,
                detail={"status": "error", "error": str(exc)},
            ) from exc
