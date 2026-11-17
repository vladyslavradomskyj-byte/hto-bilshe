"""Каталог тем: предмети, критерії, синергії, штрафи та cap-правила.

Теми — це лише дані. Уся логіка (резервування, оцінювання) живе в рушії.
"""
import random

UNITS = {"шт", "л", "г", "кг", "ккал", "набір", "упак.", "м", "пара"}

ROLES = ["critical", "important", "supporting", "synergy", "situational", "wildcard"]

# Розподіл ролей лотів за кількістю лотів (ТЗ §25).
ROLE_PLAN = {
    8: {"critical": 2, "important": 2, "supporting": 2, "synergy": 1, "situational": 1, "wildcard": 0},
    15: {"critical": 4, "important": 4, "supporting": 3, "synergy": 2, "situational": 1, "wildcard": 1},
    20: {"critical": 5, "important": 5, "supporting": 4, "synergy": 3, "situational": 2, "wildcard": 1},
}

# Складність змінює кількість взаємозалежностей (ТЗ §35); діє для 15+ лотів.
DIFFICULTY_SHIFT = {
    "easy": {"critical": 1, "synergy": -1},
    "normal": {},
    "hard": {"critical": -1, "synergy": 1},
    "expert": {"important": -1, "situational": 1},
}

CAP_LABELS = {
    "raw_water": "джерело сирої води",
    "batteries": "батарейки",
    "ventilation": "нормальна вентиляція",
    "sunlight": "сонячне світло",
    "fire": "вогонь",
    "sea": "море поруч",
    "uk_socket": "британська розетка (адаптер)",
    "phone_power": "живлення для телефона",
}

SUBJECTIVE_RUBRIC = (
    "0–2 — явна невідповідність; 3–4 — слабке поєднання; 5–6 — прийнятне; "
    "7–8 — добре; 9–10 — особливо вдале. Це прогноз, а не фізична дегустація."
)


def item(key, name, emoji, category, role, attrs=None, qty=1, unit="шт", tags=(),
         requires=(), provides=(), desc=""):
    return {
        "key": key, "name": name, "emoji": emoji, "category": category, "role": role,
        "attrs": dict(attrs or {}), "quantity": qty, "unit": unit, "tags": list(tags),
        "requires": list(requires), "provides": list(provides), "description": desc,
    }


def crit(cid, title, weight, ctype, **kw):
    c = {"id": cid, "title": title, "weight": weight, "type": ctype}
    c.update(kw)
    return c


