"""
Sistema de calificación de clubes, ligas y jugadores — WC 2026.
VERSIÓN 3: trofeos últimos 4 años + score de liga computado + posición doméstica + minutos.

Arquitectura (cinco capas):

  1. League International Score (computado dinámicamente)
       Por cada liga, suma los puntos de trofeos INTERNACIONALES de sus clubes.
       Ejemplo: La Liga = UCL×2 + CWC + UEL de Sevilla = 335 pts (máximo → 100%).

  2. League Combined Score
       league_combined = 0.55 × base_quality + 0.45 × intl_prestige_norm
       Blend entre calidad base (UEFA coeff., valor mercado) y victorias internacionales.

  3. Club Position Factor
       position_factor(avg_pos, size) → 1.0 (1º) .. 0.25 (último)
       Terminar campeón en La Liga vale más que terminar campeón en Ligue 1.

  4. Player Environment Score
       env_score = league_combined × (0.25 + 0.40 × position_factor)
                  + 0.35 × club_prestige_norm
       Pesos: 25% liga pura · 40% posición×liga · 35% trofeos del club.

  5. Participation Rate (minutos jugados)
       participation_weight = sqrt(min_pct)   (sin piso: 0 min → 0, titular → 1.0)
       player_score = env_score × participation_weight

Temporadas cubiertas: 2021-22, 2022-23, 2023-24, 2024-25.
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# 1. PESOS DE TROFEOS (sin decay temporal — todos pesan igual si son recientes)
# ---------------------------------------------------------------------------
TROPHY_W: dict[str, float] = {
    "UCL":      100.0,   # UEFA Champions League
    "CWC":       85.0,   # FIFA Club World Cup
    "Lib":       70.0,   # Copa Libertadores
    "UEL":       50.0,   # UEFA Europa League
    "CONCACAF":  28.0,   # CONCACAF Champions League/Cup
    "AFC":       28.0,   # AFC Champions League Elite
    "CAF":       25.0,   # CAF Champions League
    "UECL":      22.0,   # UEFA Conference League
    "Sud":       18.0,   # Copa Sudamericana
    "OFC":       15.0,   # OFC Champions League
    "Rec":        8.0,   # Recopa Sudamericana
    "L_T1":      18.0,   # Liga Tier-1 (PL / La Liga / BL1 / Serie A / Ligue 1)
    "L_T2":      12.0,   # Liga Tier-2 (PPL / Eredivisie / Süper Lig / Belgian…)
    "L_T3":       7.0,   # Liga Tier-3 (Brasileirão / Argentine / MLS / Liga MX…)
    "C_T1":       9.0,   # Copa nacional Tier-1 (FA Cup / Copa del Rey / DFB-Pokal…)
    "C_T2":       5.0,   # Copa nacional Tier-2 / League Cup / otras copas
    "SC":         3.0,   # Super copas nacionales o UEFA Super Cup
}

# Trofeos que computan como INTERNACIONALES para el league international score
INTERNATIONAL_TROPHIES: set[str] = {
    "UCL", "CWC", "Lib", "UEL", "CONCACAF", "AFC", "CAF", "UECL", "Sud", "OFC", "Rec"
}


# ---------------------------------------------------------------------------
# 2. BASE DE DATOS DE TROFEOS — SOLO ÚLTIMOS 4 AÑOS (2022-2026)
#    Temporadas: 2021-22, 2022-23, 2023-24, 2024-25
#    Formato: {trophy_code: count}
# ---------------------------------------------------------------------------
CLUB_TROPHIES: dict[str, dict[str, int]] = {

    # ── CHAMPIONS LEAGUE + LIGAS NACIONALES ────────────────────────────────

    "Real Madrid CF": {
        "UCL":  2,    # 2022 (vs Liverpool), 2024 (vs Dortmund)
        "CWC":  1,    # Feb-2023 (vs Al Hilal)
        "L_T1": 3,    # La Liga: 2021-22, 2023-24, 2024-25
        "SC":   2,    # UEFA Super Cup: 2022, 2024
    },

    "Manchester City FC": {
        "UCL":  1,    # 2023 (vs Inter Milan — 1-0 Istanbul)
        "CWC":  1,    # Dic-2023 (vs Fluminense)
        "L_T1": 3,    # PL: 2021-22, 2022-23, 2023-24
        "C_T1": 1,    # FA Cup: 2023
        "SC":   1,    # Community Shield: 2024
    },

    "FC Internazionale Milano": {
        "UCL":  1,    # 2024-25 (Inter beat PSG en la final de Múnich)
        "L_T1": 2,    # Serie A: 2023-24, 2024-25
        "C_T1": 1,    # Coppa Italia: 2024-25
    },

    "FC Bayern München": {
        "L_T1": 3,    # BL1: 2021-22, 2022-23, 2024-25
        "C_T1": 1,    # DFB-Pokal: 2024-25
    },

    "Bayer 04 Leverkusen": {
        "L_T1": 1,    # BL1: 2023-24 (invicto — 51 partidos sin perder)
        "C_T1": 1,    # DFB-Pokal: 2023-24
    },

    "FC Barcelona": {
        "L_T1": 1,    # La Liga: 2022-23
        "C_T1": 1,    # Copa del Rey: 2022-23 (vs Osasuna)
    },

    "Arsenal FC": {
        "L_T1": 1,    # Premier League: 2024-25
    },

    "Liverpool FC": {
        "C_T1": 1,    # FA Cup: 2021-22
        "C_T2": 1,    # Carabao Cup: 2021-22
    },

    "Manchester United FC": {
        "C_T1": 1,    # FA Cup: 2023-24
    },

    "Chelsea FC": {
        "CWC":  1,    # Feb-2022 (Chelsea vs Palmeiras)
        "C_T2": 1,    # Carabao Cup: 2024-25 (Chelsea beat Newcastle)
    },

    "Aston Villa FC": {
        "C_T2": 1,    # Carabao Cup: 2023-24
    },

    "West Ham United FC": {
        "UECL": 1,    # Conference League: 2022-23 (vs Fiorentina)
    },

    "Atalanta BC": {
        "UEL":  1,    # Europa League: 2023-24
    },

    "Sevilla FC": {
        "UEL":  1,    # Europa League: 2022-23 (7º título)
    },

    "Eintracht Frankfurt": {
        "UEL":  1,    # Europa League: 2021-22 (vs Rangers, penales)
    },

    "AS Roma": {
        "UECL": 1,    # Conference League: 2021-22 (inaugural)
    },

    "Olympiakos CFP": {
        "UECL": 1,    # Conference League: 2023-24
    },

    "SSC Napoli": {
        "L_T1": 1,    # Serie A: 2022-23 (33 años de espera)
    },

    "AC Milan": {
        "L_T1": 1,    # Serie A: 2021-22 (11 años)
    },

    "RB Leipzig": {
        "C_T1": 2,    # DFB-Pokal: 2021-22, 2022-23
    },

    "Paris Saint-Germain FC": {
        "L_T1": 4,    # Ligue 1: 2021-22, 2022-23, 2023-24, 2024-25
        "C_T1": 1,    # Coupe de France: 2024
    },

    "Athletic Club": {
        "C_T1": 1,    # Copa del Rey: 2023-24 (vs Mallorca)
    },

    "Real Betis Balompié": {
        "C_T1": 1,    # Copa del Rey: 2021-22 (penales vs Valencia)
    },

    # ── PRIMERA LIGA ────────────────────────────────────────────────────────

    "Sport Lisboa e Benfica": {
        "L_T2": 3,    # Primeira Liga: 2021-22, 2022-23, 2023-24
    },

    "FC Porto": {
        "L_T2": 1,    # Primeira Liga (1 reciente)
    },

    "Sporting Clube de Portugal": {
        "L_T2": 1,    # Primeira Liga: 2023-24
    },

    # ── EREDIVISIE ──────────────────────────────────────────────────────────

    "AFC Ajax": {
        "L_T2": 1,    # Eredivisie: 2021-22
    },

    "PSV": {
        "L_T2": 2,    # Eredivisie: 2022-23, 2023-24
    },

    "Feyenoord Rotterdam": {
        "L_T2": 1,    # Eredivisie: 2022-23
    },

    # ── TURQUÍA ─────────────────────────────────────────────────────────────

    "Galatasaray SK": {
        "L_T2": 3,    # Süper Lig: 2021-22, 2022-23, 2023-24
        "C_T2": 2,    # Turkish Cup: 2022-23, 2023-24
    },

    "Fenerbahçe SK": {
        "L_T2": 1,    # Süper Lig: 2024-25
    },

    # ── BÉLGICA / ESCOCIA / OTROS UEFA ──────────────────────────────────────

    "Club Brugge KV": {
        "L_T2": 3,    # Belgian Pro League: 2021-22, 2022-23, 2023-24
    },

    "RSC Anderlecht": {
        "L_T2": 1,    # Belgian Pro League: 2024-25
    },

    "Celtic FC": {
        "L_T2": 4,    # Scottish Prem: 2021-22, 2022-23, 2023-24, 2024-25
        "C_T2": 4,    # Scottish Cup + League Cup: varios recientes
    },

    "Rangers FC": {
        "L_T2": 1,    # Scottish Prem: 2020-21 (límite de ventana)
    },

    "SK Slavia Praha": {
        "L_T2": 3,    # Czech First League: 2021-22, 2022-23, 2023-24
        "C_T2": 2,    # Czech Cup
    },

    "FC Red Bull Salzburg": {
        "L_T2": 4,    # Austrian BL: dominación 2022-25
        "C_T2": 3,    # Austrian Cup
    },

    # ── BRASILEIRÃO + COPA LIBERTADORES ─────────────────────────────────────

    "CR Flamengo": {
        "Lib":   1,   # Copa Libertadores: 2022 (vs Athletico Paranaense)
        "Rec":   2,   # Recopa Sudamericana: 2021, 2023
    },

    "Fluminense FC": {
        "Lib":   1,   # Copa Libertadores: 2023 (vs Boca Juniors)
    },

    "Botafogo de Futebol e Regatas": {
        "Lib":   1,   # Copa Libertadores: 2024 (vs Atlético Mineiro)
        "L_T3":  1,   # Brasileirão: 2024
    },

    "SE Palmeiras": {
        "L_T3":  2,   # Brasileirão: 2022, 2023
        "C_T2":  1,   # Copa do Brasil: 2023
    },

    "Clube Atlético Mineiro": {
        "L_T3":  1,   # Brasileirão: 2021 (diciembre 2021)
        "C_T2":  1,   # Copa do Brasil: 2022
    },

    "Sport Club Corinthians Paulista": {
        "C_T2":  1,   # Copa do Brasil: 2022-23
    },

    # ── COPA LIBERTADORES — CLUBES NO BRASILEÑOS ────────────────────────────

    "LDU Quito": {
        "Sud":   1,   # Copa Sudamericana: 2023 (vs Fortaleza)
    },

    # ── ARGENTINA ───────────────────────────────────────────────────────────

    "CA River Plate": {
        "L_T3":  2,   # Argentine Primera: 2 títulos recientes
    },

    "CA Boca Juniors": {
        "L_T3":  1,   # Argentine Primera: 1 reciente
    },

    # ── ASIA / MEDIO ORIENTE ─────────────────────────────────────────────────

    "Al-Hilal SFC": {
        "AFC":   3,   # AFC Champions League: 2021-22, 2022-23, 2023-24
        "L_T3":  3,   # Saudi Pro League: 3 títulos recientes
    },

    "Al Sadd SC": {
        "L_T3":  2,   # Qatar Stars League: 2022-23, 2023-24
    },

    # ── AFRICA ───────────────────────────────────────────────────────────────

    "Al Ahly SC": {
        "CAF":   3,   # CAF Champions League: 2021-22, 2022-23, 2023-24
        "L_T3":  3,   # Egyptian Premier League: 3 recientes
    },

    # ── MÉXICO / CONCACAF ────────────────────────────────────────────────────

    "Club América": {
        "CONCACAF": 2, # CONCACAF Champions Cup: 2022-23, 2023-24
        "L_T3":  2,   # Liga MX: 2 recientes
    },

    "CF Monterrey": {
        "CONCACAF": 1, # CONCACAF CL: 2021-22
    },
}


# ---------------------------------------------------------------------------
# 3. CALIDAD DE LIGA BASE (0-100) — calidad competitiva actual
# ---------------------------------------------------------------------------
LEAGUE_QUALITY: dict[str, float] = {
    "PL":    95.0,
    "PD":    93.0,
    "BL1":   82.0,
    "SA":    78.0,
    "FL1":   74.0,
    "PPL":   68.0,
    "DED":   65.0,
    "ELC":   58.0,
    "TUR":   52.0,
    "BEL":   50.0,
    "SCO":   45.0,
    "AUT":   44.0,
    "CZE":   42.0,
    "DAN":   42.0,
    "NOR":   38.0,
    "SUI":   42.0,
    "GRE":   40.0,
    "CRO":   38.0,
    "CL":    72.0,   # fallback para clubes CL sin mapeo doméstico
    "BSA":   62.0,
    "CLI":   60.0,
    "ARG":   58.0,
    "URU":   45.0,
    "CHI":   40.0,
    "COL":   40.0,
    "ECU":   38.0,   # Liga Pro Ecuador (LDU Quito)
    "MLS":   42.0,
    "LMX":   45.0,
    "CRC":   30.0,
    "JPN":   42.0,
    "KOR":   38.0,
    "CHN":   35.0,
    "SAU":   40.0,
    "IRN":   30.0,
    "QAT":   28.0,
    "AUS":   35.0,
    "UZB":   25.0,
    "EGY":   30.0,
    "MAR":   28.0,
    "SEN":   25.0,
    "RSA":   32.0,   # Premier Soccer League (South Africa)
    "CAF":   35.0,   # CAF Champions League — fallback para clubes africanos sin código doméstico
    "UNK":   25.0,
}

# Tamaño de cada liga — para el cálculo de posición media default (mid-table)
LEAGUE_SIZES: dict[str, int] = {
    "PL": 20, "PD": 20, "SA": 20, "FL1": 18, "BL1": 18,
    "PPL": 18, "DED": 18, "TUR": 18, "BEL": 16,
    "SCO": 12, "AUT": 12, "CZE": 16, "DAN": 14, "NOR": 16,
    "SUI": 12, "GRE": 16, "CRO": 10,
    "BSA": 20, "ARG": 26, "CLI": 16, "ECU": 16, "URU": 16,
    "CHI": 16, "COL": 20,
    "SAU": 18, "QAT": 12, "EGY": 18, "LMX": 18, "MLS": 28,
    "JPN": 18, "KOR": 12, "RSA": 16,
}


# ---------------------------------------------------------------------------
# 4. MAPEO CLUB → LIGA DOMÉSTICA
#    Cubre todos los clubes en CLUB_TROPHIES + clubes de competiciones europeas
# ---------------------------------------------------------------------------
CL_CLUB_DOMESTIC: dict[str, str] = {
    # Turquía
    "Galatasaray SK":             "TUR",
    "Fenerbahçe SK":              "TUR",
    "Trabzonspor":                "TUR",
    # Países Bajos
    "PSV":                        "DED",
    "AFC Ajax":                   "DED",
    "AZ":                         "DED",
    "FC Twente":                  "DED",
    "NEC Nijmegen":               "DED",
    "Feyenoord Rotterdam":        "DED",
    # Portugal
    "Sport Lisboa e Benfica":     "PPL",
    "Sporting Clube de Portugal": "PPL",
    "Sporting Clube de Braga":    "PPL",
    "FC Porto":                   "PPL",
    # República Checa
    "SK Slavia Praha":            "CZE",
    "AC Sparta Praha":            "CZE",
    "FC Viktoria Plzeň":          "CZE",
    # Dinamarca
    "FC København":               "DAN",
    # Noruega
    "FK Bodø/Glimt":              "NOR",
    # Bélgica
    "Club Brugge KV":             "BEL",
    "RSC Anderlecht":             "BEL",
    # Grecia
    "Olympiakos CFP":             "GRE",
    "PAOK FC":                    "GRE",
    # Escocia
    "Celtic FC":                  "SCO",
    "Rangers FC":                 "SCO",
    # Ucrania
    "FC Shakhtar Donetsk":        "UKR",
    "FC Dynamo Kyiv":             "UKR",
    # Austria
    "FC Red Bull Salzburg":       "AUT",
    # Croacia
    "GNK Dinamo Zagreb":          "CRO",
    # Serbia
    "FK Crvena zvezda":           "SRB",
    # Hungría
    "Ferencvárosi TC":            "HUN",
    # Eslovaquia
    "Slovan Bratislava":          "SVK",
}

# Mapeo explícito para clubes de grandes ligas y CONMEBOL/Asia/África
# (complementa CL_CLUB_DOMESTIC — tiene prioridad en la resolución)
CLUB_DOMESTIC_LEAGUE: dict[str, str] = {
    # La Liga
    "Real Madrid CF":                    "PD",
    "FC Barcelona":                      "PD",
    "Atlético de Madrid":                "PD",
    "Atlético Madrid":                   "PD",
    "Sevilla FC":                        "PD",
    "Athletic Club":                     "PD",
    "Real Betis Balompié":               "PD",
    "Villarreal CF":                     "PD",
    "Real Sociedad de Fútbol":           "PD",
    "Girona FC":                         "PD",
    # Premier League
    "Manchester City FC":                "PL",
    "Arsenal FC":                        "PL",
    "Liverpool FC":                      "PL",
    "Chelsea FC":                        "PL",
    "Manchester United FC":              "PL",
    "Tottenham Hotspur FC":              "PL",
    "Newcastle United FC":               "PL",
    "Aston Villa FC":                    "PL",
    "West Ham United FC":                "PL",
    "AFC Bournemouth":                   "PL",
    "Brentford FC":                      "PL",
    "Brighton & Hove Albion FC":         "PL",
    "Fulham FC":                         "PL",
    "Crystal Palace FC":                 "PL",
    "Everton FC":                        "PL",
    "Leeds United FC":                   "PL",
    "Wolverhampton Wanderers FC":        "PL",
    "Nottingham Forest FC":              "PL",
    "Leicester City FC":                 "PL",
    "Southampton FC":                    "PL",
    # Bundesliga
    "FC Bayern München":                 "BL1",
    "Bayer 04 Leverkusen":               "BL1",
    "RB Leipzig":                        "BL1",
    "Borussia Dortmund":                 "BL1",
    "Eintracht Frankfurt":               "BL1",
    "1. FSV Mainz 05":                   "BL1",
    "SC Freiburg":                       "BL1",
    "VfB Stuttgart":                     "BL1",
    "Borussia Mönchengladbach":          "BL1",
    "TSG 1899 Hoffenheim":               "BL1",
    "FC Augsburg":                       "BL1",
    "VfL Wolfsburg":                     "BL1",
    "Werder Bremen":                     "BL1",
    "FC Union Berlin":                   "BL1",
    # Serie A
    "FC Internazionale Milano":          "SA",
    "SSC Napoli":                        "SA",
    "AC Milan":                          "SA",
    "Juventus FC":                       "SA",
    "Atalanta BC":                       "SA",
    "AS Roma":                           "SA",
    "SS Lazio":                          "SA",
    "ACF Fiorentina":                    "SA",
    "Bologna FC 1909":                   "SA",
    "Torino FC":                         "SA",
    # Ligue 1
    "Paris Saint-Germain FC":            "FL1",
    "Olympique de Marseille":            "FL1",
    "Olympique Lyonnais":                "FL1",
    "AS Monaco FC":                      "FL1",
    "LOSC Lille":                        "FL1",
    "RC Lens":                           "FL1",
    "Stade Rennais FC 1901":             "FL1",
    "OGC Nice":                          "FL1",
    # Brasileirão
    "CR Flamengo":                       "BSA",
    "Fluminense FC":                     "BSA",
    "Botafogo de Futebol e Regatas":     "BSA",
    "SE Palmeiras":                      "BSA",
    "Clube Atlético Mineiro":            "BSA",
    "Sport Club Corinthians Paulista":   "BSA",
    "CA Paranaense":                     "BSA",
    "São Paulo FC":                      "BSA",
    "Fortaleza EC":                      "BSA",
    "CR Vasco da Gama":                  "BSA",
    # Argentine Primera
    "CA River Plate":                    "ARG",
    "CA Boca Juniors":                   "ARG",
    "CA Independiente":                  "ARG",
    "CA San Lorenzo de Almagro":         "ARG",
    "Racing Club":                       "ARG",
    "CA Talleres":                       "ARG",
    # Ecuador
    "LDU Quito":                         "ECU",
    "CS Emelec":                         "ECU",
    # Arabia Saudí
    "Al-Hilal SFC":                      "SAU",
    "Al Nassr FC":                       "SAU",
    "Al-Ahli Saudi FC":                  "SAU",
    # Qatar
    "Al Sadd SC":                        "QAT",
    # Egipto
    "Al Ahly SC":                        "EGY",
    "Zamalek SC":                        "EGY",
    # Liga MX
    "Club América":                      "LMX",
    "CF Monterrey":                      "LMX",
    "Club Deportivo Guadalajara":        "LMX",
    "Cruz Azul FC":                      "LMX",
    "UNAM Pumas":                        "LMX",
    "Club Tigres UANL":                  "LMX",
    # MLS
    "LA Galaxy":                         "MLS",
    "Seattle Sounders FC":               "MLS",
    "Inter Miami CF":                    "MLS",
    "New England Revolution":            "MLS",
    "Atlanta United FC":                 "MLS",
    "Toronto FC":                        "MLS",
    "CF Montréal":                       "MLS",
    "New York City FC":                  "MLS",
    "New York Red Bulls":                "MLS",
    "Columbus Crew SC":                  "MLS",
    "Portland Timbers":                  "MLS",
    "FC Cincinnati":                     "MLS",
    "CF Dallas":                         "MLS",
    "Minnesota United FC":               "MLS",
    "San Jose Earthquakes":              "MLS",
    "Colorado Rapids":                   "MLS",
    "Vancouver Whitecaps FC":            "MLS",
    "Sporting Kansas City":              "MLS",
    "Austin FC":                         "MLS",
    "Chicago Fire FC":                   "MLS",
    "Nashville SC":                      "MLS",
    "Charlotte FC":                      "MLS",
    "Real Salt Lake":                    "MLS",
    "Houston Dynamo FC":                 "MLS",
    "St. Louis City SC":                 "MLS",
    "D.C. United":                       "MLS",
    "FC Dallas":                         "MLS",
    "Los Angeles FC":                    "MLS",
    "Philadelphia Union":                "MLS",
    "Orlando City SC":                   "MLS",
    "Revolution New England":            "MLS",
}


# ---------------------------------------------------------------------------
# 5. POSICIÓN PROMEDIO POR CLUB (últimas 4 temporadas domésticas)
#    Fuente: datos históricos reales de cada liga
# ---------------------------------------------------------------------------
CLUB_POSITIONS: dict[str, dict] = {
    # ── LA LIGA (PD, 20 equipos) ────────────────────────────────────────────
    "Real Madrid CF":                 {"avg_pos": 1.25, "league": "PD",  "size": 20},
    "FC Barcelona":                   {"avg_pos": 1.75, "league": "PD",  "size": 20},
    "Atlético Madrid":                {"avg_pos": 3.50, "league": "PD",  "size": 20},
    "Atlético de Madrid":             {"avg_pos": 3.50, "league": "PD",  "size": 20},
    "Sevilla FC":                     {"avg_pos": 5.50, "league": "PD",  "size": 20},
    "Athletic Club":                  {"avg_pos": 5.00, "league": "PD",  "size": 20},
    "Real Betis Balompié":            {"avg_pos": 5.50, "league": "PD",  "size": 20},
    "Villarreal CF":                  {"avg_pos": 6.00, "league": "PD",  "size": 20},
    "Real Sociedad de Fútbol":        {"avg_pos": 5.75, "league": "PD",  "size": 20},
    "Girona FC":                      {"avg_pos": 8.00, "league": "PD",  "size": 20},
    # ── PREMIER LEAGUE (PL, 20 equipos) ─────────────────────────────────────
    "Manchester City FC":             {"avg_pos": 2.25, "league": "PL",  "size": 20},
    "Arsenal FC":                     {"avg_pos": 2.50, "league": "PL",  "size": 20},
    "Liverpool FC":                   {"avg_pos": 4.25, "league": "PL",  "size": 20},
    "Chelsea FC":                     {"avg_pos": 7.50, "league": "PL",  "size": 20},
    "Manchester United FC":           {"avg_pos": 8.00, "league": "PL",  "size": 20},
    "Tottenham Hotspur FC":           {"avg_pos": 6.50, "league": "PL",  "size": 20},
    "Newcastle United FC":            {"avg_pos": 7.00, "league": "PL",  "size": 20},
    "Aston Villa FC":                 {"avg_pos": 7.25, "league": "PL",  "size": 20},
    "West Ham United FC":             {"avg_pos": 9.50, "league": "PL",  "size": 20},
    "AFC Bournemouth":                {"avg_pos": 12.0, "league": "PL",  "size": 20},
    "Brentford FC":                   {"avg_pos": 11.0, "league": "PL",  "size": 20},
    "Brighton & Hove Albion FC":      {"avg_pos": 8.50, "league": "PL",  "size": 20},
    "Fulham FC":                      {"avg_pos": 12.5, "league": "PL",  "size": 20},
    "Crystal Palace FC":              {"avg_pos": 11.0, "league": "PL",  "size": 20},
    "Everton FC":                     {"avg_pos": 14.0, "league": "PL",  "size": 20},
    "Leeds United FC":                {"avg_pos": 14.5, "league": "PL",  "size": 20},
    "Wolverhampton Wanderers FC":     {"avg_pos": 13.0, "league": "PL",  "size": 20},
    "Nottingham Forest FC":           {"avg_pos": 11.5, "league": "PL",  "size": 20},
    "Leicester City FC":              {"avg_pos": 13.5, "league": "PL",  "size": 20},
    "Southampton FC":                 {"avg_pos": 17.0, "league": "PL",  "size": 20},
    # ── BUNDESLIGA (BL1, 18 equipos) ────────────────────────────────────────
    "FC Bayern München":              {"avg_pos": 2.00, "league": "BL1", "size": 18},
    "Bayer 04 Leverkusen":            {"avg_pos": 3.50, "league": "BL1", "size": 18},
    "RB Leipzig":                     {"avg_pos": 3.00, "league": "BL1", "size": 18},
    "Borussia Dortmund":              {"avg_pos": 3.50, "league": "BL1", "size": 18},
    "Eintracht Frankfurt":            {"avg_pos": 7.00, "league": "BL1", "size": 18},
    "1. FSV Mainz 05":                {"avg_pos": 9.00, "league": "BL1", "size": 18},
    "SC Freiburg":                    {"avg_pos": 7.50, "league": "BL1", "size": 18},
    "VfB Stuttgart":                  {"avg_pos": 6.50, "league": "BL1", "size": 18},
    "Borussia Mönchengladbach":       {"avg_pos": 10.0, "league": "BL1", "size": 18},
    "TSG 1899 Hoffenheim":            {"avg_pos": 9.50, "league": "BL1", "size": 18},
    # ── SERIE A (SA, 20 equipos) ─────────────────────────────────────────────
    "FC Internazionale Milano":       {"avg_pos": 2.25, "league": "SA",  "size": 20},
    "SSC Napoli":                     {"avg_pos": 3.25, "league": "SA",  "size": 20},
    "AC Milan":                       {"avg_pos": 3.50, "league": "SA",  "size": 20},
    "Juventus FC":                    {"avg_pos": 3.50, "league": "SA",  "size": 20},
    "Atalanta BC":                    {"avg_pos": 4.50, "league": "SA",  "size": 20},
    "AS Roma":                        {"avg_pos": 5.50, "league": "SA",  "size": 20},
    "SS Lazio":                       {"avg_pos": 5.25, "league": "SA",  "size": 20},
    "ACF Fiorentina":                 {"avg_pos": 6.50, "league": "SA",  "size": 20},
    "Bologna FC 1909":                {"avg_pos": 7.00, "league": "SA",  "size": 20},
    # ── LIGUE 1 (FL1, 18 equipos) ───────────────────────────────────────────
    "Paris Saint-Germain FC":         {"avg_pos": 1.00, "league": "FL1", "size": 18},
    "AS Monaco FC":                   {"avg_pos": 3.00, "league": "FL1", "size": 18},
    "Olympique de Marseille":         {"avg_pos": 3.75, "league": "FL1", "size": 18},
    "RC Lens":                        {"avg_pos": 4.50, "league": "FL1", "size": 18},
    "Olympique Lyonnais":             {"avg_pos": 5.50, "league": "FL1", "size": 18},
    "LOSC Lille":                     {"avg_pos": 4.75, "league": "FL1", "size": 18},
    "Stade Rennais FC 1901":          {"avg_pos": 6.00, "league": "FL1", "size": 18},
    # ── OTRAS EUROPEAS ──────────────────────────────────────────────────────
    "Celtic FC":                      {"avg_pos": 1.00, "league": "SCO", "size": 12},
    "Rangers FC":                     {"avg_pos": 2.00, "league": "SCO", "size": 12},
    "Galatasaray SK":                 {"avg_pos": 1.50, "league": "TUR", "size": 18},
    "Fenerbahçe SK":                  {"avg_pos": 2.00, "league": "TUR", "size": 18},
    "Trabzonspor":                    {"avg_pos": 4.00, "league": "TUR", "size": 18},
    "SK Slavia Praha":                {"avg_pos": 1.75, "league": "CZE", "size": 16},
    "AC Sparta Praha":                {"avg_pos": 2.50, "league": "CZE", "size": 16},
    "FC Red Bull Salzburg":           {"avg_pos": 1.00, "league": "AUT", "size": 12},
    "Sport Lisboa e Benfica":         {"avg_pos": 2.00, "league": "PPL", "size": 18},
    "Sporting Clube de Portugal":     {"avg_pos": 2.50, "league": "PPL", "size": 18},
    "FC Porto":                       {"avg_pos": 2.50, "league": "PPL", "size": 18},
    "PSV":                            {"avg_pos": 2.00, "league": "DED", "size": 18},
    "AFC Ajax":                       {"avg_pos": 3.50, "league": "DED", "size": 18},
    "Feyenoord Rotterdam":            {"avg_pos": 3.00, "league": "DED", "size": 18},
    "Club Brugge KV":                 {"avg_pos": 1.50, "league": "BEL", "size": 16},
    "RSC Anderlecht":                 {"avg_pos": 3.00, "league": "BEL", "size": 16},
    "Olympiakos CFP":                 {"avg_pos": 2.00, "league": "GRE", "size": 16},
    "GNK Dinamo Zagreb":              {"avg_pos": 1.50, "league": "CRO", "size": 10},
    "FK Bodø/Glimt":                  {"avg_pos": 1.50, "league": "NOR", "size": 16},
    # ── BRASILEIRÃO (BSA, 20 equipos) ───────────────────────────────────────
    "CR Flamengo":                    {"avg_pos": 2.50, "league": "BSA", "size": 20},
    "SE Palmeiras":                   {"avg_pos": 2.00, "league": "BSA", "size": 20},
    "Botafogo de Futebol e Regatas":  {"avg_pos": 4.50, "league": "BSA", "size": 20},
    "Fluminense FC":                  {"avg_pos": 5.00, "league": "BSA", "size": 20},
    "Clube Atlético Mineiro":         {"avg_pos": 3.00, "league": "BSA", "size": 20},
    "Sport Club Corinthians Paulista":{"avg_pos": 7.00, "league": "BSA", "size": 20},
    "CA Paranaense":                  {"avg_pos": 5.50, "league": "BSA", "size": 20},
    "São Paulo FC":                   {"avg_pos": 6.00, "league": "BSA", "size": 20},
    # ── ARGENTINA (ARG, ~26 equipos) ────────────────────────────────────────
    "CA River Plate":                 {"avg_pos": 3.00, "league": "ARG", "size": 26},
    "CA Boca Juniors":                {"avg_pos": 4.00, "league": "ARG", "size": 26},
    "Racing Club":                    {"avg_pos": 4.50, "league": "ARG", "size": 26},
    "CA Independiente":               {"avg_pos": 6.00, "league": "ARG", "size": 26},
    # ── ASIA / ÁFRICA / CONCACAF ────────────────────────────────────────────
    "Al-Hilal SFC":                   {"avg_pos": 1.25, "league": "SAU", "size": 18},
    "Al Nassr FC":                    {"avg_pos": 2.50, "league": "SAU", "size": 18},
    "Al Ahly SC":                     {"avg_pos": 1.25, "league": "EGY", "size": 18},
    "Zamalek SC":                     {"avg_pos": 2.50, "league": "EGY", "size": 18},
    "Al Sadd SC":                     {"avg_pos": 2.00, "league": "QAT", "size": 12},
    "Club América":                   {"avg_pos": 2.00, "league": "LMX", "size": 18},
    "CF Monterrey":                   {"avg_pos": 3.00, "league": "LMX", "size": 18},
    "Club Deportivo Guadalajara":     {"avg_pos": 5.00, "league": "LMX", "size": 18},
    "Club Tigres UANL":               {"avg_pos": 3.50, "league": "LMX", "size": 18},
    "Cruz Azul FC":                   {"avg_pos": 4.00, "league": "LMX", "size": 18},
}


# ---------------------------------------------------------------------------
# 6. SCORES COMPUTADOS — Club prestige (basado en trofeos recientes)
# ---------------------------------------------------------------------------

def _compute_raw_scores() -> dict[str, float]:
    return {
        name: sum(TROPHY_W.get(t, 0.0) * count for t, count in trophies.items())
        for name, trophies in CLUB_TROPHIES.items()
    }


_RAW_SCORES: dict[str, float] = _compute_raw_scores()
_MAX_RAW: float = max(_RAW_SCORES.values()) if _RAW_SCORES else 1.0


# ---------------------------------------------------------------------------
# 7. LEAGUE INTERNATIONAL SCORES — computados desde CLUB_TROPHIES
# ---------------------------------------------------------------------------

def _resolve_domestic_league(club: str, fallback_code: str | None = None) -> str | None:
    """Resuelve la liga doméstica de un club: CLUB_DOMESTIC_LEAGUE → CL_CLUB_DOMESTIC → fallback."""
    return (
        CLUB_DOMESTIC_LEAGUE.get(club)
        or CL_CLUB_DOMESTIC.get(club)
        or fallback_code
    )


# Suma de puntos de trofeos INTERNACIONALES por liga
_LEAGUE_INTL_SCORES: dict[str, float] = {}
for _club, _trophies in CLUB_TROPHIES.items():
    _league = _resolve_domestic_league(_club)
    if _league is None:
        continue
    for _code, _count in _trophies.items():
        if _code in INTERNATIONAL_TROPHIES:
            _LEAGUE_INTL_SCORES[_league] = (
                _LEAGUE_INTL_SCORES.get(_league, 0.0) + TROPHY_W[_code] * _count
            )

_MAX_INTL: float = max(_LEAGUE_INTL_SCORES.values(), default=1.0)

# Normalizado 0-100 (la liga con más pts internacionales = 100)
_LEAGUE_INTL_NORM: dict[str, float] = {
    k: round(100.0 * v / _MAX_INTL, 2) for k, v in _LEAGUE_INTL_SCORES.items()
}


# ---------------------------------------------------------------------------
# 8. FUNCIONES DE PUNTUACIÓN
# ---------------------------------------------------------------------------

def club_prestige_norm(club_name: str) -> float | None:
    """
    Puntuación de prestigio normalizada 0-100 basada en trofeos recientes.
    Retorna None si el club no tiene trofeos registrados en los últimos 4 años.
    """
    raw = _RAW_SCORES.get(club_name)
    if raw is None:
        return None
    return round(100.0 * raw / _MAX_RAW, 2)


def league_quality(league_code: str, club_name: str | None = None) -> float:
    """Calidad base de la liga (0-100). Resuelve la liga doméstica para clubes con código CL."""
    code = league_code
    if code == "CL" and club_name:
        code = _resolve_domestic_league(club_name, "CL")
    return LEAGUE_QUALITY.get(code, LEAGUE_QUALITY["UNK"])


def league_combined_score(league_code: str) -> float:
    """
    Score combinado de liga (0-100):
      55% calidad base (UEFA coeff., valor de mercado, nivel general)
      45% prestigio internacional (trofeos continentales de clubs de esa liga, últimos 4 años)

    Ejemplo:
      PD (La Liga): 0.55×93 + 0.45×100 = 96.2  (Real Madrid UCL×2 + CWC + Sevilla UEL)
      PL:           0.55×95 + 0.45×87.2 = 91.7  (Man City UCL+CWC + Chelsea CWC + West Ham UECL)
      FL1:          0.55×74 + 0.45×0   = 40.7   (PSG sin victorias europeas)
    """
    base = LEAGUE_QUALITY.get(league_code, LEAGUE_QUALITY["UNK"])
    intl = _LEAGUE_INTL_NORM.get(league_code, 0.0)
    return round(0.55 * base + 0.45 * intl, 2)


def position_factor(avg_pos: float, league_size: int = 20) -> float:
    """
    Factor posicional: 1º → 1.0 · último → 0.25 · decaimiento lineal.
    Captura el impacto de dónde terminó el club en su liga.
    """
    if league_size <= 1:
        return 1.0
    return max(0.25, 1.0 - 0.75 * (avg_pos - 1.0) / (league_size - 1.0))


def player_context_score(
    club_name: str,
    league_code: str,
    min_pct: float | None = None,
) -> float:
    """
    Score de contexto del jugador (0-100).

    Fórmula V3 — cinco capas:
      1. Liga doméstica resuelta
      2. league_combined = 55% base_quality + 45% intl_prestige_norm
      3. position_factor = f(avg_pos, league_size)  [1.0 → 0.25]
      4. env_score = league_combined × (0.25 + 0.40 × pos_factor) + 0.35 × club_prestige
         Pesos: 25% liga base · 40% posición×liga · 35% trofeos club
      5. player_score = env_score × participation_weight
         participation_weight = sqrt(min_pct)  (sin piso: 0 min → peso 0, titular → 1.0)
         Si min_pct es None → sqrt(0.64) ≈ 0.80 (se asume ~64% de minutos)

    Args:
        club_name:   Nombre del club (debe coincidir con CLUB_TROPHIES o CLUB_POSITIONS)
        league_code: Código de liga del player_club_map.json
        min_pct:     Fracción de minutos jugados (0.0-1.0). None = sin dato → default 0.80
    """
    # 1. Resolver código de liga doméstica
    if league_code == "CL":
        real_code = _resolve_domestic_league(club_name, "CL")
    else:
        real_code = CLUB_DOMESTIC_LEAGUE.get(club_name) or league_code

    # 2. League combined score
    lc = league_combined_score(real_code) / 100.0

    # 3. Position factor
    pos_info = CLUB_POSITIONS.get(club_name)
    if pos_info:
        pf = position_factor(pos_info["avg_pos"], pos_info["size"])
    else:
        size = LEAGUE_SIZES.get(real_code, 18)
        pf = position_factor((size + 1) / 2.0, size)   # mid-table por defecto

    # 4. Club prestige (0.0 si el club no tiene trofeos recientes registrados)
    cp_val = club_prestige_norm(club_name)
    cp = (cp_val or 0.0) / 100.0

    # Environment score: 25% liga · 40% posición×liga · 35% trofeos
    env_score = lc * (0.25 + 0.40 * pf) + 0.35 * cp

    # 5. Participation rate — curva raíz cuadrada: sin piso, proporcional a minutos reales
    # sqrt sube rápido al inicio (10 min ya aporta algo) pero sin regalar el bonus completo
    if min_pct is not None:
        pw = math.sqrt(max(0.0, min(1.0, min_pct)))
    else:
        pw = math.sqrt(0.64)   # default ≈ 0.80, equivale a ~64% de minutos

    return round(env_score * pw * 100.0, 2)


def squad_context_score(
    squad_players: list[dict],
    player_club_map: dict,
) -> dict:
    """
    Score de contexto promedio del equipo nacional (0-100).

    Lee min_pct del player_club_map si está disponible (campo opcional añadido por
    el script enrich_minutes.py). Si no existe, player_context_score usa el default 0.80.

    Retorna: score, mapped, total, coverage, top5_pct, affinity_score, details.
    """
    scores: list[float] = []
    details: list[dict] = []
    mapped_infos: list[dict] = []   # entradas completas de player_club_map para afinidad
    top5_codes = {"PL", "PD", "BL1", "SA", "FL1"}
    top5_count = 0

    for p in squad_players:
        pid = str(p["id"])
        info = player_club_map.get(pid)
        if info is None:
            continue
        club    = info["club"]
        lcode   = info["league_code"]
        min_pct = info.get("min_pct")   # None si el mapa no ha sido enriquecido
        sc = player_context_score(club, lcode, min_pct=min_pct)
        scores.append(sc)
        mapped_infos.append(info)
        details.append({
            "name":    p["name"],
            "club":    club,
            "league":  lcode,
            "score":   sc,
            "min_pct": min_pct,
        })
        if lcode in top5_codes:
            top5_count += 1

    total    = len(squad_players)
    mapped   = len(scores)
    avg      = sum(scores) / mapped if mapped else 0.0
    affinity = squad_affinity_score(mapped_infos)

    return {
        "score":          round(avg, 2),
        "mapped":         mapped,
        "total":          total,
        "coverage":       round(mapped / total, 3) if total else 0.0,
        "top5_pct":       round(top5_count / total, 3) if total else 0.0,
        "affinity_score": round(affinity, 2),
        "details":        sorted(details, key=lambda x: x["score"], reverse=True),
    }


# ---------------------------------------------------------------------------
# CAPA 6: SQUAD AFFINITY — cohesión por liga y club compartido
# ---------------------------------------------------------------------------

_SAME_CLUB_AFF   = 1.00   # compañeros de club: entrenan juntos, máxima cohesión
_SAME_LEAGUE_AFF = 0.55   # misma liga: estilo, ritmo y exigencia compartida
_DIFF_LEAGUE_AFF = 0.15   # ligas distintas: base mínima (fútbol es fútbol)


def _pair_affinity(info_a: dict, info_b: dict) -> float:
    """
    Afinidad entre dos jugadores según su contexto de club y liga.

    Jerarquía:
      mismo club  → 1.00  (compañeros que se conocen a fondo)
      misma liga  → 0.55  (estilo táctico y ritmo similares)
      distintas   → 0.15  (base mínima — ambos son futbolistas profesionales)

    El código "CL" se resuelve a la liga doméstica del club para evitar
    que dos jugadores de clubs distintos (ej. Real Madrid y Arsenal) sean
    tratados erróneamente como compañeros de la misma competición.
    """
    club_a = info_a.get("club", "")
    club_b = info_b.get("club", "")

    # Mismo club → cohesión máxima
    if club_a and club_a == club_b:
        return _SAME_CLUB_AFF

    # Resolver liga efectiva (CL → liga doméstica)
    def _eff_league(info: dict) -> str | None:
        code = info.get("league_code", "")
        if code == "CL":
            return _resolve_domestic_league(info.get("club", ""), None)
        return code or None

    la, lb = _eff_league(info_a), _eff_league(info_b)
    if la and lb and la == lb:
        return _SAME_LEAGUE_AFF

    return _DIFF_LEAGUE_AFF


def squad_affinity_score(mapped_infos: list[dict]) -> float:
    """
    Cohesión media ponderada de todos los pares de jugadores del squad.

    **Diseño:**
    - Evalúa cada par (i, j) y asigna una afinidad:
        • mismo club  → 1.00
        • misma liga  → 0.55
        • distinta    → 0.15
    - Pondera por la media geométrica de min_pct de cada jugador del par.
      (titulares cuentan más — su química en cancha importa más que la de suplentes)
    - Normaliza el resultado al rango [0, 100].

    **Interpretación (valores esperados en squads WC):**
        ~10  → squad muy diverso — 5+ ligas distintas, sin clusters
        ~28  → mix europeo típico (3-4 ligas principales)
        ~45  → concentración alta en una liga (ej. Inglaterra: ~20/26 de PL)
        ~60  → varios clubs con 4+ jugadores cada uno en el squad
        ~85  → squad dominado por 1-2 clubs (situación excepcional)
        100  → todos en el mismo club (imposible en WC)

    Args:
        mapped_infos: entradas de player_club_map (campos: club, league_code, min_pct).

    Returns:
        Puntuación de afinidad en [0, 100].
    """
    n = len(mapped_infos)
    if n < 2:
        return 50.0   # score neutral con 0 o 1 jugadores mapeados

    total_w  = 0.0
    total_wa = 0.0

    for i in range(n):
        for j in range(i + 1, n):
            wi  = mapped_infos[i].get("min_pct") or 0.80
            wj  = mapped_infos[j].get("min_pct") or 0.80
            # Media geométrica: penaliza pares donde uno apenas juega
            w   = (wi * wj) ** 0.5
            aff = _pair_affinity(mapped_infos[i], mapped_infos[j])
            total_wa += w * aff
            total_w  += w

    raw  = total_wa / total_w if total_w > 0 else _DIFF_LEAGUE_AFF
    span = _SAME_CLUB_AFF - _DIFF_LEAGUE_AFF          # 0.85
    return round(max(0.0, min(100.0, (raw - _DIFF_LEAGUE_AFF) / span * 100.0)), 2)
