# Static venue mapping keyed by "HomeTeam|AwayTeam" using exact API team names.
# Source: official WC 2026 schedule (mlssoccer.com, June 2026)
_VENUES: dict[str, str] = {
    # GROUP A
    "Mexico|South Africa":          "Estadio Azteca · Ciudad de México",
    "South Korea|Czechia":          "Estadio Akron · Guadalajara",
    "Mexico|South Korea":           "Estadio Akron · Guadalajara",
    "Czechia|South Africa":         "Mercedes-Benz Stadium · Atlanta",
    "Czechia|Mexico":               "Estadio Azteca · Ciudad de México",
    "South Africa|South Korea":     "Estadio BBVA · Monterrey",
    # GROUP B
    "Canada|Bosnia-Herzegovina":    "BMO Field · Toronto",
    "Qatar|Switzerland":            "Levi's Stadium · San Francisco",
    "Switzerland|Bosnia-Herzegovina": "SoFi Stadium · Los Angeles",
    "Canada|Qatar":                 "BC Place · Vancouver",
    "Bosnia-Herzegovina|Qatar":     "Lumen Field · Seattle",
    "Switzerland|Canada":           "BC Place · Vancouver",
    # GROUP C
    "Brazil|Morocco":               "MetLife Stadium · New York/New Jersey",
    "Haiti|Scotland":               "Gillette Stadium · Boston",
    "Brazil|Haiti":                 "Lincoln Financial Field · Philadelphia",
    "Scotland|Morocco":             "Gillette Stadium · Boston",
    "Morocco|Haiti":                "Hard Rock Stadium · Miami",
    "Scotland|Brazil":              "Hard Rock Stadium · Miami",
    # GROUP D
    "United States|Paraguay":       "SoFi Stadium · Los Angeles",
    "Australia|Turkey":             "BC Place · Vancouver",
    "United States|Australia":      "Lumen Field · Seattle",
    "Turkey|Paraguay":              "Levi's Stadium · San Francisco",
    "Turkey|United States":         "SoFi Stadium · Los Angeles",
    "Paraguay|Australia":           "Levi's Stadium · San Francisco",
    # GROUP E
    "Germany|Curaçao":              "NRG Stadium · Houston",
    "Ivory Coast|Ecuador":          "Lincoln Financial Field · Philadelphia",
    "Germany|Ivory Coast":          "BMO Field · Toronto",
    "Ecuador|Curaçao":              "GEHA Field at Arrowhead · Kansas City",
    "Ecuador|Germany":              "MetLife Stadium · New York/New Jersey",
    "Curaçao|Ivory Coast":          "Lincoln Financial Field · Philadelphia",
    # GROUP F
    "Netherlands|Japan":            "AT&T Stadium · Dallas",
    "Sweden|Tunisia":               "Estadio BBVA · Monterrey",
    "Netherlands|Sweden":           "NRG Stadium · Houston",
    "Tunisia|Japan":                "Estadio BBVA · Monterrey",
    "Tunisia|Netherlands":          "GEHA Field at Arrowhead · Kansas City",
    "Japan|Sweden":                 "AT&T Stadium · Dallas",
    # GROUP G
    "Iran|New Zealand":             "SoFi Stadium · Los Angeles",
    "Belgium|Egypt":                "Lumen Field · Seattle",
    "Belgium|Iran":                 "SoFi Stadium · Los Angeles",
    "New Zealand|Egypt":            "BC Place · Vancouver",
    "Egypt|Iran":                   "Lumen Field · Seattle",
    "New Zealand|Belgium":          "BC Place · Vancouver",
    # GROUP H
    "Spain|Cape Verde Islands":     "Mercedes-Benz Stadium · Atlanta",
    "Saudi Arabia|Uruguay":         "Hard Rock Stadium · Miami",
    "Spain|Saudi Arabia":           "Mercedes-Benz Stadium · Atlanta",
    "Uruguay|Cape Verde Islands":   "Hard Rock Stadium · Miami",
    "Uruguay|Spain":                "Estadio Akron · Guadalajara",
    "Cape Verde Islands|Saudi Arabia": "NRG Stadium · Houston",
    # GROUP I
    "France|Senegal":               "MetLife Stadium · New York/New Jersey",
    "Iraq|Norway":                  "Gillette Stadium · Boston",
    "Norway|Senegal":               "MetLife Stadium · New York/New Jersey",
    "France|Iraq":                  "Lincoln Financial Field · Philadelphia",
    "Norway|France":                "Gillette Stadium · Boston",
    "Senegal|Iraq":                 "BMO Field · Toronto",
    # GROUP J
    "Argentina|Algeria":            "GEHA Field at Arrowhead · Kansas City",
    "Austria|Jordan":               "Levi's Stadium · San Francisco",
    "Argentina|Austria":            "AT&T Stadium · Dallas",
    "Jordan|Algeria":               "Levi's Stadium · San Francisco",
    "Jordan|Argentina":             "AT&T Stadium · Dallas",
    "Algeria|Austria":              "GEHA Field at Arrowhead · Kansas City",
    # GROUP K
    "Portugal|Congo DR":            "NRG Stadium · Houston",
    "Uzbekistan|Colombia":          "Estadio Azteca · Ciudad de México",
    "Colombia|Congo DR":            "Estadio Akron · Guadalajara",
    "Portugal|Uzbekistan":          "NRG Stadium · Houston",
    "Colombia|Portugal":            "Hard Rock Stadium · Miami",
    "Congo DR|Uzbekistan":          "Mercedes-Benz Stadium · Atlanta",
    # GROUP L
    "England|Croatia":              "AT&T Stadium · Dallas",
    "Ghana|Panama":                 "BMO Field · Toronto",
    "England|Ghana":                "Gillette Stadium · Boston",
    "Panama|Croatia":               "BMO Field · Toronto",
    "Croatia|Ghana":                "Lincoln Financial Field · Philadelphia",
    "Panama|England":               "MetLife Stadium · New York/New Jersey",
}


