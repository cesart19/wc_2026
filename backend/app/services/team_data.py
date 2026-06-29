# Static team data for WC 2026 forecasting.
# Sources: FIFA World Rankings (Nov 2025), Transfermarkt squad values (Apr 2026), club ELO.
# Keys match team names returned by football-data.org API.

import logging

log = logging.getLogger(__name__)

TEAM_DATA: dict[str, dict] = {
    # --- CONMEBOL ---
    "Argentina":         {"elo": 2060, "fifa_pts": 1862, "market_value_m": 890},
    "Brazil":            {"elo": 2000, "fifa_pts": 1733, "market_value_m": 1020},
    "Uruguay":           {"elo": 1900, "fifa_pts": 1628, "market_value_m": 330},
    "Colombia":          {"elo": 1890, "fifa_pts": 1635, "market_value_m": 360},
    "Ecuador":           {"elo": 1820, "fifa_pts": 1560, "market_value_m": 210},
    "Venezuela":         {"elo": 1750, "fifa_pts": 1430, "market_value_m": 135},
    "Chile":             {"elo": 1780, "fifa_pts": 1425, "market_value_m": 125},
    "Paraguay":          {"elo": 1740, "fifa_pts": 1350, "market_value_m": 105},
    "Peru":              {"elo": 1730, "fifa_pts": 1340, "market_value_m": 110},
    "Bolivia":           {"elo": 1650, "fifa_pts": 1290, "market_value_m": 60},
    # --- UEFA ---
    "France":            {"elo": 2010, "fifa_pts": 1776, "market_value_m": 1180},
    "England":           {"elo": 1990, "fifa_pts": 1764, "market_value_m": 1100},
    "Spain":             {"elo": 1980, "fifa_pts": 1705, "market_value_m": 980},
    "Germany":           {"elo": 1970, "fifa_pts": 1640, "market_value_m": 965},
    "Portugal":          {"elo": 1960, "fifa_pts": 1710, "market_value_m": 1050},
    "Netherlands":       {"elo": 1950, "fifa_pts": 1708, "market_value_m": 850},
    "Belgium":           {"elo": 1930, "fifa_pts": 1736, "market_value_m": 745},
    "Italy":             {"elo": 1920, "fifa_pts": 1679, "market_value_m": 720},
    "Croatia":           {"elo": 1870, "fifa_pts": 1688, "market_value_m": 380},
    "Denmark":           {"elo": 1855, "fifa_pts": 1598, "market_value_m": 490},
    "Switzerland":       {"elo": 1850, "fifa_pts": 1594, "market_value_m": 420},
    "Austria":           {"elo": 1840, "fifa_pts": 1540, "market_value_m": 430},
    "Turkey":            {"elo": 1830, "fifa_pts": 1535, "market_value_m": 510},
    "Poland":            {"elo": 1800, "fifa_pts": 1480, "market_value_m": 250},
    "Serbia":            {"elo": 1790, "fifa_pts": 1530, "market_value_m": 310},
    "Scotland":          {"elo": 1770, "fifa_pts": 1408, "market_value_m": 205},
    "Hungary":           {"elo": 1760, "fifa_pts": 1400, "market_value_m": 185},
    "Ukraine":           {"elo": 1750, "fifa_pts": 1490, "market_value_m": 310},
    "Slovakia":          {"elo": 1740, "fifa_pts": 1395, "market_value_m": 135},
    "Albania":           {"elo": 1710, "fifa_pts": 1375, "market_value_m": 115},
    "Wales":             {"elo": 1720, "fifa_pts": 1388, "market_value_m": 165},
    "Czech Republic":    {"elo": 1730, "fifa_pts": 1410, "market_value_m": 220},
    "Czechia":           {"elo": 1730, "fifa_pts": 1410, "market_value_m": 220},
    "Slovenia":          {"elo": 1715, "fifa_pts": 1380, "market_value_m": 145},
    "Georgia":           {"elo": 1700, "fifa_pts": 1360, "market_value_m": 135},
    "Romania":           {"elo": 1720, "fifa_pts": 1395, "market_value_m": 220},
    "Greece":            {"elo": 1710, "fifa_pts": 1372, "market_value_m": 190},
    "Norway":            {"elo": 1700, "fifa_pts": 1370, "market_value_m": 295},
    # --- CONCACAF ---
    "USA":               {"elo": 1870, "fifa_pts": 1650, "market_value_m": 520},
    "Mexico":            {"elo": 1860, "fifa_pts": 1606, "market_value_m": 340},
    "Canada":            {"elo": 1830, "fifa_pts": 1546, "market_value_m": 285},
    "Panama":            {"elo": 1760, "fifa_pts": 1355, "market_value_m": 95},
    "Honduras":          {"elo": 1720, "fifa_pts": 1325, "market_value_m": 75},
    "Costa Rica":        {"elo": 1730, "fifa_pts": 1338, "market_value_m": 90},
    "Jamaica":           {"elo": 1700, "fifa_pts": 1335, "market_value_m": 85},
    "El Salvador":       {"elo": 1680, "fifa_pts": 1310, "market_value_m": 55},
    "Guatemala":         {"elo": 1670, "fifa_pts": 1295, "market_value_m": 45},
    "Trinidad and Tobago": {"elo": 1660, "fifa_pts": 1275, "market_value_m": 40},
    # --- CAF ---
    "Morocco":           {"elo": 1880, "fifa_pts": 1645, "market_value_m": 315},
    "Senegal":           {"elo": 1860, "fifa_pts": 1612, "market_value_m": 285},
    "Nigeria":           {"elo": 1820, "fifa_pts": 1511, "market_value_m": 205},
    "Egypt":             {"elo": 1810, "fifa_pts": 1492, "market_value_m": 175},
    "Ivory Coast":       {"elo": 1800, "fifa_pts": 1482, "market_value_m": 225},
    "Côte d'Ivoire":     {"elo": 1800, "fifa_pts": 1482, "market_value_m": 225},
    "Cameroon":          {"elo": 1780, "fifa_pts": 1460, "market_value_m": 165},
    "Algeria":           {"elo": 1770, "fifa_pts": 1445, "market_value_m": 165},
    "Tunisia":           {"elo": 1760, "fifa_pts": 1440, "market_value_m": 135},
    "Mali":              {"elo": 1750, "fifa_pts": 1430, "market_value_m": 125},
    "South Africa":      {"elo": 1730, "fifa_pts": 1412, "market_value_m": 165},
    "Ghana":             {"elo": 1720, "fifa_pts": 1450, "market_value_m": 145},
    "DR Congo":          {"elo": 1710, "fifa_pts": 1418, "market_value_m": 115},
    "Congo DR":          {"elo": 1710, "fifa_pts": 1418, "market_value_m": 115},
    "Zambia":            {"elo": 1700, "fifa_pts": 1380, "market_value_m": 65},
    "Tanzania":          {"elo": 1670, "fifa_pts": 1340, "market_value_m": 45},
    "Comoros":           {"elo": 1650, "fifa_pts": 1295, "market_value_m": 30},
    "Mozambique":        {"elo": 1640, "fifa_pts": 1285, "market_value_m": 25},
    "Uganda":            {"elo": 1690, "fifa_pts": 1360, "market_value_m": 55},
    # --- AFC ---
    "Japan":             {"elo": 1870, "fifa_pts": 1618, "market_value_m": 375},
    "South Korea":       {"elo": 1840, "fifa_pts": 1564, "market_value_m": 345},
    "Korea Republic":    {"elo": 1840, "fifa_pts": 1564, "market_value_m": 345},
    "Iran":              {"elo": 1820, "fifa_pts": 1523, "market_value_m": 155},
    "Saudi Arabia":      {"elo": 1800, "fifa_pts": 1472, "market_value_m": 185},
    "Australia":         {"elo": 1800, "fifa_pts": 1558, "market_value_m": 230},
    "Iraq":              {"elo": 1770, "fifa_pts": 1310, "market_value_m": 95},
    "Uzbekistan":        {"elo": 1760, "fifa_pts": 1318, "market_value_m": 105},
    "Jordan":            {"elo": 1750, "fifa_pts": 1295, "market_value_m": 85},
    "China PR":          {"elo": 1700, "fifa_pts": 1260, "market_value_m": 110},
    "China":             {"elo": 1700, "fifa_pts": 1260, "market_value_m": 110},
    "Bahrain":           {"elo": 1690, "fifa_pts": 1245, "market_value_m": 70},
    "Oman":              {"elo": 1680, "fifa_pts": 1235, "market_value_m": 55},
    "Indonesia":         {"elo": 1660, "fifa_pts": 1255, "market_value_m": 75},
    # --- OFC ---
    "New Zealand":       {"elo": 1680, "fifa_pts": 1280, "market_value_m": 55},
    # --- Intercontinental (probable) ---
    "Qatar":             {"elo": 1720, "fifa_pts": 1270, "market_value_m": 85},
    # --- Añadidos 2026-06-13: clasificados WC26 ausentes del dataset inicial.
    # Caían silenciosamente a DEFAULT_DATA (~promedio), distorsionando sus
    # pronósticos (caso Canada-Bosnia: Bosnia rateada como promedio pese a
    # eliminar a Italia). Escala consistente con las entradas existentes.
    "United States":     {"elo": 1870, "fifa_pts": 1650, "market_value_m": 520},  # alias football-data de "USA"
    "Bosnia-Herzegovina": {"elo": 1750, "fifa_pts": 1485, "market_value_m": 170},  # eliminó a Italia en repechaje
    "Sweden":            {"elo": 1820, "fifa_pts": 1528, "market_value_m": 430},  # Isak + Gyökeres elevan el valor
    "Cape Verde Islands": {"elo": 1690, "fifa_pts": 1400, "market_value_m": 60},   # debutante CAF
    "Cape Verde":        {"elo": 1690, "fifa_pts": 1400, "market_value_m": 60},   # alias football-data de "Cape Verde Islands"
    "Curaçao":           {"elo": 1655, "fifa_pts": 1330, "market_value_m": 35},   # debutante CONCACAF
    "Haiti":             {"elo": 1650, "fifa_pts": 1320, "market_value_m": 45},
}