# ---------------------------------------------------------------- Укриття
SHELTER = dict(
    id="shelter_5d", title="П'ять діб в укритті", emoji="🏚️", category="Виживання", photos=False,
    objective="Зібрати набір, з яким одна людина найкраще протримається 5 діб в укритті без водогону, світла й опалення.",
    intro="Місто накрив тривалий блекаут. У вас — сухий, але холодний підвал на п'ять діб. "
          "Те, що ви купите на аукціоні, — усе, що буде поруч.",
    environment=["Водогону немає, джерела сирої води теж", "Електрики немає, сонця в підвалі не буде",
                 "Вентиляція слабка — газ і відкритий вогонь небезпечні", "Температура близько +8 °C"],
    env_caps=[],
    attr_labels={"water_l": ("Питна вода", "л"), "kcal": ("Енергія їжі", "ккал"), "heat": ("Тепло", "бал."),
                 "sanitation": ("Санітарія", "бал."), "light_h": ("Світло", "год"),
                 "medical": ("Медицина", "бал."), "info": ("Інформація", "бал."),
                 "protection": ("Захист", "бал."), "energy_wh": ("Енергія", "Вт·год")},
    criteria=[
        crit("water", "Питна вода", 25, "sum", attr="water_l", target=15),
        crit("food", "Харчування", 20, "sum", attr="kcal", target=10000),
        crit("heat", "Тепло", 12, "sum", attr="heat", target=10),
        crit("sanitation", "Санітарія", 10, "sum", attr="sanitation", target=10),
        crit("light", "Освітлення", 7, "sum", attr="light_h", target=40),
        crit("medicine", "Медицина", 7, "sum", attr="medical", target=10),
        crit("info", "Інформація", 5, "sum", attr="info", target=8),
        crit("protection", "Захист", 5, "sum", attr="protection", target=8),
        crit("energy", "Автономна енергія", 5, "sum", attr="energy_wh", target=120),
        crit("economy", "Економність", 4, "economy"),
    ],
    items=[
        item("water20", "Вода питна", "💧", "water", "critical", {"water_l": 20}, 20, "л", ["water"]),
        item("water10", "Вода питна", "💧", "water", "critical", {"water_l": 10}, 10, "л", ["water"]),
        item("water9", "Вода в пляшках 6×1,5 л", "🧴", "water", "critical", {"water_l": 9}, 9, "л", ["water"]),
        item("canned6", "Консерви", "🥫", "food", "critical", {"kcal": 2400}, 6, "шт", ["food"]),
        item("rations", "Сухі раціони", "🍱", "food", "critical", {"kcal": 10000}, 10000, "ккал", ["food"]),
        item("bars12", "Енергобатончики", "🍫", "food", "critical", {"kcal": 2400}, 12, "шт", ["food"]),
        item("sleeping_bag", "Зимовий спальник", "🛏️", "heat", "important", {"heat": 6}),
        item("first_aid", "Аптечка", "🩹", "medical", "important", {"medical": 8}, 1, "набір"),
        item("toilet", "Портативний туалет", "🚽", "sanitation", "important", {"sanitation": 7}),
        item("radio", "Аварійне радіо з динамо", "📻", "info", "important", {"info": 7}),
        item("led_lamp", "LED-ліхтар з батарейками", "🔦", "light", "important", {"light_h": 30}),
        item("gas_heater", "Газовий обігрівач з балоном", "🔥", "heat", "important", {"heat": 7},
             requires=["ventilation"], desc="Безпечний лише за нормальної вентиляції."),
        item("thermal_blankets", "Термоковдри", "🪙", "heat", "supporting", {"heat": 2}, 3, "шт",
             desc="Зберігають тепло, але не гріють самі."),
        item("hygiene_kit", "Гігієнічний набір", "🧼", "sanitation", "supporting", {"sanitation": 4}, 1, "набір"),
        item("powerbank", "Павербанк 30 000 мА·год", "🔋", "energy", "supporting", {"energy_wh": 110},
             provides=["phone_power"]),
        item("respirators", "Респіратори FFP2", "😷", "protection", "supporting", {"protection": 4}, 5, "шт",
             desc="Захищають від пилу, але не від нестачі кисню чи чадного газу."),
        item("candles", "Свічки", "🕯️", "light", "supporting", {"light_h": 20, "heat": 1}, 10, "шт"),
        item("headlamp", "Налобний ліхтар", "⛑️", "light", "synergy", {"light_h": 35}, requires=["batteries"],
             desc="Продається без батарейок."),
        item("batteries", "Батарейки АА", "🔋", "energy", "synergy", {"energy_wh": 30}, 12, "шт",
             provides=["batteries"]),
        item("water_filter", "Фільтр для води", "🚰", "water", "synergy", {"water_l": 30}, requires=["raw_water"],
             desc="Очищує сиру воду, але сам воду не створює."),
        item("helmet_gloves", "Каска та робочі рукавиці", "🪖", "protection", "synergy", {"protection": 5}, 1, "набір"),
        item("dynamo_light", "Динамо-ліхтар", "🔦", "light", "situational", {"light_h": 15}),
        item("solar_panel", "Сонячна панель 20 Вт", "☀️", "energy", "situational", {"energy_wh": 120},
             requires=["sunlight"]),
        item("thermos", "Термос", "🫖", "heat", "situational", {"heat": 2}),
        item("whistle", "Сигнальний свисток", "📯", "protection", "wildcard", {"protection": 2}),
        item("cards", "Колода карт", "🃏", "misc", "wildcard", {}, 1, "упак.",
             desc="Рятує від нудьги, але рубрика її не враховує."),
    ],
    synergies=[
        {"id": "layers", "all": ["sleeping_bag", "thermal_blankets"], "criterion": "heat", "bonus": 1.0,
         "text": "Спальник + термоковдри: шари утеплення працюють разом."},
        {"id": "hygiene", "all": ["toilet", "hygiene_kit"], "criterion": "sanitation", "bonus": 1.0,
         "text": "Туалет + гігієнічний набір: повний санітарний цикл."},
        {"id": "radio_power", "all": ["radio", "powerbank"], "criterion": "info", "bonus": 1.0,
         "text": "Радіо + павербанк: зв'язок не залежить від сил крутити динамо."},
    ],
    penalties=[],
    caps=[
        {"id": "no_water", "cond": {"attr": "water_l", "lt": 3}, "cap": 4.0,
         "text": "Критичний дефіцит питної води (менше 3 л на 5 діб) — підсумок не вище 4,0."},
        {"id": "no_food", "cond": {"attr": "kcal", "lt": 2000}, "cap": 6.0,
         "text": "Майже немає їжі (менше 2000 ккал) — підсумок не вище 6,0."},
    ],
    constraints=[{"tag": "water", "min": 2}],
)

