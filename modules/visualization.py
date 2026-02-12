"""
Построение интерактивной карты районов.

Главная функция — build_district_map(metrics, geojson_path) — возвращает
объект folium.Map, готовый к показу через streamlit-folium.

Каждый район:
  • покрашен в градиенте зелёный → красный по negativity_score (0..1);
  • при наведении показывает tooltip со сводкой;
  • при клике в Streamlit прилетает id района через st_folium return value.
"""
from __future__ import annotations

import json
from pathlib import Path

import branca.colormap as cm
import folium

from modules.mock_data import DistrictMetrics

# Цветовая шкала: зелёный → жёлтый → красный.
# vmin=0 (нет негатива), vmax=1 (всё красным).
COLORMAP = cm.LinearColormap(
    colors=["#2ecc71", "#a3d977", "#f1c40f", "#e67e22", "#e74c3c"],
    vmin=0.0, vmax=1.0,
    caption="Уровень негативной реакции",
)

# Центр карты — географический центр Нижнего Новгорода.
NN_CENTER = (56.296, 43.936)
DEFAULT_ZOOM = 11


def color_for_score(score: float) -> str:
    """Цвет района по итоговой оценке негативности (0..1)."""
    return COLORMAP(max(0.0, min(1.0, score)))


def build_district_map(
    metrics: list[DistrictMetrics],
    geojson_path: str | Path,
    selected_id: str | None = None,
) -> folium.Map:
    """
    Собрать Folium-карту с цветными районами.

    metrics       — сводки по районам (см. mock_data.DistrictMetrics);
    geojson_path  — путь к data/districts.geojson;
    selected_id   — id выбранного района: подсвечиваем его толстой обводкой.
    """
    metrics_by_id = {m.district_id: m for m in metrics}

    with open(geojson_path, "r", encoding="utf-8") as f:
        geojson = json.load(f)

    # Обогащаем properties в GeoJSON значениями из metrics —
    # чтобы они были доступны для tooltip и стилизации.
    for feature in geojson["features"]:
        d_id = feature["properties"]["id"]
        m = metrics_by_id.get(d_id)
        if m is None:
            continue
        feature["properties"].update({
            "score":      m.negativity_score,
            "total":      m.total_posts,
            "negative":   m.negative,
            "neutral":    m.neutral,
            "positive":   m.positive,
            "neg_share":  round(m.neg_share * 100, 1),
        })

    fmap = folium.Map(
        location=NN_CENTER,
        zoom_start=DEFAULT_ZOOM,
        tiles="CartoDB positron",   # светлая нейтральная подложка
        control_scale=True,
    )

    def _style(feature):
        d_id = feature["properties"]["id"]
        score = feature["properties"].get("score", 0.0)
        is_selected = (d_id == selected_id)
        return {
            "fillColor":   color_for_score(score),
            "color":       "#1a5276" if is_selected else "#34495e",
            "weight":      4 if is_selected else 1.5,
            "fillOpacity": 0.72,
        }

    def _highlight(_feature):
        return {"weight": 3, "color": "#1a5276", "fillOpacity": 0.85}

    folium.GeoJson(
        geojson,
        name="Районы",
        style_function=_style,
        highlight_function=_highlight,
        tooltip=folium.GeoJsonTooltip(
            fields=["name_ru", "total", "negative", "neg_share"],
            aliases=["Район:", "Постов всего:", "Негативных:", "Доля негатива, %:"],
            sticky=True,
            labels=True,
            localize=True,
        ),
        # popup нам не нужен — клик ловим в Streamlit через st_folium,
        # содержимое выводим в боковой панели.
    ).add_to(fmap)

    COLORMAP.add_to(fmap)
    return fmap
