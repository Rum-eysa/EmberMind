"""Gelistirme yardimcisi: API'yi EM-012/015/017/018/072/073/103/104 demo verisiyle yerelde calistirir.

Kullanim:
    python scripts/demo_api.py                  # sentetik senaryo tohumi 7
    python scripts/demo_api.py --seed 42 --preset firtina
    -> http://127.0.0.1:8000/ui          (operator map, EM-072)
    -> http://127.0.0.1:8000/panel       (commander panel, EM-073)
    -> http://127.0.0.1:8000/inventory   (kaynak envanteri, EM-103)
    -> http://127.0.0.1:8000/styleguide  (tasarim sistemi, EM-075)
    -> http://127.0.0.1:8000/docs        (Swagger UI)
    -> http://127.0.0.1:8000/api/v1/fires (birlestirilmis VIIRS/MODIS kumeleri)

EM-104: `--seed` ayni kalrsa ayni sentetik veri uretilir (iletişim kesinti
bolgeleri, ruzgar gecmisi, kaynak dagilimi); tum kayitlar SENTETIK etiketlidir.
"""
import argparse  # noqa: E402
import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime import timedelta  # noqa: E402

import uvicorn  # noqa: E402
from shapely import affinity, wkt as shapely_wkt  # noqa: E402

from src.fastapi_app import create_fastapi_app  # noqa: E402
from src.models.fire import FireCluster, FireObservation, FirmsSyncStatus  # noqa: E402
from src.models.fwi import FireWeatherIndex  # noqa: E402
from src.models.inventory import SuppressionResource  # noqa: E402
from src.models.land_cover import LandCoverDataPoint  # noqa: E402
from src.models.road_network import CrewBase, RoadSegment, RoadClosure  # noqa: E402
from src.models.spatial import FireEvent, SilentRegion  # noqa: E402
from src.services.fwi import fwi_risk_category  # noqa: E402
from src.services.spread import predict_spread  # noqa: E402
from src.services.spread_metrics import (  # noqa: E402
    evaluate_forecast_against_actual,
)
from src.services.spread_trigger import auto_trigger_forecasts  # noqa: E402
from src.services.synthetic import (  # noqa: E402
    PRESETS,
    SyntheticError,
    build_dataset,
    persist_dataset,
    record_run,
)
from src.utils.timeutils import utc_now  # noqa: E402

api = create_fastapi_app("testing")