# ---------------------------------------------------------------- Острів
ISLAND = dict(
    id="island_7d", title="Безлюдний острів", emoji="🏝️", category="Виживання", photos=False,
    objective="Протриматися 7 діб на тропічному острові, доки вас не знайдуть рятувальники.",
    intro="Яхта сіла на риф. До острова ви дісталися вплав, а все, що встигли врятувати, "
          "розіграють на аукціоні. Через тиждень тут пролітатиме патрульний літак.",
    environment=["Є струмок із сирою водою", "Багато сонця", "Море поруч — можна рибалити",
                 "Ночі прохолодні, бувають зливи"],
    env_caps=["raw_water", "sunlight", "sea"],
    attr_labels={"water_l": ("Питна вода", "л"), "kcal": ("Енергія їжі", "ккал"), "heat": ("Укриття й тепло", "бал."),
                 "fire": ("Вогонь", "бал."), "tools": ("Інструменти", "бал."), "info": ("Сигнал", "бал."),
                 "medical": ("Медицина", "бал."), "light_h": ("Світло", "год"),
                 "protection": ("Захист", "бал.")},
    criteria=[
        crit("water", "Питна вода", 22, "sum", attr="water_l", target=21),
        crit("food", "Харчування", 18, "sum", attr="kcal", target=14000),
        crit("shelter", "Укриття й тепло", 12, "sum", attr="heat", target=10),
        crit("fire", "Вогонь", 10, "sum", attr="fire", target=8),
        crit("tools", "Інструменти", 10, "sum", attr="tools", target=10),
        crit("signal", "Сигнал рятувальникам", 8, "sum", attr="info", target=8),
        crit("medicine", "Медицина", 8, "sum", attr="medical", target=8),
        crit("light", "Освітлення", 5, "sum", attr="light_h", target=40),
        crit("protection", "Захист від сонця й комах", 3, "sum", attr="protection", target=6),
        crit("economy", "Економність", 4, "economy"),
    ],
    items=[
        item("water10", "Вода питна", "💧", "water", "critical", {"water_l": 10}, 10, "л", ["water"]),
        item("water20", "Вода питна", "💧", "water", "critical", {"water_l": 20}, 20, "л", ["water"]),
        item("water_filter", "Фільтр для води", "🚰", "water", "critical", {"water_l": 40}, tags=["water"],
             requires=["raw_water"], desc="Очищує воду зі струмка."),
        item("rations", "Сухі раціони", "🍱", "food", "critical", {"kcal": 10000}, 10000, "ккал", ["food"]),
        item("canned6", "Консерви", "🥫", "food", "critical", {"kcal": 2400}, 6, "шт", ["food"]),
        item("fishing_kit", "Рибальський набір", "🎣", "food", "critical", {"kcal": 7000}, 1, "набір", ["food"],
             requires=["sea"]),
        item("machete", "Мачете", "🗡️", "tools", "important", {"tools": 7, "protection": 1}),
        item("flint", "Вогниво", "✨", "fire", "important", {"fire": 8}, provides=["fire"]),
        item("matches", "Водостійкі сірники", "🔥", "fire", "important", {"fire": 5}, 3, "упак.", provides=["fire"]),
        item("tarp", "Тент 3×4 м", "⛺", "shelter", "important", {"heat": 5}),
        item("first_aid", "Аптечка", "🩹", "medical", "important", {"medical": 8}, 1, "набір"),
        item("flares", "Сигнальні ракети", "🎆", "signal", "important", {"info": 7}, 3, "шт"),
        item("multitool", "Мультитул", "🛠️", "tools", "supporting", {"tools": 5}),
        item("rope", "Мотузка", "🪢", "tools", "supporting", {"tools": 3, "heat": 1}, 30, "м"),
        item("sleeping_bag", "Спальник", "🛏️", "shelter", "supporting", {"heat": 5}),
        item("purif_tabs", "Таблетки для знезараження води", "💊", "water", "supporting", {"water_l": 20}, 20, "шт",
             ["water"], requires=["raw_water"]),
        item("repellent", "Репелент і сонцезахисний крем", "🧴", "protection", "supporting", {"protection": 6}, 1, "набір"),
        item("pot", "Казанок", "🍲", "water", "synergy", {"water_l": 25}, requires=["raw_water", "fire"],
             desc="Щоб кип'ятити воду, потрібен вогонь."),
        item("headlamp", "Налобний ліхтар", "⛑️", "light", "synergy", {"light_h": 35}, requires=["batteries"],
             desc="Продається без батарейок."),
        item("batteries", "Батарейки АА", "🔋", "light", "synergy", {}, 12, "шт", provides=["batteries"]),
        item("mirror", "Сигнальне дзеркало", "🪞", "signal", "synergy", {"info": 4}, requires=["sunlight"]),
        item("dynamo_light", "Динамо-ліхтар", "🔦", "light", "situational", {"light_h": 15}),
        item("solar_charger", "Сонячний зарядний пристрій з акумуляторами", "☀️", "light", "situational", {},
             requires=["sunlight"], provides=["batteries"]),
        item("hammock", "Гамак", "🏖️", "shelter", "situational", {"heat": 2}),
        item("ukulele", "Укулеле", "🎸", "misc", "wildcard", {}, desc="Чудово для настрою, рубрика не враховує."),
        item("flamingo", "Надувний фламінго", "🦩", "misc", "wildcard", {"protection": 1}),
    ],
    synergies=[
        {"id": "tarp_rope", "all": ["tarp", "rope"], "criterion": "shelter", "bonus": 1.0,
         "text": "Тент + мотузка: укриття можна натягнути надійно."},
        {"id": "cook_fish", "all": ["fishing_kit"], "caps": ["fire"], "criterion": "food", "bonus": 1.0,
         "text": "Рибальський набір + вогонь: улов можна приготувати."},
        {"id": "signal_combo", "all": ["flares", "mirror"], "criterion": "signal", "bonus": 1.0,
         "text": "Ракети вночі + дзеркало вдень: сигнал цілодобово."},
    ],
    penalties=[],
    caps=[
        {"id": "no_water", "cond": {"attr": "water_l", "lt": 5}, "cap": 4.0,
         "text": "Немає питної води чи способу її отримати — підсумок не вище 4,0."},
        {"id": "no_fire", "cond": {"attr": "fire", "lt": 1}, "cap": 7.0,
         "text": "Немає чим розпалити вогонь — підсумок не вище 7,0."},
    ],
    constraints=[{"tag": "water", "min": 2}],
)