# Knockout stage venue mapping by match ID (teams are TBD until groups finish)
_KNOCKOUT_VENUES: dict[int, str] = {
    # LAST_32  (Round of 32)
    537417: "SoFi Stadium · Los Angeles",
    537423: "NRG Stadium · Houston",
    537415: "Gillette Stadium · Boston",
    537418: "Estadio BBVA · Monterrey",
    537424: "AT&T Stadium · Dallas",
    537416: "MetLife Stadium · New York/New Jersey",
    537425: "Estadio Azteca · Ciudad de México",
    537426: "Levi's Stadium · San Francisco",
    537422: "Lumen Field · Seattle",
    537421: "Mercedes-Benz Stadium · Atlanta",
    537420: "BMO Field · Toronto",
    537419: "SoFi Stadium · Los Angeles",
    537429: "BC Place · Vancouver",
    537428: "Hard Rock Stadium · Miami",
    537427: "GEHA Field at Arrowhead · Kansas City",
    537430: "AT&T Stadium · Dallas",
    # LAST_16  (Round of 16)
    537376: "NRG Stadium · Houston",
    537375: "Lincoln Financial Field · Philadelphia",
    537377: "MetLife Stadium · New York/New Jersey",
    537378: "Estadio Azteca · Ciudad de México",
    537379: "AT&T Stadium · Dallas",
    537380: "Lumen Field · Seattle",
    537381: "BC Place · Vancouver",
    537382: "Mercedes-Benz Stadium · Atlanta",
    # QUARTER_FINALS
    537383: "Gillette Stadium · Boston",
    537384: "SoFi Stadium · Los Angeles",
    537385: "Hard Rock Stadium · Miami",
    537386: "GEHA Field at Arrowhead · Kansas City",
    # SEMI_FINALS
    537387: "AT&T Stadium · Dallas",
    537388: "Mercedes-Benz Stadium · Atlanta",
    # THIRD PLACE & FINAL
    537389: "Hard Rock Stadium · Miami",
    537390: "MetLife Stadium · New York/New Jersey",
}


_MX_VENUES = {"Estadio Azteca", "Estadio BBVA", "Estadio Akron"}
_CA_VENUES  = {"BMO Field", "BC Place"}


def get_venue(home: str, away: str) -> str | None:
    return _VENUES.get(f"{home}|{away}")


def get_venue_by_id(match_id: int) -> str | None:
    return _KNOCKOUT_VENUES.get(match_id)


def get_host_country(venue: str) -> str:
    """Devuelve 'Mexico', 'Canada' o 'USA' según la sede del partido."""
    if any(v in venue for v in _MX_VENUES):
        return "Mexico"
    if any(v in venue for v in _CA_VENUES):
        return "Canada"
    return "USA"
