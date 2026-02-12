"""
Конфигурация районов Нижнего Новгорода.

DISTRICTS — 8 административных районов города.
LOCAL_GROUPS — крупнейшие локальные сообщества VK по каждому району
              (по 5 на район — топ по подписчикам и активности).
CITY_GROUPS — общегородские паблики, посты из которых распределяются
              по районам через геокодинг адресов в текстах.

Список групп — стартовый, его можно дополнять. Часть групп пересекается
по тематике (Подслушано / LIVE / Новости — стандартные форматы VK-пабликов
для городских районов).
"""

# Каноничный порядок и идентификаторы районов.
# id используется в GeoJSON как ключ привязки границ к данным.
DISTRICTS = [
    {"id": "avtozavodsky",  "name_ru": "Автозаводский",  "name_en": "Avtozavodsky"},
    {"id": "kanavinsky",    "name_ru": "Канавинский",    "name_en": "Kanavinsky"},
    {"id": "leninsky",      "name_ru": "Ленинский",      "name_en": "Leninsky"},
    {"id": "moskovsky",     "name_ru": "Московский",     "name_en": "Moskovsky"},
    {"id": "nizhegorodsky", "name_ru": "Нижегородский",  "name_en": "Nizhegorodsky"},
    {"id": "priokskiy",     "name_ru": "Приокский",      "name_en": "Priokskiy"},
    {"id": "sovetsky",      "name_ru": "Советский",      "name_en": "Sovetsky"},
    {"id": "sormovsky",     "name_ru": "Сормовский",     "name_en": "Sormovsky"},
]

DISTRICT_BY_ID = {d["id"]: d for d in DISTRICTS}

# По 5 локальных VK-сообществ на район.
# Поля: name (отображаемое имя), screen_name (для построения URL),
#       members (примерное число подписчиков — для сортировки).
LOCAL_GROUPS = {
    "avtozavodsky": [
        {"name": "Подслушано Автозавод",                        "screen_name": "podslushanoavtozavodnnovgorod", "members": 42400},
        {"name": "Автозавод. Нижний Новгород",                  "screen_name": "avtozavod.nino",                "members": 77000},
        {"name": "Администрация Автозаводского района",         "screen_name": "avt_nn",                        "members": 12500},
        {"name": "Типичный Автозавод",                          "screen_name": "avtozavod_152",                 "members": 38000},
        {"name": "Автозаводцы",                                 "screen_name": "club48760252",                  "members": 14000},
    ],
    "kanavinsky": [
        {"name": "Канавинский. Нижний Новгород",                "screen_name": "kanavino.nino",               "members": 6400},
        {"name": "Канавинский район",                           "screen_name": "kanavino_nino",               "members": 3200},
        {"name": "Мещерское озеро",                             "screen_name": "meshera_nino",                "members": 8600},
        {"name": "Подслушано Канавинский",                      "screen_name": "podslushano_afisha_nnv5",     "members": 5800},
        {"name": "Администрация Канавинского района",           "screen_name": "kan_adm_nn",                  "members": 6000},
    ],
    "leninsky": [
        {"name": "Подслушано Ленинский",                        "screen_name": "podslushano_afisha_nnv3",   "members": 5900},
        {"name": "ЛЕНИНСКИЙ район | НН",                        "screen_name": "leninsky_nn",               "members": 2300},
        {"name": "Типичный Ленинский",                          "screen_name": "leninskiu_k",               "members": 5100},
        {"name": "Ленинский LIVE",                              "screen_name": "len_nn_live",               "members": 8300},
        {"name": "Администрация Ленинского района",             "screen_name": "len.admgor.nnov",           "members": 5900},
    ],
    "moskovsky": [
        {"name": "Подслушано в Московском районе",              "screen_name": "public879740",          "members": 1700},
        {"name": "МОСКОВСКИЙ район | НН",                       "screen_name": "moskovskiy_nino",       "members": 2800},
        {"name": "Солнечная Сортировка",                        "screen_name": "sun_sortirovka",        "members": 17300},
        {"name": "Бурнаковка LIFE",                             "screen_name": "burnakovka",            "members": 3200},
        {"name": "Администрация Московского района",            "screen_name": "msknino",               "members": 4900},
    ],
    "nizhegorodsky": [
        {"name": "Нижегородский район | Новости и события",     "screen_name": "nizh_rayon",            "members": 2200},
        {"name": "НИЖЕГОРОДСКИЙ район | НН",                    "screen_name": "nizhegorodskij_nino",   "members": 2400},
        {"name": "Верхние Печёры.Нижний Новгород",              "screen_name": "verkhniyepecherynn",    "members": 6300},
        {"name": "Нижний Новгород Нижегородский",               "screen_name": "nig_nn",                "members": 2600},
        {"name": "Администрация Нижегородского района",         "screen_name": "nizh_adm",              "members": 7300},
    ],
    "priokskiy": [
        {"name": "Подслушано Приокский р-н",                    "screen_name": "priokskii",             "members": 21700},
        {"name": "ПРИОКСКИЙ район | НН",                        "screen_name": "priokskij_nino",        "members": 3000},
        {"name": "ЖК Цветы",                                    "screen_name": "tsvetynn",              "members": 18000},
        {"name": "Гагаринские Высоты| ЖК",                      "screen_name": "club63657280",          "members": 2700},
        {"name": "Администрация Приокского района",             "screen_name": "priok.admgor.nnov",     "members": 7200},
    ],
    "sovetsky": [
        {"name": "Подслушано в Анкудиновке",                    "screen_name": "ankudinovskij_park_sosedi",     "members": 111000},
        {"name": "СОВЕТСКИЙ район | НН",                        "screen_name": "sovetskij_nino",                "members": 2900},
        {"name": "ЖК Новая Кузнечиха",                          "screen_name": "zhk_novaya_kuznechiha",         "members": 14300},
        {"name": "Бекетовка",                                   "screen_name": "beketowka",                     "members": 4200},
        {"name": "Администрация Советского района",             "screen_name": "publicsovadm",                  "members": 6400},
    ],
    "sormovsky": [
        {"name": "Подслушано в Сормово",                        "screen_name": "sormovskir",            "members": 18700},
        {"name": "Сормово.РФ",                                  "screen_name": "sormovorf",             "members": 16000},
        {"name": "Типичное Сормово",                            "screen_name": "sormovo_152",           "members": 45000},
        {"name": "Сормово. Нижний Новгород",                    "screen_name": "sormovo.nino",          "members": 26400},
        {"name": "Администрация Сормовского района",            "screen_name": "sormovo_adm",           "members": 6800},
    ],
}

# Общегородские паблики. Контент из них распределяется по районам
# через NER + геокодинг упомянутых адресов / районов в тексте.
CITY_GROUPS = [
    {"name": "Нижний Новгород",                 "screen_name": "nn800",             "members": 470000},
    {"name": "ЧП | ДТП Нижний Новгород",        "screen_name": "chp_nn",            "members": 341000},
    {"name": "Типичный Нижний Новгород",        "screen_name": "typical_nn",        "members": 277000},
    {"name": "Нижний Новгород |БЕЗ ЦЕНЗУРЫ|",   "screen_name": "bez_cenznn",        "members": 147000},
    {"name": "Кстати...",                       "screen_name": "kstatinn",          "members": 483000},
    {"name": "Мэрия Нижнего Новгорода",         "screen_name": "nn_admgorod",       "members": 39600},
]


def get_group_url(screen_name: str) -> str:
    """Сформировать ссылку на VK-сообщество по короткому имени."""
    return f"https://vk.com/{screen_name}"