# ---------------------------------------------------------------- Салат
_P = "бал."
SALAD = dict(
    id="salad", title="Ідеальний салат", emoji="🥗", category="Кулінарія", photos=True,
    objective="Зібрати інгредієнти для найгармонійнішого салату. Важить смак, а не ціна покупки.",
    intro="Кулінарне шоу, фінал. Журі чекає на салат, про який говоритимуть. "
          "Інгредієнти виставляють по одному — і кожен може дістатися суперникові.",
    environment=["Кухня обладнана всім необхідним", "Сіль і перець є в усіх",
                 "Оцінюється прогноз смаку, а не дегустація"],
    env_caps=[],
    attr_labels={"base": ("Основа", _P), "protein": ("Білок", _P), "dressing": ("Заправка", _P),
                 "crunch": ("Хрусткість", _P), "sweet": ("Солодкість", _P), "sour": ("Кислинка", _P),
                 "salty": ("Солоність", _P), "umami": ("Умамі", _P), "bitter": ("Гірчинка", _P),
                 "nutrition": ("Поживність", _P), "creative": ("Оригінальність", _P)},
    criteria=[
        crit("taste", "Очікуваний смак", 25, "avg", of=["balance", "dressing", "texture"], subjective=True,
             rubric=SUBJECTIVE_RUBRIC),
        crit("dressing", "Заправка", 15, "sum", attr="dressing", target=8),
        crit("texture", "Текстура", 10, "sum", attr="crunch", target=8),
        crit("balance", "Баланс смаків", 10, "profiles", attrs=["sweet", "sour", "salty", "umami"],
             threshold=2, target=4),
        crit("base", "Основа", 10, "sum", attr="base", target=8),
        crit("protein", "Білкова складова", 7, "sum", attr="protein", target=8),
        crit("variety", "Різноманітність", 7, "categories", target=6),
        crit("nutrition", "Поживність", 6, "sum", attr="nutrition", target=8),
        crit("creativity", "Креативність", 5, "sum", attr="creative", target=6, subjective=True,
             rubric=SUBJECTIVE_RUBRIC),
        crit("economy", "Економність", 5, "economy"),
    ],
    items=[
        item("mix_greens", "Мікс салатів", "🥬", "base", "critical", {"base": 6, "nutrition": 3, "bitter": 1}, 200, "г"),
        item("iceberg", "Айсберг", "🥬", "base", "critical", {"base": 5, "crunch": 3, "nutrition": 1}, 1, "шт"),
        item("arugula", "Рукола", "🌿", "base", "critical", {"base": 5, "bitter": 2, "creative": 1}, 150, "г"),
        item("cherry", "Томати черрі", "🍅", "veg", "critical", {"sweet": 2, "sour": 1, "nutrition": 2}, 250, "г"),
        item("chicken", "Курка гриль", "🍗", "meat", "critical", {"protein": 7, "umami": 2}, 300, "г"),
        item("caesar_sauce", "Соус «Цезар»", "🥣", "sauce", "important", {"dressing": 6, "umami": 2, "salty": 1},
             150, "г", ["sauce"]),
        item("balsamic", "Оливкова олія з бальзаміком", "🫒", "sauce", "important",
             {"dressing": 6, "sour": 2, "sweet": 1}, 150, "г", ["sauce"]),
        item("honey_mustard", "Медово-гірчична заправка", "🍯", "sauce", "important",
             {"dressing": 5, "sweet": 2, "sour": 1}, 150, "г", ["sauce"]),
        item("feta", "Фета", "🧀", "cheese", "important", {"protein": 4, "salty": 3}, 200, "г"),
        item("parmesan", "Пармезан", "🧀", "cheese", "important", {"protein": 3, "salty": 2, "umami": 3}, 100, "г"),
        item("cucumbers", "Огірки", "🥒", "veg", "important", {"crunch": 3, "nutrition": 1}, 300, "г"),
        item("croutons", "Грінки", "🍞", "bread", "supporting", {"crunch": 4}, 100, "г"),
        item("walnuts", "Волоські горіхи", "🌰", "nuts", "supporting",
             {"crunch": 3, "protein": 2, "nutrition": 2, "bitter": 1}, 100, "г"),
        item("olives", "Оливки", "🫒", "veg", "supporting", {"salty": 2, "sour": 1}, 150, "г"),
        item("red_onion", "Червона цибуля", "🧅", "veg", "supporting", {"sour": 1, "bitter": 1, "crunch": 1}, 1, "шт"),
        item("avocado", "Авокадо", "🥑", "veg", "supporting", {"protein": 1, "nutrition": 3, "creative": 1}, 2, "шт"),
        item("burrata", "Буррата", "🧀", "cheese", "synergy", {"protein": 4, "salty": 1, "creative": 3}, 125, "г"),
        item("basil", "Базилік", "🌿", "herbs", "synergy", {"creative": 1, "sweet": 1}, 30, "г"),
        item("pear", "Груша", "🍐", "fruit", "synergy", {"sweet": 3, "crunch": 1, "creative": 1}, 2, "шт"),
        item("dor_blue", "Дор блю", "🧀", "cheese", "synergy", {"protein": 3, "salty": 2, "umami": 2, "creative": 2},
             100, "г"),
        item("shrimp", "Креветки", "🦐", "seafood", "situational", {"protein": 6, "umami": 2, "creative": 2}, 250, "г"),
        item("bacon", "Бекон", "🥓", "meat", "situational", {"protein": 3, "salty": 3, "umami": 2, "crunch": 2}, 150, "г"),
        item("pesto", "Песто", "🌱", "sauce", "situational", {"dressing": 4, "umami": 2, "salty": 1}, 100, "г",
             ["sauce"]),
        item("pomegranate", "Гранат", "🍎", "fruit", "wildcard", {"sweet": 2, "sour": 2, "creative": 2}, 1, "шт"),
        item("flowers", "Їстівні квіти", "🌸", "herbs", "wildcard", {"creative": 4}, 20, "г"),
    ],
    synergies=[
        {"id": "caprese", "all": ["burrata", "cherry", "basil"], "criterion": "taste", "bonus": 1.5,
         "text": "Буррата + томати + базилік: класичне італійське поєднання."},
        {"id": "greek", "all": ["feta", "olives", "cucumbers"], "criterion": "taste", "bonus": 1.0,
         "text": "Фета + оливки + огірки: грецька класика."},
        {"id": "pear_blue", "all": ["pear", "dor_blue", "walnuts"], "criterion": "taste", "bonus": 1.5,
         "text": "Груша + дор блю + горіхи: солодке, солоне й хрустке."},
        {"id": "caesar", "all": ["chicken", "parmesan", "croutons", "caesar_sauce"], "criterion": "taste",
         "bonus": 1.5, "text": "Курка + пармезан + грінки + соус «Цезар»: повний «Цезар»."},
        {"id": "shrimp_avocado", "all": ["shrimp", "avocado"], "criterion": "taste", "bonus": 1.0,
         "text": "Креветки + авокадо: ніжне й поживне поєднання."},
    ],
    penalties=[
        {"id": "too_many_sauces", "cond": {"count_tag": "sauce", "gt": 2}, "criterion": "balance", "value": 2.0,
         "text": "Понад два соуси: смаки перебивають один одного."},
    ],
    caps=[
        {"id": "no_base", "cond": {"all": [{"attr": "base", "lt": 1}, {"attr": "protein", "lt": 1}]}, "cap": 5.0,
         "text": "Немає ні зелені-основи, ні білка — це гарнір, а не салат. Підсумок не вище 5,0."},
    ],
    constraints=[{"tag": "sauce", "min": 2}],
)

