"""
Подготовка геоданных по районам.

Запуск:
    python prepare_data.py

Стратегия получения границ:
  Шаг 1. ОДИН запрос features_from_place: тянем все админ-границы
         (boundary=administrative, admin_level=8/9) внутри Нижнего
         Новгорода. Это надёжно отсекает здания и точки —
         возвращаются только настоящие районы.
  Шаг 2. Для районов, не нашедшихся на шаге 1 (вдруг отсутствуют
         в OSM с нужным admin_level), запасной путь — geocode_to_gdf
         с фильтрами: только Polygon/MultiPolygon, площадь > 1 км²,
         bbox внутри НН. Так мы не подхватим МФЦ или другую точку.
  Шаг 3. Ручные полигоны из DISTRICT_POLYGONS — поверх всего, если
         какой-то район нужно подкрутить руками.
  Шаг 4. Квадрат-заглушка, если ничего не сработало.

После любых правок — перезапустить скрипт и обновить страницу Streamlit.
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path

from modules.districts import DISTRICTS

OUT_PATH = Path(__file__).parent / "data" / "districts.geojson"

# Грубая ограничивающая рамка Нижнего Новгорода.
NN_BBOX = {"min_lon": 43.5, "max_lon": 44.3,
           "min_lat": 56.0, "max_lat": 56.5}

# Минимальная площадь района в квадратных градусах. ~0.0001 deg² ≈ 1 км².
# Здания заметно меньше, любой реальный район — заметно больше.
MIN_DISTRICT_AREA_DEG2 = 0.0001


# ----------------------------------------------------------------------
# Ручные полигоны районов (опционально, переопределяют OSM).
# Формат: id_района -> [(lat, lon), (lat, lon), ...]
# Точки — последовательно по контуру. Замыкать кольцо не нужно.
# ----------------------------------------------------------------------
DISTRICT_POLYGONS: dict[str, list[tuple[float, float]]] = {
    # Пример (закомментирован):
    # "sormovsky": [
    #     (56.316447, 43.653466),
    #     (56.423042, 43.810352),
    #     (56.357674, 43.907664),
    # ],
}


# Центры районов — для квадратной заглушки. (lon, lat)
CENTERS_LON_LAT: dict[str, tuple[float, float]] = {
    "avtozavodsky":  (43.890, 56.230),
    "kanavinsky":    (43.945, 56.325),
    "leninsky":      (43.935, 56.290),
    "moskovsky":     (43.890, 56.350),
    "nizhegorodsky": (44.020, 56.325),
    "priokskiy":     (43.985, 56.245),
    "sovetsky":      (44.030, 56.280),
    "sormovsky":     (43.840, 56.355),
}


# ----------------------------------------------------------------------
# Конструкторы геометрий
# ----------------------------------------------------------------------
def _polygon_from_latlon(vertices: list[tuple[float, float]]) -> dict:
    """(lat, lon) список -> GeoJSON-полигон."""
    ring = [[lon, lat] for (lat, lon) in vertices]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}


def _square_around(lon: float, lat: float, half: float = 0.025) -> dict:
    ring = [
        [lon - half, lat - half],
        [lon + half, lat - half],
        [lon + half, lat + half],
        [lon - half, lat + half],
        [lon - half, lat - half],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


# ----------------------------------------------------------------------
# Валидация — отсекаем здания, точки и районы из других городов
# ----------------------------------------------------------------------
def _bbox_in_nn(bounds: tuple[float, float, float, float]) -> bool:
    minx, miny, maxx, maxy = bounds
    return (NN_BBOX["min_lon"] <= minx and maxx <= NN_BBOX["max_lon"]
            and NN_BBOX["min_lat"] <= miny and maxy <= NN_BBOX["max_lat"])


def _looks_like_district(geom) -> bool:
    """Похоже ли это вообще на район, а не на здание/точку?"""
    if geom is None:
        return False
    if geom.geom_type not in ("Polygon", "MultiPolygon"):
        return False
    if geom.area < MIN_DISTRICT_AREA_DEG2:
        return False
    if not _bbox_in_nn(geom.bounds):
        return False
    return True


# ----------------------------------------------------------------------
# Шаг 1. Одним запросом — все админ-границы внутри НН
# ----------------------------------------------------------------------
def _fetch_admin_boundaries() -> dict[str, object]:
    """
    Тянет все boundary=administrative в Нижнем Новгороде с admin_level 8 и 9.
    Возвращает dict {имя -> shapely-геометрия}.
    """
    try:
        import osmnx as ox
    except ImportError:
        warnings.warn("osmnx не установлен — пропускаю OSM")
        return {}

    print("OSM: запрашиваю административные границы НН...")
    try:
        gdf = ox.features_from_place(
            "Нижний Новгород, Россия",
            tags={"boundary": "administrative", "admin_level": ["8", "9"]},
        )
    except Exception as e:  # noqa: BLE001
        warnings.warn(f"OSM features_from_place: {e}")
        return {}

    index: dict[str, object] = {}
    for _, row in gdf.iterrows():
        name = row.get("name") or ""
        geom = row.geometry
        if not name or not _looks_like_district(geom):
            continue
        # первый встреченный имеет приоритет
        index.setdefault(name, geom)

    print(f"OSM: получено {len(index)} админ-объектов с именами")
    return index


def _find_in_index(name_ru: str, index: dict[str, object]) -> object | None:
    """Найти геометрию по имени с разными вариантами написания."""
    for cand in (f"{name_ru} район", name_ru, f"район {name_ru}"):
        if cand in index:
            return index[cand]
    return None


# ----------------------------------------------------------------------
# Шаг 2. Запасной путь — geocode_to_gdf с перебором результатов
# ----------------------------------------------------------------------
def _try_osm_single(district_name_ru: str) -> object | None:
    """
    Если в общем индексе района не нашлось, пробуем геокодинг
    с перебором which_result и фильтрами. Так мы пропускаем
    точки/здания и берём первый подходящий полигон.
    """
    try:
        import osmnx as ox
    except ImportError:
        return None

    queries = [
        f"{district_name_ru} район, Нижний Новгород, Нижегородская область, Россия",
        f"{district_name_ru} район, Нижний Новгород, Россия",
    ]

    for query in queries:
        for which in range(1, 5):  # пробуем первые 4 кандидата
            try:
                gdf = ox.geocode_to_gdf(query, which_result=which)
            except Exception:  # noqa: BLE001
                break  # which_result больше нет
            geom = gdf.geometry.iloc[0]
            if _looks_like_district(geom):
                time.sleep(1.0)
                return geom
            # иначе — это здание/точка/чужой город, пробуем следующий
        time.sleep(1.0)

    return None


# ----------------------------------------------------------------------
# Основной запуск
# ----------------------------------------------------------------------
def main() -> int:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    osm_index = _fetch_admin_boundaries()

    features = []
    counters = {"manual": 0, "osm_index": 0, "osm_single": 0, "fallback": 0}

    for d in DISTRICTS:
        d_id = d["id"]

        # 1) ручные точки — приоритет
        if d_id in DISTRICT_POLYGONS and DISTRICT_POLYGONS[d_id]:
            geom = _polygon_from_latlon(DISTRICT_POLYGONS[d_id])
            source = "manual"
        else:
            # 2) общий OSM-индекс
            geom_obj = _find_in_index(d["name_ru"], osm_index)
            if geom_obj is not None:
                geom = geom_obj.__geo_interface__
                source = "osm_index"
            else:
                # 3) запасной OSM-запрос
                geom_obj = _try_osm_single(d["name_ru"])
                if geom_obj is not None:
                    geom = geom_obj.__geo_interface__
                    source = "osm_single"
                else:
                    # 4) квадрат
                    lon, lat = CENTERS_LON_LAT[d_id]
                    geom = _square_around(lon, lat)
                    source = "fallback"

        counters[source] += 1
        features.append({
            "type": "Feature",
            "id": d_id,
            "properties": {
                "id": d_id,
                "name_ru": d["name_ru"],
                "name_en": d["name_en"],
                "source": source,
            },
            "geometry": geom,
        })
        print(f"  [{source:10s}] {d['name_ru']}")

    geojson = {"type": "FeatureCollection", "features": features}
    OUT_PATH.write_text(
        json.dumps(geojson, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        f"\nГотово: {OUT_PATH}\n"
        f"  Ручные:        {counters['manual']}\n"
        f"  OSM (индекс):  {counters['osm_index']}\n"
        f"  OSM (одиноч.): {counters['osm_single']}\n"
        f"  Заглушка:      {counters['fallback']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())