# Fallback for teams not in the dict
DEFAULT_DATA: dict = {"elo": 1640, "fifa_pts": 1250, "market_value_m": 80}


def get_team_data(name: str) -> dict:
    return TEAM_DATA.get(name, DEFAULT_DATA)


# ---------------------------------------------------------------------------
# Crowd support index for WC 2026 (hosted in North America)
# Three components: co-host venue, diaspora size in USA/Canada, neutral sympathy
# ---------------------------------------------------------------------------

CROWD_SUPPORT: dict[str, int] = {
    # Co-hosts (máxima ventaja de sede)
    "USA":                100,
    "Mexico":              98,  # 37M de origen mexicano en USA + 3 sedes propias
    "Canada":              85,
    # CONCACAF — juegan prácticamente en casa
    "Honduras":            60,  # 1M diasp. USA
    "El Salvador":         58,  # 2.3M diasp. USA
    "Guatemala":           55,  # 1M diasp.
    "Costa Rica":          52,  # 800k diasp.
    "Panama":              50,  # 400k diasp.
    "Jamaica":             45,  # 700k diasp. caribeña
    "Trinidad and Tobago": 38,
    # Sudamérica — diáspora + factor simpatía
    "Brazil":              68,  # 1.5M diasp. + "quinta squadra" mundial
    "Argentina":           65,  # 800k diasp. + popularidad post-2022
    "Colombia":            58,  # 1.2M diasp. USA
    "Ecuador":             52,  # 700k diasp.
    "Venezuela":           45,  # 500k diasp.
    "Chile":               38,
    "Uruguay":             35,
    "Peru":                32,
    "Bolivia":             28,
    "Paraguay":            28,
    # Europa — comunidades históricas en USA, menor que Américas
    "Italy":               22,  # fuerte comunidad ítalo-americana
    "Portugal":            20,
    "Poland":              20,  # gran diasp. polaca en Chicago/NY
    "Greece":              18,
    "Spain":               18,
    "Germany":             16,
    "England":             15,
    "France":              14,  # diasp. franco-caribeña en NY/Miami
    "Netherlands":         12,
    "Croatia":             12,
    "Serbia":              12,
    "Ukraine":             14,
    "Albania":             10,
    "Slovakia":            10,
    "Czech Republic":      10,
    "Czechia":             10,
    "Romania":             10,
    "Hungary":             10,
    "Slovenia":             9,
    "Georgia":              8,
    "Austria":             10,
    "Switzerland":         10,
    "Turkey":              12,  # diasp. turca moderada en NY
    "Denmark":              8,
    "Belgium":              8,
    "Wales":                8,
    "Scotland":             8,
    # África — poca representación en Norteamérica
    "Morocco":              8,   # comunidad marroquí moderada
    "Nigeria":              7,
    "Senegal":              6,
    "Egypt":                6,
    "Ivory Coast":          6,
    "Côte d'Ivoire":        6,
    # Asia / Oceanía
    "Japan":                6,
    "South Korea":          6,
    "Korea Republic":       6,
    # África (sin entrada previa → usaban DEFAULT 5 incorrectamente)
    "Cameroon":             8,   # diáspora africana en NY/DC
    "Algeria":              7,
    "Tunisia":              7,
    "Mali":                 6,
    "South Africa":         6,
    "Ghana":                8,   # notable comunidad ghaneana en NY/DC
    "DR Congo":             6,
    "Congo DR":             6,
    "Zambia":               5,
    "Tanzania":             5,
    "Comoros":              5,
    "Mozambique":           5,
    "Uganda":               6,
    # Oriente Medio / Asia Central
    "Iran":                 8,   # comunidad iraní significativa en LA/DC
    "Saudi Arabia":         6,
    "Australia":            7,   # diáspora anglosajona
    "Iraq":                 6,
    "Uzbekistan":           5,
    "Jordan":               6,
    "China PR":             7,   # comunidad china significativa en EEUU
    "China":                7,
    "Bahrain":              5,
    "Oman":                 5,
    "Indonesia":            6,
    # Europa (faltante)
    "Norway":               7,
    # OFC
    "New Zealand":          6,
    # Varios
    "Qatar":                5,
    # --- Añadidos 2026-06-13 (ver TEAM_DATA) ---
    "United States":      100,  # co-anfitrión (alias football-data de "USA")
    "Bosnia-Herzegovina":  11,  # comunidad bosnia notable (St. Louis ~70k)
    "Sweden":               9,
    "Cape Verde Islands":   6,  # comunidad caboverdiana (Nueva Inglaterra)
    "Cape Verde":           6,  # alias football-data de "Cape Verde Islands"
    "Curaçao":              7,  # diáspora caribeña/neerlandesa
    "Haiti":               12,  # gran comunidad haitiana en Florida/NY
}

