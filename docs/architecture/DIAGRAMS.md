# EmberMind — Mimari Diyagramlar

Bu dosya, sistemin akışını referans görsellerdeki tarzda (lavanta temalı
**Mermaid** sequence ve bileşen diyagramları) anlatır. Qoder markdown
önizlemesi Mermaid'i doğal olarak çizer; harici olarak
[Mermaid Live Editor](https://mermaid.live)'e de yapıştırabilirsiniz.

> Not: EM-023 analiz önbelleği süreç-içi (in-process) bir parmak-izi/TTL
> önbelleğidir; Redis yalnızca Celery broker/result backend'i olarak kullanılır.

## 1. Sıra Diyagramı — Tehdit/Maruziyet Analizi (EM-023)

Yayılım tahmini poligonlarıyla yerleşim/yol/enerji hatlarını kesiştirip
enterpolasyonlu `T+dk` ilk-etki zamanı ve öncelik skoru üretme akışı.

```mermaid
%%{init: {'theme':'base','themeVariables':{'primaryColor':'#ece7f7','primaryBorderColor':'#7e57c2','lineColor':'#7e57c2','textColor':'#2b2b2b','actorBkg':'#ece7f7','actorBorder':'#7e57c2','signalColor':'#5e35b1','noteBkgColor':'#f3effb','noteBorderColor':'#b39ddb'}}}%%
sequenceDiagram
    autonumber
    actor Op as Operatör
    participant UI as Operatör Haritası<br/>(operator_map.html)
    participant API as FastAPI WebAPI
    participant Exp as exposure servisi
    participant Cache as TTL önbellek<br/>(parmak izi)
    participant DB as PostgreSQL
    participant OV as Overpass / OSM
    participant Cel as Celery (beat+worker)

    Note over Cel,DB: Pipeline: FIRMS → kümeleme → yayılım tahmini (30/60/120 dk poligon) → DB
    Cel->>DB: FireForecast yaz (geometry_wkt, rate, spread_dir)

    Op->>UI: "Tehdit Altındaki Yapılar" katmanını aç
    UI->>API: GET /api/v1/exposure?event_key=...
    API->>Exp: analyze_exposure(session, settings, event_key)
    Exp->>DB: son tahmin poligonları + aday elemanlar (bbox ön-filtre)
    Exp->>Cache: parmak izi gecer mi?
    alt cache HIT
        Cache-->>Exp: hazır sonuç
    else cache MISS
        Exp->>Exp: shapely intersects + T+dk enterpolasyon + öncelik skoru
        Exp->>Cache: TTL 60sn yaz
    end
    Exp-->>API: [{asset, first_impact_minutes, priority_score, source}]
    API-->>UI: JSON (öncelik sıralı)
    UI-->>Op: mor noktalar + T+X rozetleri + sıralı liste

    Note over Op,UI: ilk kez varlık yoksa içe aktar
    Op->>UI: /exposure/import (bbox)
    UI->>API: POST /api/v1/exposure/import
    API->>API: bbox doğrula (min>max? alan>limit? → 400)
    API->>Exp: sync_exposed_assets(bbox)
    Exp->>OV: Overpass QL (place + power)
    alt Overpass OK
        OV-->>Exp: node/way JSON
        Exp->>DB: ExposedAsset upsert (named/partial bayrağı)
    else Overpass 503 / erişim yok
        Exp->>DB: demo-fallback varlıklar (source=demo-fallback)
    end
    Exp-->>API: {assets_fetched, kept, saved}
    API-->>UI: 200 özet
```

## 2. Bileşen Diyagramı — Sistem Geneli

Katlama: arayüzler → FastAPI → Celery (zamanlama/işleme) → iş servisleri →
veri katmanı → harici kaynaklar → gözlemlenebilirlik.

```mermaid
%%{init: {'theme':'base','themeVariables':{'primaryColor':'#ece7f7','primaryBorderColor':'#7e57c2','lineColor':'#7e57c2','clusterBkg':'#f6f3fc','clusterBorder':'#b39ddb','fontFamily':'Segoe UI, Arial'}}}%%
flowchart LR
    subgraph Clients["Arayüzler"]
        UI["Operatör Haritası<br/>operator_map.html"]
        PANEL["Komutan Paneli<br/>risk_panel.html"]
        INV["Kaynak Envanteri<br/>inventory.html"]
        SWAG["/docs (Swagger)"]
    end

    subgraph App["FastAPI WebAPI"]
        ROUTES["routes/*"]
        MAP["map_layers<br/>(9 katman kataloğu)"]
        EXPSVC["exposure servisi"]
        FWI["fwi servisi"]
        QUAL["data_quality / governance"]
    end

    subgraph Async["Celery"]
        BEAT["beat scheduler"]
        WORK["workers"]
    end

    subgraph Svc["İş servisleri"]
        MERGE["satellite_merge"]
        SPREAD["spread engine<br/>Rothermel + uncertainty + barriers"]
        TRIG["spread_trigger"]
        TOPO["topography / land_cover<br/>weather / road_network"]
    end

    subgraph Data["Veri"]
        PG[("PostgreSQL<br/>geometrik tablolar")]
        RD[("Redis<br/>broker / result")]
    end

    subgraph Ext["Harici Kaynaklar"]
        FIRMS["NASA FIRMS"]
        OW["OpenWeather"]
        SRTM["USGS / SRTM"]
        COP["Copernicus CORINE"]
        OSM["Overpass / OSM"]
        EFFIS["EFFIS"]
    end

    OBS["Prometheus"]
    GRAF["Grafana"]

    UI --> ROUTES
    PANEL --> ROUTES
    INV --> ROUTES
    SWAG --> ROUTES

    ROUTES --> MAP
    ROUTES --> EXPSVC
    ROUTES --> FWI
    ROUTES --> QUAL
    ROUTES -->|"/exposure/import"| EXPSVC

    MAP --> PG
    EXPSVC --> PG
    EXPSVC -->|Overpass| OSM
    FWI --> PG

    BEAT -->|periyodik| WORK
    WORK --> RD
    RD --> WORK
    WORK --> MERGE
    WORK --> TOPO
    WORK --> TRIG
    TRIG --> SPREAD

    MERGE --> FIRMS
    TOPO --> OW
    TOPO --> SRTM
    TOPO --> COP
    TOPO --> OSM
    WORK --> EFFIS

    MERGE --> PG
    SPREAD -->|"FireForecast"| PG
    TOPO --> PG

    ROUTES -->|"/metrics"| OBS
    OBS --> GRAF
```
