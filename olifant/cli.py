"""Ligne de commande : calculer les traces et regarder ce qu'elles valent.

    python -m olifant calcule                 # tout, en se servant du cache
    python -m olifant calcule cotes-jussy     # un seul parcours
    python -m olifant calcule --profil trekking --hors-ligne
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import donnees, export, qualite
from .modele import Parcours, distance_m
from .routage import PROFIL_DEFAUT, ErreurRoutage, Routeur

RACINE = Path(__file__).resolve().parent.parent
DONNEES = Path(os.environ.get("OLIFANT_PARCOURS", RACINE / "data" / "parcours.yaml"))
CACHE = Path(os.environ.get("OLIFANT_CACHE", RACINE / "data" / "cache"))
SORTIE = Path(os.environ.get("OLIFANT_SORTIE", RACINE / "data" / "sortie"))


def calcule(args: argparse.Namespace) -> int:
    recueil = donnees.charge(args.fichier)
    routeur = Routeur(args.cache, profil=args.profil, hors_ligne=args.hors_ligne)
    voulus = set(args.ids) if args.ids else None
    SORTIE.mkdir(parents=True, exist_ok=True)

    resultats, echecs = [], []
    for parcours in recueil.parcours:
        if voulus and parcours.id not in voulus:
            continue
        try:
            trace = routeur.trace(parcours, recueil.points)
        except ErreurRoutage as e:
            echecs.append((parcours.id, str(e)))
            print("%-22s ECHEC  %s" % (parcours.id, e))
            continue
        bilan = qualite.juge(parcours, trace, recueil.points)
        resultats.append((parcours, trace, bilan))
        print("%-22s %5.1f km  D+%4d m  chemin %3d%%  bitume %3d%%  balise %3d%%"
              "  repasse %3d%%  %s"
              % (parcours.id, bilan.km, round(bilan.montee), round(bilan.chemin),
                 round(bilan.bitume), round(bilan.balise), round(bilan.recouvrement),
                 "ok" if bilan.bon else "!"))
        (SORTIE / (parcours.id + ".gpx")).write_text(
            export.gpx(parcours, trace, recueil.points), encoding="utf-8")
        (SORTIE / (parcours.id + ".kml")).write_text(
            export.kml(parcours, trace, recueil.points), encoding="utf-8")

    if resultats:
        (SORTIE / "tous.kml").write_text(
            export.kml_complet([(p, t) for p, t, _ in resultats], recueil.points,
                               recueil.meta.get("titre", "Olifant"),
                               recueil.meta.get("accroche", "")),
            encoding="utf-8")
        (SORTIE / "parcours.json").write_text(
            json.dumps(_catalogue(recueil, resultats), ensure_ascii=False, indent=1),
            encoding="utf-8")
        (SORTIE / "traces.geojson").write_text(
            json.dumps({"type": "FeatureCollection",
                        "features": [export.geojson(p, t) for p, t, _ in resultats]},
                       ensure_ascii=False),
            encoding="utf-8")

    alertes = [(p.id, a) for p, _, b in resultats for a in b.alertes]
    if alertes:
        print("\nA regarder de pres :")
        for pid, texte in alertes:
            print("  %-22s %s" % (pid, texte))
    if echecs:
        print("\nNon calcules :")
        for pid, texte in echecs:
            print("  %-22s %s" % (pid, texte))
    print("\n%d parcours ecrits dans %s" % (len(resultats), SORTIE))
    return 1 if echecs else 0


def essaie(args: argparse.Namespace) -> int:
    """Mesure une suite d'etapes sans rien ecrire : sert a composer un parcours.

    On tatonne beaucoup pour caler une boucle sur la bonne distance ; autant
    que le tatonnement ne salisse pas le fichier de reference.
    """
    recueil = donnees.charge(args.fichier)
    routeur = Routeur(args.cache, profil=args.profil, hors_ligne=args.hors_ligne)
    brouillon = Parcours(id="essai", nom="Essai", etapes=args.etapes)
    try:
        trace = routeur.trace(brouillon, recueil.points)
    except ErreurRoutage as e:
        print("ECHEC %s" % e)
        return 1
    bilan = qualite.juge(brouillon, trace, recueil.points)
    print("%5.1f km  D+%4d m  chemin %3d%%  bitume %3d%%  route %3d%%  balise %3d%%"
          "  repasse %3d%%"
          % (bilan.km, round(bilan.montee), round(bilan.chemin), round(bilan.bitume),
             round(bilan.route), round(bilan.balise), round(bilan.recouvrement)))
    for alerte in bilan.alertes:
        print("  ! " + alerte)
    return 0


def accroche(args: argparse.Namespace) -> int:
    """Dit ou le routeur rattache chaque point, et de combien il le deplace.

    Un point pose au milieu d'un bois sur une image satellite peut se retrouver
    accroche a 300 m de la, sur la route qui longe le bois : le parcours ne
    passe alors pas du tout ou on croyait.
    """
    recueil = donnees.charge(args.fichier)
    routeur = Routeur(args.cache, profil=args.profil, hors_ligne=args.hors_ligne)
    cles = args.cles or list(recueil.points)
    for cle in cles:
        point = recueil.points.get(cle)
        if point is None:
            print("%-18s inconnu" % cle)
            continue
        try:
            forme = routeur.geojson([point.lonlat, point.lonlat])
            lon, lat = forme["features"][0]["geometry"]["coordinates"][0][:2]
        except (ErreurRoutage, IndexError, KeyError) as e:
            print("%-18s pas de chemin accessible (%s)" % (cle, e))
            continue
        ecart = distance_m(point.lonlat, (lon, lat))
        marque = "  <- a recaler" if ecart > qualite.ETAPE_LOIN_M else ""
        print("%-18s %3d m du chemin le plus proche   lon: %.6f  lat: %.6f%s"
              % (cle, round(ecart), lon, lat, marque))
    return 0


def _catalogue(recueil, resultats) -> dict:
    """Ce que le site consomme : le fichier de reference, mesures comprises.

    Le serveur ne recalcule rien et n'appelle aucun routeur : il sert ce que
    `calcule` a mis ici. Le NAS peut donc etre eteint sans que les traces
    deja emportees cessent d'exister.
    """
    return {
        "titre": recueil.meta.get("titre", "Olifant"),
        "accroche": recueil.meta.get("accroche", ""),
        "parcours": [{
            "id": p.id,
            "nom": p.nom,
            "resume": p.resume,
            "acces": p.acces,
            "parking": p.parking,
            "themes": p.themes,
            "couleur": "#" + p.couleur,
            "km": round(b.km, 1),
            "montee": round(b.montee),
            "chemin": round(b.chemin),
            "bitume": round(b.bitume),
            "route": round(b.route),
            "balise": round(b.balise),
            "depart": recueil.points[p.etapes[0]].nom,
            "etapes": [{"nom": recueil.points[c].nom, "note": recueil.points[c].note,
                        "lon": recueil.points[c].lon, "lat": recueil.points[c].lat,
                        "depart": c == p.etapes[0]}
                       for c in dict.fromkeys(p.etapes)],
        } for p, _, b in resultats],
    }


def principal(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="olifant", description=__doc__)
    ap.add_argument("--fichier", type=Path, default=DONNEES)
    ap.add_argument("--cache", type=Path, default=CACHE)
    sous = ap.add_subparsers(dest="commande", required=True)

    c = sous.add_parser("calcule", help="calcule les traces et les exports")
    c.add_argument("ids", nargs="*", help="identifiants a traiter, tous par defaut")
    c.add_argument("--profil", default=PROFIL_DEFAUT,
                   help="profil BRouter (defaut : %s)" % PROFIL_DEFAUT)
    c.add_argument("--hors-ligne", action="store_true",
                   help="n'appelle pas le reseau, se contente du cache")
    c.set_defaults(fonction=calcule)

    e = sous.add_parser("essaie", help="mesure une suite d'etapes sans rien ecrire")
    e.add_argument("etapes", nargs="+", help="cles de points, dans l'ordre")
    e.add_argument("--profil", default=PROFIL_DEFAUT)
    e.add_argument("--hors-ligne", action="store_true")
    e.set_defaults(fonction=essaie)

    a = sous.add_parser("accroche", help="ou le routeur rattache les points")
    a.add_argument("cles", nargs="*", help="points a verifier, tous par defaut")
    a.add_argument("--profil", default=PROFIL_DEFAUT)
    a.add_argument("--hors-ligne", action="store_true")
    a.set_defaults(fonction=accroche)

    args = ap.parse_args(argv)
    try:
        return args.fonction(args)
    except (ValueError, OSError) as e:
        print("Erreur : %s" % e, file=sys.stderr)
        return 2