DEFAULT_CROWD_SUPPORT: int = 8  # neutral-turista; mín. Europeo en lista = 8 (DEN/BEL/WAL/SCO)

# ---------------------------------------------------------------------------
# Overrides por país-sede. La tabla CROWD_SUPPORT modela diáspora en
# USA/Canadá y es ciega a la sede: en estadios mexicanos la composición de
# la grada cambia (simpatía del público local, hinchadas viajeras,
# comunidades residentes en México). Solo agregar entradas con justificación
# documentada — validado en KOR-CZE (Guadalajara, 2026-06-12): ola Hallyu
# entre el público mexicano neutral, Red Devils viajeros y comunidad
# coreana industrial (NL/QRO/CDMX).
# ---------------------------------------------------------------------------
CROWD_SUPPORT_BY_HOST: dict[str, dict[str, int]] = {
    "South Korea":    {"Mexico": 22},
    "Korea Republic": {"Mexico": 22},
}


def get_crowd_support(name: str, host_country: str | None = None) -> int:
    """Crowd support index for WC 2026 (0-100). Higher = more local fan support.

    Args:
        name: Nombre de la selección.
        host_country: País anfitrión de la sede ("USA" | "Mexico" | "Canada").
            Si hay override por sede para el equipo, tiene prioridad sobre
            el índice global (que modela diáspora en USA/Canadá).
    """
    if host_country:
        override = CROWD_SUPPORT_BY_HOST.get(name, {}).get(host_country)
        if override is not None:
            return override
    return CROWD_SUPPORT.get(name, DEFAULT_CROWD_SUPPORT)