# ---------------------------------------------------------------- Валіза
SUITCASE = dict(
    id="suitcase", title="Валіза для подорожі", emoji="🧳", category="Подорожі", photos=True,
    objective="Зібрати валізу на тиждень осінньої подорожі: Лондон і гори Шотландії.",
    intro="Квитки куплено, виліт завтра. Лишилося зібрати валізу — і кожну річ доведеться виграти на аукціоні. "
          "Прогноз: +6…+12 °C, дощі, вітер у горах.",
    environment=["Розетки британського типу", "Часті дощі й вітер", "Багато ходьби містом і стежками",
                 "Ліміт багажу — 7 кг ручної поклажі"],
    env_caps=[],
    attr_labels={"warmth": ("Тепло", _P), "rain": ("Захист від дощу", _P), "security": ("Безпека документів", _P),
                 "power": ("Електроніка", _P), "medical": ("Здоров'я", _P), "versatility": ("Універсальність", _P),
                 "nav": ("Навігація", _P), "comfort": ("Комфорт", _P), "weight_kg": ("Вага", "кг")},
    criteria=[
        crit("warmth", "Тепло", 18, "sum", attr="warmth", target=10),
        crit("rain", "Захист від дощу", 12, "sum", attr="rain", target=8),
        crit("security", "Документи й гроші", 12, "sum", attr="security", target=8),
        crit("electronics", "Заряд електроніки", 10, "sum", attr="power", target=8),
        crit("health", "Здоров'я", 10, "sum", attr="medical", target=8),
        crit("versatility", "Універсальність", 10, "sum", attr="versatility", target=8),
        crit("navigation", "Навігація", 8, "sum", attr="nav", target=8),
        crit("comfort", "Комфорт", 8, "sum", attr="comfort", target=8),
        crit("weight", "Вага багажу", 7, "inverse_sum", attr="weight_kg", limit=7, per_unit=2.0),
        crit("economy", "Економність", 5, "economy"),
    ],
    items=[
        item("down_jacket", "Пуховик", "🧥", "clothes", "critical", {"warmth": 7, "weight_kg": 1.2}),
        item("raincoat", "Дощовик", "🧥", "clothes", "critical", {"rain": 7, "weight_kg": 0.3}),
        item("boots", "Трекінгові черевики", "🥾", "shoes", "critical",
             {"comfort": 4, "rain": 2, "versatility": 3, "weight_kg": 1.3}, 1, "пара"),
        item("rfid_wallet", "Гаманець-сумка з RFID-захистом", "👛", "docs", "critical", {"security": 6, "weight_kg": 0.2}),
        item("uk_adapter", "Адаптер для британських розеток", "🔌", "electronics", "critical",
             {"power": 1, "weight_kg": 0.1}, provides=["uk_socket"]),
        item("fleece", "Флісова кофта", "🧶", "clothes", "important", {"warmth": 4, "versatility": 2, "weight_kg": 0.5}),
        item("thermal", "Термобілизна", "🩲", "clothes", "important", {"warmth": 4, "weight_kg": 0.3}, 1, "набір"),
        item("charger", "Зарядний пристрій для телефона", "🔌", "electronics", "important",
             {"power": 5, "weight_kg": 0.2}, requires=["uk_socket"], provides=["phone_power"],
             desc="Вилка європейського типу."),
        item("first_aid", "Дорожня аптечка", "🩹", "health", "important", {"medical": 7, "weight_kg": 0.4}, 1, "набір"),
        item("offline_maps", "Офлайн-карти (річна підписка)", "🗺️", "nav", "important", {"nav": 6},
             requires=["phone_power"], desc="Працюють, лише поки телефон заряджений."),
        item("umbrella", "Компактна парасолька", "☂️", "clothes", "important", {"rain": 4, "weight_kg": 0.4}),
        item("powerbank", "Павербанк", "🔋", "electronics", "supporting", {"power": 4, "weight_kg": 0.4},
             provides=["phone_power"]),
        item("doc_copies", "Копії документів у файлі", "📄", "docs", "supporting", {"security": 4, "weight_kg": 0.05}),
        item("paper_map", "Паперова мапа", "🗺️", "nav", "supporting", {"nav": 4, "weight_kg": 0.2}),
        item("cold_meds", "Ліки від застуди", "💊", "health", "supporting", {"medical": 3, "weight_kg": 0.1}, 1, "упак."),
        item("daypack", "Компактний рюкзак", "🎒", "bags", "supporting", {"versatility": 5, "weight_kg": 0.5}),
        item("neck_pillow", "Подушка для шиї", "💤", "comfort", "synergy", {"comfort": 4, "weight_kg": 0.3}),
        item("earplugs", "Беруші й маска для сну", "😴", "comfort", "synergy", {"comfort": 3, "weight_kg": 0.05}, 1, "набір"),
        item("sneakers", "Кросівки", "👟", "shoes", "synergy", {"comfort": 4, "versatility": 2, "weight_kg": 0.8}, 1, "пара"),
        item("thermo_mug", "Термокухоль", "☕", "comfort", "synergy", {"comfort": 2, "warmth": 1, "weight_kg": 0.35}),
        item("book", "Книжка в дорогу", "📖", "comfort", "situational", {"comfort": 2, "weight_kg": 0.4}),
        item("camera", "Фотоапарат", "📷", "electronics", "situational", {"versatility": 1, "comfort": 1, "weight_kg": 0.9}),
        item("hat_gloves", "Шапка й рукавички", "🧤", "clothes", "situational", {"warmth": 3, "weight_kg": 0.2}, 1, "набір"),
        item("kilt", "Картатий кілт", "🏴", "clothes", "wildcard", {"warmth": 2, "comfort": 1, "weight_kg": 0.8}),
        item("big_suitcase", "Велика валіза на колесах", "🧳", "bags", "wildcard", {"versatility": 2, "weight_kg": 4.0},
             desc="Містка, але важка — ліміт багажу 7 кг."),
    ],
    synergies=[
        {"id": "dry", "all": ["raincoat", "boots"], "criterion": "rain", "bonus": 1.0,
         "text": "Дощовик + трекінгові черевики: сухо з голови до ніг."},
        {"id": "sleep", "all": ["neck_pillow", "earplugs"], "criterion": "comfort", "bonus": 1.0,
         "text": "Подушка + беруші: можна виспатися в дорозі."},
        {"id": "nav_backup", "all": ["offline_maps", "paper_map"], "criterion": "navigation", "bonus": 1.0,
         "text": "Офлайн-карти + паперова мапа: є резерв, якщо сяде телефон."},
    ],
    penalties=[],
    caps=[
        {"id": "cold", "cond": {"attr": "warmth", "lt": 4}, "cap": 6.0,
         "text": "Немає теплого одягу для осінніх гір — підсумок не вище 6,0."},
    ],
    constraints=[{"tag": None, "category": "clothes", "min": 3}],
)

