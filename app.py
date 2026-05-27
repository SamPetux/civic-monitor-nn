"""
Civic Monitor НН — Streamlit UI на реальных данных БД.

Изменения:
  • Метрика окраски района — z-score отклонения от средней негативности
    по городу (лучше различает однородные периоды).
  • В комментариях есть ссылки на сам комментарий VK и на автора.
  • В таблице авторов клик по имени ведёт на их страницу VK.
  • Слева в сайдбаре — кнопка обновления данных (фоновый запуск).
  • В графике динамики — переключатель день/час.
  • Темы со словами max/канал/подписывайтесь не показываются.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_folium import st_folium

from modules.districts import (
    DISTRICTS, DISTRICT_BY_ID, LOCAL_GROUPS, CITY_GROUPS, get_group_url,
)
from modules.visualization import build_district_map

from datetime import timezone, timedelta
MSK = timezone(timedelta(hours=3))

def _to_msk(dt: datetime) -> datetime:
    """Конвертировать UTC datetime в московское время."""
    if dt is None:
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(MSK)

GEOJSON_PATH = Path(__file__).parent / "data" / "districts.geojson"

st.set_page_config(
    page_title="Civic Monitor НН",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.metric-card {
  background:#f7f9fb;border:1px solid #e3e8ee;border-radius:10px;
  padding:12px 14px;margin-bottom:6px;
}
.sentiment-neg {color:#c0392b;font-weight:600;}
.sentiment-neu {color:#7f8c8d;font-weight:600;}
.sentiment-pos {color:#27ae60;font-weight:600;}
.small-caption {color:#7f8c8d;font-size:0.85rem;}
.intensity-high   {background:#e74c3c;color:white;padding:2px 8px;border-radius:4px;}
.intensity-medium {background:#f39c12;color:white;padding:2px 8px;border-radius:4px;}
.intensity-low    {background:#95a5a6;color:white;padding:2px 8px;border-radius:4px;}
a.vk-link { text-decoration:none; color:#3a6dd9; }
a.vk-link:hover { text-decoration:underline; }
</style>
""", unsafe_allow_html=True)


# ----------------------------------------------------------------------
# Источник данных
# ----------------------------------------------------------------------
def _try_real_repo():
    try:
        from modules import data_repo
        if not data_repo.is_db_empty():
            return data_repo, "real"
    except Exception as e:  # noqa: BLE001
        st.sidebar.warning(f"Не удалось подключиться к БД: {e}")
    return None, "mock"


class _MockRepoAdapter:
    def __init__(self):
        from modules import mock_data
        self._m = mock_data
    def is_db_empty(self): return False
    def get_data_period(self):
        return (datetime.now() - timedelta(days=30), datetime.now())
    def get_district_metrics(self, **kw):
        return self._m.get_district_metrics()
    def get_recent_comments(self, district_id, limit=50, sentiment=None,
                            excluded_user_ids=None, **kw):
        items = self._m.get_recent_comments(district_id, limit=limit)
        out = []
        for c in items:
            if excluded_user_ids and c.user_id in excluded_user_ids:
                continue
            if sentiment and c.sentiment != sentiment:
                continue
            # дополним отсутствующие поля для UI
            c.user_url = None
            c.group_url = None
            c.comment_url = None
            out.append(c)
        return out
    def get_sentiment_timeseries(self, district_id, **kw):
        return self._m.get_sentiment_timeseries(district_id)
    def get_top_users(self, limit=30, **kw):
        from modules.data_repo import TopUserRow
        return [
            TopUserRow(
                user_id=u.user_id, name=u.name,
                user_url=f"https://vk.com/id{u.user_id}",
                comments_in_period=u.comments_30d,
                avg_sentiment=u.avg_sentiment,
                districts=u.districts,
                suspected_bot=u.suspected_bot,
            ) for u in self._m.get_top_users(limit=limit)
        ]
    def get_top_topics(self, *a, **k): return []
    def get_bursts(self, *a, **k): return []
    def get_topic_day_heatmap(self, *a, **k): return [], [], []