def seed_demo_data() -> None:
    """Load a small merged-satellite demo dataset into the in-memory database."""
    database = api.state.database
    database.create_all()
    now = utc_now()
    with database.session() as session:
        session.add(
            FireCluster(
                cluster_key="demo-merged-001",
                latitude=38.9005,
                longitude=27.5005,
                observation_count=2,
                max_frp=30.0,
                first_seen_at=now.replace(hour=12, minute=0, second=0),
                last_seen_at=now.replace(hour=12, minute=30, second=0),
                sources="Suomi NPP;Terra",
                latency_minutes=35.0,
                deduplicated_count=1,
            )
        )
        session.add(
            FireObservation(
                source_id="demo-viirs-001",
                cluster_key="demo-merged-001",
                latitude=38.9000,
                longitude=27.5000,
                observed_at=now.replace(hour=12, minute=0, second=0),
                frp=12.5,
                confidence=50.0,
                satellite="Suomi NPP",
                instrument="VIIRS",
                product="VIIRS_SNPP_NRT",
                published_at=now.replace(hour=12, minute=35, second=0),
                latency_minutes=35.0,
            )
        )
        session.add(
            FireObservation(
                source_id="demo-modis-001",
                cluster_key="demo-merged-001",
                latitude=38.9010,
                longitude=27.5010,
                observed_at=now.replace(hour=12, minute=30, second=0),
                frp=30.0,
                confidence=80.0,
                satellite="Terra",
                instrument="MODIS",
                product="MODIS_Terra_CorrectedAnomalies",
                published_at=now.replace(hour=13, minute=20, second=0),
                latency_minutes=50.0,
            )
        )
        session.add(
            FireCluster(
                cluster_key="demo-modis-only-002",
                latitude=37.2400,
                longitude=28.0600,
                observation_count=1,
                max_frp=18.4,
                first_seen_at=now.replace(hour=14, minute=5, second=0),
                last_seen_at=now.replace(hour=14, minute=5, second=0),
                sources="Aqua",
                latency_minutes=42.0,
                deduplicated_count=0,
            )
        )
        session.add(
            FireObservation(
                source_id="demo-modis-002",
                cluster_key="demo-modis-only-002",
                latitude=37.2400,
                longitude=28.0600,
                observed_at=now.replace(hour=14, minute=5, second=0),
                frp=18.4,
                confidence=90.0,
                satellite="Aqua",
                instrument="MODIS",
                product="MODIS_Aqua_CorrectedAnomalies",
                published_at=now.replace(hour=14, minute=47, second=0),
                latency_minutes=42.0,
            )
        )
        session.add(
            FirmsSyncStatus(
                source="NASA FIRMS",
                last_success_at=now,
                last_observation_count=3,
            )
        )
        # --- EM-072 operator map demo layers ---
        session.add(
            SilentRegion(
                region_name="Demo Sessiz Bolge",
                reason="uydu uctan gecis boslugu (demo)",
                min_lat=38.4,
                max_lat=38.7,
                min_lon=27.2,
                max_lon=27.6,
                geometry_wkt="",
                is_active=True,
            )
        )
        session.add(
            CrewBase(
                base_key="demo-base-001",
                name="Demo Mudahale Merkezi (EM-072)",
                latitude=38.85,
                longitude=27.65,
                crew_type="first_response",
                available=True,
            )
        )
        session.add(
            LandCoverDataPoint(
                cluster_key="demo-merged-001",
                latitude=38.9005,
                longitude=27.5005,
                corine_code=311,
                land_cover_class="kizilcam",
                fuel_model="FM10_RedPine",
                spread_factor=1.8,
                fetched_at=now,
            )
        )
        session.add(
            RoadSegment(
                segment_key="demo-seg-001",
                osm_way_id=900001,
                from_node_id=1,
                to_node_id=2,
                from_lat=38.85,
                from_lon=27.65,
                to_lat=38.9,
                to_lon=27.5,
                name="D330 (demo)",
                highway="primary",
                length_km=18.4,
                max_speed_kmh=90.0,
                one_way=False,
                fetched_at=now,
            )
        )
        # --- EM-073 komutan paneli: FWI bölge günleri + aktif olay/kapanma ---
        today = now.date()
        fwi_zones = {
            "FWI_DEMO_BATI": [22.0, 34.0, 41.0],  # eşik (30) 2. gün aşılır
            "FWI_DEMO_DOGU": [8.0, 12.0, 15.0],  # hiç aşım yok
        }
        for zone, series in fwi_zones.items():
            for offset, fwi in enumerate(series):
                session.add(
                    FireWeatherIndex(
                        zone_key=zone,
                        region_name="Demo bölge (Ege sahili)",
                        day=today - timedelta(days=len(series) - 1 - offset),
                        fwi=fwi,
                        isi=fwi * 0.6,
                        risk_category=fwi_risk_category(fwi),
                        drought_category="moderate" if fwi < 30 else "severe",
                    )
                )
        session.add(
            FireEvent(
                event_key="demo-event-001",
                name="Demo Aktif Olay (Menteşe)",
                latitude=37.5,
                longitude=28.0,
                min_lat=37.4,
                max_lat=37.6,
                min_lon=27.9,
                max_lon=28.1,
                geometry_wkt="POLYGON((27.9 37.4, 28.1 37.4, 28.1 37.6, 27.9 37.6, 27.9 37.4))",
                status="active",
                started_at=now - timedelta(hours=3),
            )
        )
        session.add(
            RoadClosure(
                segment_key="demo-seg-001",
                reason="yangın nedeniyle kapalı (demo)",
                status="active",
                reported_at=now - timedelta(hours=1),
            )
        )
        # --- EM-103 koordinatör kaynak envanteri ---
        for asset in (
            SuppressionResource(
                resource_key="EKIP-DEMO-01",
                name="Menteşe Arazöz Timi",
                resource_type="crew",
                latitude=37.5,
                longitude=28.0,
                base_key="demo-base-001",
                country="TR",
                status="available",
                capacity=25.0,
                capacity_unit="personnel",
            ),
            SuppressionResource(
                resource_key="EKIP-DEMO-02",
                name="Ula Piyade Timi",
                resource_type="crew",
                latitude=37.03,
                longitude=28.35,
                base_key="demo-base-001",
                country="TR",
                status="deployed",
                capacity=30.0,
                capacity_unit="personnel",
            ),
            SuppressionResource(
                resource_key="HELI-DEMO-01",
                name="Dalaman Helikopter 1",
                resource_type="helicopter",
                latitude=36.71,
                longitude=28.52,
                country="TR",
                status="available",
                capacity=12.0,
                capacity_unit="tons",
            ),
            SuppressionResource(
                resource_key="IHA-DEMO-01",
                name="İHA Keşif-1",
                resource_type="uav",
                latitude=38.85,
                longitude=27.65,
                base_key="demo-base-001",
                country="TR",
                status="maintenance",
                capacity=4.0,
                capacity_unit="uçuş saati",
            ),
        ):
            session.add(asset)
        session.commit()
        # EM-015 spread engine: 30/60/120 dk risk poligonlari (demo kumesi icin).
        spread_result = predict_spread(
            session,
            api.state.settings,
            {
                "latitude": 38.9005,
                "longitude": 27.5005,
                "event_key": "demo-merged-001",
                "wind_speed_kmh": 25.0,
                "wind_from_deg": 225.0,
                "air_temp_c": 31.0,
                "relative_humidity_pct": 22.0,
                "fuel_moisture_pct": 12.0,
                "slope_deg": 15.0,
                "aspect_deg": 180.0,
                "fuel_model": "FM10_RedPine",
            },
        )
        # EM-017 degerlendirme: 120 dk tahmin poligonu kaydirilip olceklendirerek
        # sentetik "gercek cevre" uretilir; IoU / alan / varis zamani metrikleri
        # spread_evaluation_metrics tablosuna yazilir (surum bazli ozet icin).
        predicted = shapely_wkt.loads(spread_result["forecasts"][-1]["geometry_wkt"])
        scale_origin = (
            predicted.centroid.x + 0.0015,
            predicted.centroid.y - 0.0010,
        )
        actual_poly = affinity.scale(predicted, 1.18, 0.92, origin=scale_origin)
        dlat_m = 111320.0
        dlon_m = 111320.0 * math.cos(math.radians(38.9005))
        evaluate_forecast_against_actual(
            session,
            event_key="demo-merged-001",
            actual_perimeter_wkt=actual_poly.wkt,
            actual_area_ha=round(actual_poly.area * dlat_m * dlon_m / 10000.0, 2),
            actual_arrival_time=now + timedelta(minutes=95),
        )
        # EM-018 otomatik tetikleme: forecastsız aktif olaylara (demo-event-001)
        # debounce korumalı taramayla ilk yayılım tahmini üretilir.
        sweep = auto_trigger_forecasts(session, api.state.settings)
        print(
            f"[EM-018] tetikleme taraması: kontrol={sweep['checked']} "
            f"çalışan={sweep['triggered_count']} "
            f"olaylar={[t['event_key'] for t in sweep['triggered']]}"
        )