THEMES = {t["id"]: t for t in (SHELTER, ISLAND, SALAD, SUITCASE)}
for _t in THEMES.values():
    for _i, _c in enumerate(_t["criteria"]):
        _c["priority"] = _i + 1
    _t["item_index"] = {it["key"]: it for it in _t["items"]}


def get(theme_id):
    return THEMES.get(theme_id)


def catalog():
    return [{"id": t["id"], "title": t["title"], "emoji": t["emoji"], "category": t["category"],
             "objective": t["objective"]} for t in THEMES.values()]


def validate_theme(t):
    """Повертає список помилок валідації теми (порожній — тема коректна)."""
    errors = []
    if len(t["criteria"]) != 10:
        errors.append("має бути рівно 10 критеріїв")
    if sum(c["weight"] for c in t["criteria"]) != 100:
        errors.append("сума ваг має дорівнювати 100")
    ids = [c["id"] for c in t["criteria"]]
    keys = [it["key"] for it in t["items"]]
    if len(set(keys)) != len(keys):
        errors.append("дубльовані ключі предметів")
    for it in t["items"]:
        if it["unit"] not in UNITS:
            errors.append(f"{it['key']}: непідтримувана одиниця {it['unit']}")
        if it["role"] not in ROLES:
            errors.append(f"{it['key']}: невідома роль {it['role']}")
        for cap in it["requires"] + it["provides"]:
            if cap not in CAP_LABELS:
                errors.append(f"{it['key']}: невідома можливість {cap}")
        for a, v in it["attrs"].items():
            if a not in t["attr_labels"]:
                errors.append(f"{it['key']}: атрибут {a} без підпису")
            if not isinstance(v, (int, float)) or v < 0 or v > 100000:
                errors.append(f"{it['key']}: недопустиме значення {a}")
    for s in t["synergies"]:
        if s["criterion"] not in ids:
            errors.append(f"синергія {s['id']}: невідомий критерій")
        for k in s["all"]:
            if k not in keys:
                errors.append(f"синергія {s['id']}: невідомий предмет {k}")
    for p in t["penalties"]:
        if p["criterion"] not in ids:
            errors.append(f"штраф {p['id']}: невідомий критерій")
    for c in t["criteria"]:
        if c["type"] == "avg" and any(x not in ids for x in c["of"]):
            errors.append(f"критерій {c['id']}: невідоме посилання")
    need = ROLE_PLAN[20]
    for role, n in need.items():
        have = sum(1 for it in t["items"] if it["role"] == role)
        if have < n:
            errors.append(f"роль {role}: потрібно щонайменше {n}, є {have}")
    return errors