repo, source = _try_real_repo()
if repo is None:
    repo = _MockRepoAdapter()


# ----------------------------------------------------------------------
# Кэш
# ----------------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def _cached_district_metrics(start_iso, end_iso, src):
    sd = datetime.fromisoformat(start_iso) if start_iso else None
    ed = datetime.fromisoformat(end_iso) if end_iso else None
    return repo.get_district_metrics(start_dt=sd, end_dt=ed)

@st.cache_data(ttl=300, show_spinner=False)
def _cached_comments(d_id, start_iso, end_iso, src, sentiment, excluded_tuple):
    sd = datetime.fromisoformat(start_iso) if start_iso else None
    ed = datetime.fromisoformat(end_iso) if end_iso else None
    return repo.get_recent_comments(
        d_id, start_dt=sd, end_dt=ed, limit=50,
        sentiment=sentiment, excluded_user_ids=set(excluded_tuple),
    )

@st.cache_data(ttl=300, show_spinner=False)
def _cached_timeseries(d_id, start_iso, end_iso, src, bucket):
    sd = datetime.fromisoformat(start_iso) if start_iso else None
    ed = datetime.fromisoformat(end_iso) if end_iso else None
    return repo.get_sentiment_timeseries(
        d_id, start_dt=sd, end_dt=ed, bucket=bucket,
    )

@st.cache_data(ttl=300, show_spinner=False)
def _cached_top_topics(d_id, start_iso, end_iso, src, limit=5):
    sd = datetime.fromisoformat(start_iso) if start_iso else None
    ed = datetime.fromisoformat(end_iso) if end_iso else None
    return repo.get_top_topics(d_id, start_dt=sd, end_dt=ed, limit=limit)

@st.cache_data(ttl=300, show_spinner=False)
def _cached_bursts(d_id, start_iso, end_iso, src, limit=10):
    sd = datetime.fromisoformat(start_iso) if start_iso else None
    ed = datetime.fromisoformat(end_iso) if end_iso else None
    return repo.get_bursts(d_id, start_dt=sd, end_dt=ed, limit=limit)

@st.cache_data(ttl=300, show_spinner=False)
def _cached_top_users(start_iso, end_iso, src, limit=30):
    sd = datetime.fromisoformat(start_iso) if start_iso else None
    ed = datetime.fromisoformat(end_iso) if end_iso else None
    return repo.get_top_users(start_dt=sd, end_dt=ed, limit=limit)

@st.cache_data(ttl=300, show_spinner=False)
def _cached_heatmap(d_id, start_iso, end_iso, src, top_n=8):
    sd = datetime.fromisoformat(start_iso) if start_iso else None
    ed = datetime.fromisoformat(end_iso) if end_iso else None
    return repo.get_topic_day_heatmap(d_id, start_dt=sd, end_dt=ed, top_n_topics=top_n)


def check_geojson() -> bool:
    if GEOJSON_PATH.exists():
        return True
    st.error(
        "Не найден файл `data/districts.geojson`. "
        "Запустите: `python prepare_data.py`"
    )
    return False


# ----------------------------------------------------------------------
# Session state
# ----------------------------------------------------------------------
if "selected_district" not in st.session_state:
    st.session_state.selected_district = "sormovsky"
if "excluded_users" not in st.session_state:
    st.session_state.excluded_users = set()


# ----------------------------------------------------------------------
# Sidebar
# ----------------------------------------------------------------------
period_avail = repo.get_data_period()
if period_avail:
    data_min, data_max = period_avail
else:
    data_min, data_max = datetime.now() - timedelta(days=30), datetime.now()