# ---------------------------------------------------------------------------
# FIFA ranking points trajectory (Dec 2024 → May 2026)
# trend_18m : Actual (May 2026) − Dec 2024  — long-run trajectory
# momentum  : Actual (May 2026) − Jan 2026  — recent form / hot-cold streak
# Source: ranking_fifa_18_meses_completo.csv
# ---------------------------------------------------------------------------

TREND_DATA: dict[str, dict] = {
    # ── Top-ranked / consistent improvers ──────────────────────────────────
    "France":             {"trend_18m": 24.0, "momentum":  5.0},
    "Spain":              {"trend_18m": 16.5, "momentum":  2.0},
    "Argentina":          {"trend_18m": 15.0, "momentum":  5.0},
    "England":            {"trend_18m": 13.5, "momentum":  2.0},
    "Portugal":           {"trend_18m": 18.0, "momentum":  5.0},
    "Brazil":             {"trend_18m": 15.5, "momentum":  2.0},
    "Netherlands":        {"trend_18m": 20.0, "momentum":  5.0},
    "Morocco":            {"trend_18m": 12.5, "momentum":  2.0},
    "Belgium":            {"trend_18m": 17.0, "momentum":  5.0},
    "Germany":            {"trend_18m": 15.5, "momentum":  2.0},
    "Croatia":            {"trend_18m": 19.0, "momentum":  5.0},
    "Italy":              {"trend_18m": 11.5, "momentum":  2.0},
    "Colombia":           {"trend_18m": 22.0, "momentum":  5.0},
    "Senegal":            {"trend_18m": 14.5, "momentum":  2.0},
    "Mexico":             {"trend_18m": 13.0, "momentum":  5.0},
    "USA":                {"trend_18m": 16.5, "momentum":  2.0},
    "Uruguay":            {"trend_18m": 21.0, "momentum":  5.0},
    "Japan":              {"trend_18m": 13.5, "momentum":  2.0},
    "Switzerland":        {"trend_18m": 18.0, "momentum":  5.0},
    "Denmark":            {"trend_18m": 10.5, "momentum":  2.0},
    "Ecuador":            {"trend_18m": 20.0, "momentum":  5.0},
    "Iran":               {"trend_18m": 18.5, "momentum":  2.0},
    "South Korea":        {"trend_18m": 17.0, "momentum":  5.0},
    "Korea Republic":     {"trend_18m": 17.0, "momentum":  5.0},
    "Australia":          {"trend_18m":  9.5, "momentum":  2.0},
    "Ukraine":            {"trend_18m": 20.0, "momentum":  5.0},
    "Austria":            {"trend_18m": 17.5, "momentum":  2.0},
    "Poland":             {"trend_18m": 16.0, "momentum":  5.0},
    "Wales":              {"trend_18m": 19.0, "momentum":  5.0},
    "Hungary":            {"trend_18m": 11.5, "momentum":  2.0},
    "Tunisia":            {"trend_18m": 21.0, "momentum":  5.0},
    "Algeria":            {"trend_18m": 13.5, "momentum":  2.0},
    "Egypt":              {"trend_18m": 18.0, "momentum":  5.0},
    "Nigeria":            {"trend_18m": 16.5, "momentum":  2.0},
    "Cameroon":           {"trend_18m": 15.0, "momentum":  5.0},
    "Ivory Coast":        {"trend_18m": 12.5, "momentum":  2.0},
    "Côte d'Ivoire":      {"trend_18m": 12.5, "momentum":  2.0},
    "Panama":             {"trend_18m": 23.0, "momentum":  5.0},
    "Costa Rica":         {"trend_18m": 15.5, "momentum":  2.0},
    "Jamaica":            {"trend_18m": 14.0, "momentum":  5.0},
    "Canada":             {"trend_18m": 12.5, "momentum":  2.0},
    "Peru":               {"trend_18m": 22.0, "momentum":  5.0},
    "Chile":              {"trend_18m": 14.5, "momentum":  2.0},
    "Venezuela":          {"trend_18m": 19.0, "momentum":  5.0},
    "Paraguay":           {"trend_18m": 11.5, "momentum":  2.0},
    "Bolivia":            {"trend_18m": 16.0, "momentum":  5.0},
    "Saudi Arabia":       {"trend_18m": 19.5, "momentum":  2.0},
    "Qatar":              {"trend_18m": 18.0, "momentum":  5.0},
    "Iraq":               {"trend_18m": 10.5, "momentum":  2.0},
    "New Zealand":        {"trend_18m": 21.0, "momentum":  5.0},
    "Honduras":           {"trend_18m": 17.0, "momentum":  5.0},
    "El Salvador":        {"trend_18m": 15.5, "momentum":  2.0},
    "Czechia":            {"trend_18m": 19.0, "momentum":  5.0},  # football-data.org retorna "Czechia"
    "Czech Republic":     {"trend_18m": 19.0, "momentum":  5.0},  # alias alternativo (odds API)
    # ── Stagnating / slightly declining (rows 53-104 in source) ────────────
    "South Africa":       {"trend_18m":  4.5, "momentum": -2.0},
    "Ghana":              {"trend_18m":  4.5, "momentum": -2.0},
    "Romania":            {"trend_18m":  4.5, "momentum": -2.0},
    "Norway":             {"trend_18m":  4.5, "momentum": -2.0},
    "Greece":             {"trend_18m":  4.5, "momentum": -2.0},
    "Slovakia":           {"trend_18m":  4.5, "momentum": -2.0},
    "Slovenia":           {"trend_18m":  4.5, "momentum": -2.0},
    "Albania":            {"trend_18m":  4.5, "momentum": -2.0},
    "Georgia":            {"trend_18m":  4.5, "momentum": -2.0},
    "Uzbekistan":         {"trend_18m":  4.5, "momentum": -2.0},
    "Jordan":             {"trend_18m":  4.5, "momentum": -2.0},
    "Oman":               {"trend_18m":  4.5, "momentum": -2.0},
    "Bahrain":            {"trend_18m":  4.5, "momentum": -2.0},
    "Guatemala":          {"trend_18m":  4.5, "momentum": -2.0},
    "Trinidad and Tobago":{"trend_18m":  4.5, "momentum": -2.0},
    "Zambia":             {"trend_18m":  4.5, "momentum": -2.0},
    "Uganda":             {"trend_18m":  4.5, "momentum": -2.0},
    "DR Congo":           {"trend_18m":  4.5, "momentum": -2.0},
    "Congo DR":           {"trend_18m":  4.5, "momentum": -2.0},
    # --- Añadidos 2026-06-13 (ver TEAM_DATA) ---
    "United States":      {"trend_18m": 16.5, "momentum":  2.0},  # alias de "USA"
    "Bosnia-Herzegovina": {"trend_18m":  8.5, "momentum":  2.0},  # alza tras clasificar vía repechaje
    "Sweden":             {"trend_18m": 10.0, "momentum":  2.0},
    "Cape Verde Islands": {"trend_18m":  9.0, "momentum":  5.0},  # ascenso (1a clasificación)
    "Cape Verde":         {"trend_18m":  9.0, "momentum":  5.0},  # alias football-data de "Cape Verde Islands"
    "Curaçao":            {"trend_18m":  7.0, "momentum":  5.0},
    "Haiti":              {"trend_18m":  4.5, "momentum": -2.0},
    # Detectados por el guardrail (2026-06-13): tenían elo/crowd pero no trend.
    "Turkey":             {"trend_18m": 13.5, "momentum":  2.0},  # plantel joven en ascenso
    "Scotland":           {"trend_18m":  7.0, "momentum":  2.0},
}

