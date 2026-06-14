"""
prematch.py — Reporte de pronóstico pre-partido por línea de comandos.

Corre el pipeline completo de prematch_analysis (XI probable, afinidad
extendida, mercado, marcadores) y registra el snapshot en el forecast
ledger. Pensado para correrse el día del partido, lo más cerca posible
del kickoff (el ledger evalúa con el último snapshot pre-kickoff).

Uso:
  cd backend && source venv/bin/activate
  python prematch.py "Canada" "Bosnia-Herzegovina" --date 2026-06-12
  python prematch.py "South Korea" "Mexico" --date 2026-06-18 \
      --stage GROUP_STAGE
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("prematch")
logging.getLogger("httpx").setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    """Define y parsea los argumentos del CLI."""
    parser = argparse.ArgumentParser(
        description="Pronóstico pre-partido WC 2026"
    )
    parser.add_argument("home", help="Selección local (nombre football-data)")
    parser.add_argument("away", help="Selección visitante")
    parser.add_argument(
        "--date",
        required=True,
        help="Fecha del partido YYYY-MM-DD (excluye el partido del historial)",
    )
    parser.add_argument("--stage", default="GROUP_STAGE")
    parser.add_argument("--venue", default=None)
    return parser.parse_args()


def render(report: dict) -> None:
    """Imprime el reporte en formato legible vía logging."""
    home, away = report["home"], report["away"]
    log.info("\n%s vs %s — %s", home, away, report["venue"] or "sede TBD")

    for name in (home, away):
        t = report["teams"][name]
        friendly_pct = t["friendlyShare"]
        warn = (
            "  ⚠ historial 100% amistosos — XI probable poco fiable"
            if friendly_pct == 1.0
            else ""
        )
        log.info("\n— %s (afinidad extendida %.1f)%s",
                 name, t["extendedAffinity"], warn)
        coverage = t.get("ratingCoverage", {})
        if not coverage.get("rated", True):
            log.info("  ⚠ RATING INCOMPLETO — usa valores por defecto en %s "
                     "(pronóstico poco fiable)",
                     ", ".join(coverage["missingSources"]))
        for m in t["last5"]:
            tag = " [amistoso]" if m["friendly"] else ""
            log.info("    %s  %s vs %s%s",
                     m["date"], m["score"], m["opponent"], tag)
        log.info("  XI probable:")
        for p in t["probableXI"]:
            club = p["club"] or "?? sin mapear"
            log.info("    %-26s %d/5  %s [%s]",
                     p["name"], p["starts"], club, p["league_code"] or "—")

    probs = report["probs"]
    log.info("\nModelo : %s %.1f%% | X %.1f%% | %s %.1f%%",
             home, probs["model"]["homeWin"] * 100,
             probs["model"]["draw"] * 100,
             away, probs["model"]["awayWin"] * 100)
    if probs["market"]:
        mk = report["market"]
        log.info("Mercado: %s %.1f%% | X %.1f%% | %s %.1f%%  (%d casas)",
                 home, probs["market"]["homeWin"] * 100,
                 probs["market"]["draw"] * 100,
                 away, probs["market"]["awayWin"] * 100,
                 mk["bookmakerCount"])
    log.info("FINAL  : %s %.1f%% | X %.1f%% | %s %.1f%%",
             home, probs["blended"]["homeWin"] * 100,
             probs["blended"]["draw"] * 100,
             away, probs["blended"]["awayWin"] * 100)

    sc = report["scorelines"]
    log.info("\nλ %s %.2f | %s %.2f  ·  over 2.5: %.1f%%  ·  ambos anotan: %.1f%%",
             home, sc["lambdas"]["home"], away, sc["lambdas"]["away"],
             sc["over25"] * 100, sc["btts"] * 100)
    log.info("Marcadores: %s",
             " | ".join(f"{s['score']} {s['prob']:.1%}"
                        for s in sc["topScorelines"]))
    log.info("\nSnapshot registrado en el forecast ledger.")


def main() -> None:
    """Punto de entrada del CLI."""
    args = parse_args()
    from app.services.prematch_analysis import run_prematch

    try:
        report = asyncio.run(
            run_prematch(
                args.home,
                args.away,
                match_date=args.date,
                stage=args.stage,
                venue=args.venue,
            )
        )
    except (LookupError, RuntimeError) as err:
        log.error("Error: %s", err)
        sys.exit(1)
    render(report)


if __name__ == "__main__":
    main()