with st.sidebar:
    st.markdown(f"**Источник:** "
                f"{'🗄️ БД' if source == 'real' else '🧪 Mock (демо)'}")
    if source == "mock":
        st.caption("БД пуста — UI работает на демо-данных.")

    st.markdown("---")
    # ----- кнопка обновления -----
    st.markdown("### 🔄 Обновление данных")

    if source == "real":
        from modules.refresh_runner import (
            cancel_refresh, clear_last_result, get_status, start_refresh,
        )
        status = get_status()

        # Если последний прогон только что завершился — показываем
        # результат и сбрасываем кэш данных.
        if status.last_result == "done":
            st.success("✅ Обновление завершено")
            st.cache_data.clear()
            clear_last_result()
        elif status.last_result == "failed":
            st.error("❌ Обновление прервано / ошибка. См. лог ниже.")
            clear_last_result()

        if status.is_running:
            elapsed = int(time.time() - (status.started_at or time.time()))
            st.warning(f"Идёт обновление… ({elapsed}с, pid={status.pid})")

            # Автообновление статуса на стороне БРАУЗЕРА — не блокирует
            # Streamlit-сессию, поэтому остальные кнопки страницы остаются
            # отзывчивыми. Если пакет не установлен — fallback на ручное
            # обновление.
            try:
                from streamlit_autorefresh import st_autorefresh
                st_autorefresh(interval=60000, key="refresh_poll")
                st.caption("Статус обновляется автоматически каждые 60 сек.")
            except ImportError:
                st.caption("Для авто-обновления: "
                           "`pip install streamlit-autorefresh`. "
                           "Пока доступно ручное.")

            if status.log_tail:
                with st.expander("Лог", expanded=False):
                    st.code(status.log_tail[-2000:], language="text")
            c1, c2 = st.columns(2)
            if c1.button("⟳ Обновить статус"):
                st.rerun()
            if c2.button("✕ Остановить", type="secondary"):
                ok, msg = cancel_refresh()
                st.toast(msg)
                st.rerun()
        else:
            with st.expander("Параметры", expanded=True):
                refresh_unit = st.radio(
                    "Период парсинга",
                    ["Часы", "Дни"], index=0, horizontal=True,
                )
                if refresh_unit == "Часы":
                    refresh_hours = st.slider("За сколько часов", 1, 72, 24)
                    refresh_days = None
                else:
                    refresh_days = st.slider("За сколько дней", 1, 14, 1)
                    refresh_hours = None
                refresh_max  = st.slider(
                    "Постов на группу (потолок)", 10, 200, 50,
                    help="Парсер всё равно остановится на границе периода — "
                         "это лишь верхний предел.",
                )
                rerun_topics = st.checkbox("Переучить темы (долго)", value=False)
                rerun_bursts = st.checkbox("Пересчитать всплески", value=True)
            if st.button("▶ Запустить", type="primary",
                          use_container_width=True):
                ok, msg = start_refresh(
                    days=refresh_days, hours=refresh_hours,
                    max_posts=refresh_max,
                    skip_topics=not rerun_topics,
                    skip_bursts=not rerun_bursts,
                )
                st.toast(msg)
                st.cache_data.clear()
                time.sleep(1)
                st.rerun()
            if status.log_tail:
                with st.expander("Лог последнего запуска"):
                    st.code(status.log_tail[-2000:], language="text")

            # Аварийный сброс — на случай зависшего лока / зомби-pid
            from modules.refresh_runner import force_clear
            if st.button("🧹 Сбросить состояние",
                          help="Удалить лок и флаг результата, "
                               "если что-то зависло.",
                          use_container_width=True):
                force_clear()
                st.toast("Состояние сброшено")
                st.rerun()
    else:
        st.caption("Доступно только при работе с БД.")

    st.markdown("---")
    st.markdown("### 📅 Период")
    st.caption(f"Данные: {data_min.date()} — {data_max.date()}")

    period_mode = st.radio(
        "Режим",
        ["Весь период", "Последние N дней", "Последние N часов",
         "Один день", "Диапазон"],
        index=0,
    )

    start_dt = data_min
    end_dt = data_max + timedelta(days=1)

    if period_mode == "Последние N дней":
        n = st.slider("Дней", 1, 60, 7)
        end_dt = data_max + timedelta(days=1)
        start_dt = end_dt - timedelta(days=n)
    elif period_mode == "Последние N часов":
        n = st.slider("Часов", 1, 72, 12)
        end_dt = data_max + timedelta(minutes=1)
        start_dt = end_dt - timedelta(hours=n)
    elif period_mode == "Один день":
        chosen = st.date_input(
            "Дата", value=data_max.date(),
            min_value=data_min.date(), max_value=data_max.date(),
        )
        start_dt = datetime.combine(chosen, datetime.min.time())
        end_dt   = start_dt + timedelta(days=1)
    elif period_mode == "Диапазон":
        rng = st.date_input(
            "Диапазон", value=(data_min.date(), data_max.date()),
            min_value=data_min.date(), max_value=data_max.date(),
        )
        if isinstance(rng, tuple) and len(rng) == 2:
            start_dt = datetime.combine(rng[0], datetime.min.time())
            end_dt   = datetime.combine(rng[1], datetime.min.time()) \
                + timedelta(days=1)

    # форматирование подписи
    span_hours = (end_dt - start_dt).total_seconds() / 3600
    if span_hours <= 72:
        label = (f"{start_dt:%d.%m %H:%M} → "
                 f"{(end_dt - timedelta(seconds=1)):%d.%m %H:%M}")
    else:
        label = (f"{start_dt.date()} → "
                 f"{(end_dt - timedelta(days=1)).date()}")
    st.markdown(f"<small>Выбрано: <b>{label}</b></small>",
                unsafe_allow_html=True)