def seed_synthetic_scenario(seed: int, preset: str) -> dict:
    """EM-104: deterministik sentetik senaryoyu üretip kalıcı tabloları yazar.

    Ayni `seed` + ayni `preset` her kosuda birebir ayni veriyi verir; her
    kayit SENTETIK etiketi tasir (not: ana demo verisinden ayrtılır).
    """
    if preset not in PRESETS:
        raise SystemExit(f"bilinmeyen preset '{preset}'; secenekler: {sorted(PRESETS)}")
    database = api.state.database
    dataset = build_dataset(seed, preset=preset)
    with database.session() as session:
        counts = persist_dataset(session, dataset)
        record_run(session, dataset, persisted=True, preset=preset)
        session.commit()
    meta = dataset["meta"]
    print(
        f"[EM-104] sentetik senaryo: seed={seed} preset={preset} "
        f"tag={meta['scenario_tag']} kayit={meta['record_count']} "
        f"result_hash={meta['result_hash'][:12]}... etiketli alanlar: {counts}"
    )
    return dataset


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EmberMind demo API (EM-104)")
    parser.add_argument(
        "--seed",
        type=int,
        default=7,
        help="sentetik uretec tohumi (ayni seed ayni sonuc)",
    )
    parser.add_argument(
        "--preset", default="standart", help=f"senaryo preset'i: {sorted(PRESETS)}"
    )
    parser.add_argument(
        "--no-synthetic", action="store_true", help="sentetik senaryoyu atla"
    )
    args = parser.parse_args()
    # The app defines a custom lifespan, so seed up-front (the in-memory
    # SQLite uses StaticPool, so the data survives across sessions inside
    # this process).
    seed_demo_data()
    if not args.no_synthetic:
        try:
            seed_synthetic_scenario(args.seed, args.preset)
        except SyntheticError as exc:
            raise SystemExit(f"sentetik senaryo hatasi: {exc}") from exc
    uvicorn.run(api, host="127.0.0.1", port=8000, log_level="info")