def _plan(lot_count, difficulty):
    plan = dict(ROLE_PLAN[lot_count])
    if lot_count >= 15:
        for role, d in DIFFICULTY_SHIFT.get(difficulty, {}).items():
            plan[role] = max(0, plan[role] + d)
    return plan


def _matches(it, c):
    if c.get("tag"):
        return c["tag"] in it["tags"]
    return it["category"] == c.get("category")


def generate_lots(theme, lot_count, seed, recent_keys=(), difficulty="normal"):
    """Детермінований за seed вибір і порядок лотів (ТЗ §13, §26)."""
    rng = random.Random(seed)
    plan = _plan(lot_count, difficulty)
    recent = set(recent_keys)
    chosen = []
    for role in ROLES:
        pool = [it for it in theme["items"] if it["role"] == role]
        rng.shuffle(pool)
        if role != "critical":  # критичні ресурси можуть повторюватися між партіями
            pool.sort(key=lambda it: it["key"] in recent)
        chosen.extend(pool[:plan[role]])
    rest = [it for it in theme["items"] if it not in chosen]
    rng.shuffle(rest)
    rest.sort(key=lambda it: it["key"] in recent)
    while len(chosen) < lot_count and rest:
        chosen.append(rest.pop(0))
    # Категорійні умови (наприклад, «мінімум два соуси»): підміняємо найменш важливі лоти.
    for c in theme.get("constraints", []):
        have = [it for it in chosen if _matches(it, c)]
        candidates = [it for it in theme["items"] if _matches(it, c) and it not in chosen]
        rng.shuffle(candidates)
        while len(have) < c["min"] and candidates:
            for role in reversed(ROLES):
                victims = [it for it in chosen if it["role"] == role and not _matches(it, c)]
                if victims:
                    new = candidates.pop(0)
                    chosen[chosen.index(victims[-1])] = new
                    have.append(new)
                    break
            else:
                break
    lots = [dict(it) for it in chosen[:lot_count]]
    rng.shuffle(lots)
    return lots