start_iso = start_dt.isoformat()
end_iso   = end_dt.isoformat()


# ----------------------------------------------------------------------
# Header
# ----------------------------------------------------------------------
st.title("🗺️ Мониторинг гражданской активности — Нижний Новгород")
st.caption(
    "Цвет района показывает, насколько он отличается от средней "
    "негативности по городу за выбранный период (красный = хуже среднего, "
    "зелёный = лучше). Кликните по району для деталей."
)
if not check_geojson():
    st.stop()


# ----------------------------------------------------------------------
# Tabs
# ----------------------------------------------------------------------
tab_map, tab_topics, tab_users = st.tabs([
    "🗺️ Карта", "📊 Темы", "👤 Топ авторов / боты"
])


# ====== ВКЛАДКА 1: КАРТА ============================================
with tab_map:
    metrics = _cached_district_metrics(start_iso, end_iso, source)
    metrics_by_id = {m.district_id: m for m in metrics}

    col_map, col_panel = st.columns([1.7, 1])

    with col_map:
        district_options = [m.district_id for m in metrics]
        if not district_options:
            st.info("За выбранный период нет данных.")
        else:
            current = st.session_state.selected_district
            if current not in district_options:
                current = district_options[0]
            selected = st.selectbox(
                "Район",
                options=district_options,
                index=district_options.index(current),
                format_func=lambda x: DISTRICT_BY_ID[x]["name_ru"],
                key="district_picker",
            )
            if selected != st.session_state.selected_district:
                st.session_state.selected_district = selected

            fmap = build_district_map(
                metrics=metrics,
                geojson_path=GEOJSON_PATH,
                selected_id=st.session_state.selected_district,
            )
            map_state = st_folium(
                fmap,
                height=680,
                width=None,
                use_container_width=True,
                returned_objects=["last_active_drawing"],
                key="nn_map",
            )
            clicked = map_state.get("last_active_drawing") if map_state else None
            if clicked and clicked.get("properties", {}).get("id"):
                new_id = clicked["properties"]["id"]
                if new_id != st.session_state.selected_district:
                    st.session_state.selected_district = new_id
                    st.rerun()

    with col_panel:
        d_id = st.session_state.selected_district
        d = DISTRICT_BY_ID[d_id]
        m = metrics_by_id.get(d_id)

        st.subheader(f"{d['name_ru']} район")

        if m is None or m.total_posts == 0:
            st.info("За выбранный период нет данных по этому району.")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Сообщений", m.total_posts)
            delta_pp = (m.delta_vs_city if hasattr(m, "delta_vs_city") else 0) * 100
            c2.metric(
                "Негатив",
                f"{m.neg_share * 100:.1f}%" if hasattr(m, "neg_share") else "—",
                f"{delta_pp:+.1f}%",
                delta_color="inverse",
            )
            c3.metric("Score", f"{m.negativity_score:.2f}")

            df_dist = pd.DataFrame({
                "tone": ["Негатив", "Нейтрально", "Позитив"],
                "count": [m.negative, m.neutral, m.positive],
            })
            fig_pie = px.pie(
                df_dist, names="tone", values="count", hole=0.55,
                color="tone",
                color_discrete_map={
                    "Негатив": "#e74c3c", "Нейтрально": "#bdc3c7",
                    "Позитив": "#27ae60",
                },
            )
            fig_pie.update_layout(
                margin=dict(l=0, r=0, t=10, b=0), height=200,
                showlegend=True, legend=dict(orientation="h", y=-0.1),
            )
            st.plotly_chart(fig_pie, use_container_width=True)

            # Динамика — bucket auto-выбирается
            bucket_default = "hour" if span_hours <= 72 else "day"
            bucket = st.radio(
                "Шаг", ["день", "час"],
                index=0 if bucket_default == "day" else 1,
                horizontal=True, key=f"bucket_{d_id}",
            )
            ts = _cached_timeseries(d_id, start_iso, end_iso, source,
                                    "hour" if bucket == "час" else "day")
            if ts:
                df = pd.DataFrame(ts)
                df["date"] = pd.to_datetime(df["date"])
                df_long = df.melt(
                    id_vars="date",
                    value_vars=["negative", "neutral", "positive"],
                    var_name="tone", value_name="count",
                )
                fig_line = px.line(
                    df_long, x="date", y="count", color="tone",
                    color_discrete_map={
                        "negative": "#e74c3c", "neutral": "#bdc3c7",
                        "positive": "#27ae60",
                    },
                    labels={"date": "Время", "count": "Сообщений", "tone": "Тон"},
                )
                fig_line.update_layout(
                    margin=dict(l=0, r=0, t=10, b=0), height=210,
                    legend=dict(orientation="h", y=-0.25),
                )
                st.plotly_chart(fig_line, use_container_width=True)

        # Топ-5 тем района
        topics = _cached_top_topics(d_id, start_iso, end_iso, source, 5)
        if topics:
            st.markdown("**Топ-5 тем района**")
            for t in topics:
                neg_pct = int(t.neg_share * 100)
                color = ("#e74c3c" if neg_pct >= 50
                         else "#f39c12" if neg_pct >= 30
                         else "#27ae60")
                st.markdown(
                    f"<div class='metric-card'>"
                    f"<b>{t.label}</b> "
                    f"<span class='small-caption'>· {t.count} сообщ. · </span>"
                    f"<span style='color:{color};font-weight:600;'>"
                    f"негатив {neg_pct}%</span><br>"
                    f"<span class='small-caption'>{t.keywords}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

        bursts = _cached_bursts(d_id, start_iso, end_iso, source, 5)
        if bursts:
            st.markdown("**🔥 Всплески обсуждений**")
            for b in bursts:
                cls = f"intensity-{b.intensity}"
                neg_str = (f"· негатив {int(b.neg_share * 100)}%"
                           if b.neg_share is not None else "")
                st.markdown(
                    f"<div class='metric-card'>"
                    f"<span class='{cls}'>{b.intensity.upper()}</span> "
                    f"<b>{_to_msk(b.date).strftime('%d.%m')}</b> · "
                    f"vol={b.volume} · z={b.z_score:.1f} {neg_str}<br>"
                    f"<span class='small-caption'>{b.topic_label}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

        with st.expander("Локальные сообщества района"):
            for g in LOCAL_GROUPS.get(d_id, []):
                st.markdown(
                    f"- [{g['name']}]({get_group_url(g['screen_name'])}) "
                    f"<span class='small-caption'>· {g['members']:,} подписчиков"
                    f"</span>".replace(",", " "),
                    unsafe_allow_html=True,
                )
        with st.expander("Общегородские паблики"):
            for g in CITY_GROUPS:
                st.markdown(
                    f"- [{g['name']}]({get_group_url(g['screen_name'])}) "
                    f"· {g['members']:,} подписчиков".replace(",", " ")
                )

        # ---- PDF-отчёт ----
        if source == "real":
            st.markdown("---")
            if st.button("📄 Экспорт PDF-отчёта", use_container_width=True,
                          key=f"pdf_{d_id}"):
                try:
                    from modules.pdf_report import build_district_report
                    pdf_bytes = build_district_report(
                        None, d_id, start_dt, end_dt,
                    )
                    st.session_state[f"pdf_data_{d_id}"] = pdf_bytes
                except Exception as e:  # noqa: BLE001
                    st.error(f"Ошибка генерации: {e}")
            # если PDF уже сгенерирован — даём скачать
            pdf_data = st.session_state.get(f"pdf_data_{d_id}")
            if pdf_data:
                fname = (
                    f"report_{d_id}_"
                    f"{start_dt.strftime('%Y%m%d')}_"
                    f"{(end_dt - timedelta(seconds=1)).strftime('%Y%m%d')}.pdf"
                )
                st.download_button(
                    "⬇ Скачать PDF",
                    data=pdf_data,
                    file_name=fname,
                    mime="application/pdf",
                    use_container_width=True,
                    key=f"pdf_dl_{d_id}",
                )

    # ---- комментарии под картой ----
    st.divider()
    st.subheader(f"Последние сообщения — {DISTRICT_BY_ID[d_id]['name_ru']}")
    tone_filter = st.radio(
        "Фильтр по тональности",
        options=["all", "negative", "neutral", "positive"],
        format_func=lambda x: {
            "all": "Все", "negative": "Только негатив",
            "neutral": "Только нейтральные", "positive": "Только позитив",
        }[x],
        horizontal=True,
        key="tone_filter",
    )

    excluded_tuple = tuple(sorted(st.session_state.excluded_users))
    sent_filter = None if tone_filter == "all" else tone_filter
    comments = _cached_comments(d_id, start_iso, end_iso, source,
                                 sent_filter, excluded_tuple)

    if not comments:
        st.info("Нет сообщений под этот фильтр / период.")
    else:
        for c in comments[:30]:
            tone_class = {"negative": "sentiment-neg",
                          "neutral":  "sentiment-neu",
                          "positive": "sentiment-pos"}[c.sentiment]
            tone_label = {"negative": "негатив",
                          "neutral":  "нейтрально",
                          "positive": "позитив"}[c.sentiment]

            # автор: ссылка если есть
            author_html = (
                f"<a class='vk-link' href='{c.user_url}' target='_blank'>"
                f"<b>{c.author}</b></a>"
                if getattr(c, "user_url", None) else f"<b>{c.author}</b>"
            )
            # группа
            group_html = (
                f"<a class='vk-link' href='{c.group_url}' target='_blank'>{c.group}</a>"
                if getattr(c, "group_url", None) else c.group
            )
            # ссылка на сам комментарий
            link_html = (
                f" · <a class='vk-link' href='{c.comment_url}' target='_blank'>"
                f"открыть в VK ↗</a>"
                if getattr(c, "comment_url", None) else ""
            )
            st.markdown(
                f"<div class='metric-card'>"
                f"{author_html} "
                f"<span class='small-caption'>· {group_html} · "
                f"{_to_msk(c.created_at):%d.%m %H:%M}{link_html}</span><br>"
                f"<span class='{tone_class}'>[{tone_label} · {c.score:.2f}]</span> "
                f"{c.text}"
                f"</div>",
                unsafe_allow_html=True,
            )


# ====== ВКЛАДКА 2: ТЕМЫ =============================================
with tab_topics:
    st.subheader("Темы по районам")
    col_l, col_r = st.columns([1, 2])
    with col_l:
        scope = st.radio(
            "Область",
            options=["город"] + [d["id"] for d in DISTRICTS],
            format_func=lambda x: ("Весь город" if x == "город"
                                    else DISTRICT_BY_ID[x]["name_ru"]),
        )
        topic_district = None if scope == "город" else scope

    topics = _cached_top_topics(topic_district, start_iso, end_iso, source, 15)
    if not topics:
        st.info("Нет тем за выбранный период.")
    else:
        df = pd.DataFrame([{
            "label": t.label,
            "count": t.count,
            "neg_share": round(t.neg_share * 100, 1),
        } for t in topics])

        with col_r:
            fig = px.bar(
                df, y="label", x="count", orientation="h",
                color="neg_share",
                color_continuous_scale=["#27ae60", "#f1c40f", "#e74c3c"],
                range_color=(0, 100),
                labels={"label": "Тема", "count": "Сообщений",
                        "neg_share": "% негатива"},
            )
            fig.update_layout(
                height=420, yaxis=dict(autorange="reversed"),
                margin=dict(l=0, r=0, t=10, b=0),
            )
            st.plotly_chart(fig, use_container_width=True)

        days, labels, matrix = _cached_heatmap(
            topic_district, start_iso, end_iso, source, 8
        )
        if days and matrix:
            st.markdown("**Динамика тем по дням**")
            fig_h = px.imshow(
                matrix, x=days, y=labels,
                color_continuous_scale="Reds",
                labels={"x": "Дата", "y": "Тема", "color": "Сообщений"},
                aspect="auto",
            )
            fig_h.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_h, use_container_width=True)


# ====== ВКЛАДКА 3: ТОП АВТОРОВ ======================================
with tab_users:
    st.subheader("Топ авторов за период")
    st.caption(
        "Самые активные комментаторы. Сильный перекос среднего эмоционального "
        "окраса при высокой активности — индикатор возможной бот-сети. "
        "Клик по имени открывает профиль VK."
    )

    users = _cached_top_users(start_iso, end_iso, source, 30)

    if not users:
        st.info("Нет авторов за выбранный период.")
    else:
        # Делаем колонку "Автор" в виде markdown-ссылок —
        # data_editor с LinkColumn даёт кликабельность
        rows = []
        for u in users:
            rows.append({
                "user_id": u.user_id,
                "VK": u.user_url,
                "Автор": u.name,
                "Комментариев": u.comments_in_period,
                "Средний окрас": u.avg_sentiment,
                "Активен в районах": ", ".join(
                    DISTRICT_BY_ID[d_id]["name_ru"] for d_id in u.districts
                ) if u.districts else "—",
                "🤖 Бот?": "⚠️ да" if u.suspected_bot else "—",
                "Исключён": u.user_id in st.session_state.excluded_users,
            })
        df_users = pd.DataFrame(rows)

        edited = st.data_editor(
            df_users,
            column_config={
                "user_id": None,
                "VK": st.column_config.LinkColumn(
                    "Профиль", display_text="↗ открыть",
                ),
                "Средний окрас": st.column_config.NumberColumn(
                    format="%.2f",
                    help="-1 = всегда негатив, +1 = всегда позитив",
                ),
                "Исключён": st.column_config.CheckboxColumn(
                    help="Не учитывать в районной аналитике",
                ),
            },
            hide_index=True,
            use_container_width=True,
            key="users_editor",
        )

        new_excluded = set(
            edited.loc[edited["Исключён"], "user_id"].astype(int).tolist()
        )
        if new_excluded != st.session_state.excluded_users:
            st.session_state.excluded_users = new_excluded
            _cached_comments.clear()
            st.toast(f"Исключено: {len(new_excluded)}")

        c1, c2, c3 = st.columns(3)
        c1.metric("Авторов", len(users))
        c2.metric("Подозрение на бота",
                  sum(1 for u in users if u.suspected_bot))
        c3.metric("Исключены", len(st.session_state.excluded_users))