DEFAULT_TREND: dict = {"trend_18m": 0.0, "momentum": 0.0}


def get_trend_data(name: str) -> dict:
    """FIFA ranking trend (18-month change) and recent momentum for WC 2026 prediction."""
    return TREND_DATA.get(name, DEFAULT_TREND)


# ---------------------------------------------------------------------------
# Guardrail anti-default: detectar selecciones sin rating explícito antes de
# que caigan silenciosamente al promedio (caso Bosnia/USA, 2026-06-13).
# ---------------------------------------------------------------------------

_warned_defaults: set[str] = set()


def missing_ratings(name: str) -> list[str]:
    """Fuentes de rating que NO tienen entrada explícita para `name`.

    Lista vacía ⇒ la selección está completamente rateada. Una lista no
    vacía significa que `name` cae a valores por defecto en esas fuentes
    (promediándose y borrando su nivel real). El crowd se considera
    presente si existe entrada base o algún override por sede.
    """
    has_crowd = name in CROWD_SUPPORT or name in {
        team for hosts in CROWD_SUPPORT_BY_HOST.values() for team in hosts
    }
    missing = []
    if name not in TEAM_DATA:
        missing.append("TEAM_DATA")
    if not has_crowd:
        missing.append("CROWD_SUPPORT")
    if name not in TREND_DATA:
        missing.append("TREND_DATA")
    return missing


def warn_if_unrated(name: str) -> list[str]:
    """Emite un warning (una vez por nombre y proceso) si falta rating.

    Devuelve la lista de fuentes faltantes para que el llamador pueda
    además marcarlo en su reporte. No spamea: deduplica por nombre.
    """
    missing = missing_ratings(name)
    if missing and name not in _warned_defaults:
        _warned_defaults.add(name)
        log.warning(
            "Rating incompleto para %r: usa valores por defecto en %s. "
            "Agrégalo a team_data.py para un pronóstico fiable.",
            name,
            ", ".join(missing),
        )
    return missing
