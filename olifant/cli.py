"""Ligne de commande : calculer les traces et regarder ce qu'elles valent.

    python -m olifant calcule                 # tout, en se servant du cache
    python -m olifant calcule cotes-jussy     # un seul parcours
    python -m olifant calcule --profil trekking --hors-ligne
    python -m olifant reperes                 # ce qu'OSM sait autour des etapes
    python -m olifant tuiles                  # emporte le fond de carte
    python -m olifant candidats pompidou      # ou aller qu'on ne connait pas
    python -m olifant essaie gare 6.2157,49.1316 queuleu gare
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import composition, donnees, export, jalons, qualite, reperes, tuiles
from .modele import Parcours, Point, distance_m
from .routage import PROFIL_DEFAUT, ErreurRoutage, Routeur

RACINE = Path(__file__).resolve().parent.parent
DONNEES = Path(os.environ.get("OLIFANT_PARCOURS", RACINE / "data" / "parcours.yaml"))
# Les carreaux du fond de carte vivent avec ce qui s'ecrit, pas dans l'image :
# 19 Mo de PNG n'ont rien a faire dans un depot de code.
TUILES = Path(os.environ.get("OLIFANT_TUILES",
                             Path(os.environ.get("OLIFANT_DATA", RACINE / "data"))
                             / "tuiles"))
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


def releve_les_reperes(args: argparse.Namespace) -> int:
    """Demande a OpenStreetMap ce qu'il y a autour de chaque etape.

    A part de `calcule` volontairement : Overpass est lent et capricieux, et
    un parcours doit pouvoir se calculer sans lui. Le fichier produit est
    relu par `calcule`, qui s'en passe s'il n'existe pas.
    """
    recueil = donnees.charge(args.fichier)
    sonde = reperes.Sonde(args.cache, hors_ligne=args.hors_ligne)
    voulus = set(args.ids) if args.ids else None
    SORTIE.mkdir(parents=True, exist_ok=True)

    fichier = SORTIE / "reperes.json"
    connus = (json.loads(fichier.read_text(encoding="utf-8"))
              if fichier.exists() else {})
    echecs = []
    for parcours in recueil.parcours:
        if voulus and parcours.id not in voulus:
            continue
        cibles = {c: recueil.points[c] for c in dict.fromkeys(parcours.etapes)}
        try:
            reponse = sonde.interroge(reperes.requete(list(cibles.values())))
        except reperes.ErreurOverpass as e:
            echecs.append((parcours.id, str(e)))
            print("%-22s ECHEC  %s" % (parcours.id, e))
            continue
        par_etape = reperes.range_par_etape(reponse, cibles)
        connus[parcours.id] = par_etape
        total = sum(len(v) for v in par_etape.values())
        print("%-22s %3d reperes sur %d etapes  %s"
              % (parcours.id, total, len(par_etape),
                 ", ".join(sorted({r["genre"] for v in par_etape.values()
                                   for r in v}))))

    fichier.write_text(json.dumps(connus, ensure_ascii=False, indent=1),
                       encoding="utf-8")
    print("\nReleve ecrit dans %s" % fichier)
    if echecs:
        print("Non releves : %s" % ", ".join(pid for pid, _ in echecs))
    return 1 if echecs else 0


def emporte_les_tuiles(args: argparse.Namespace) -> int:
    """Recupere le fond de carte des traces, pour marcher sans reseau.

    A lancer une fois. Les carreaux deja pris ne sont jamais redemandes, ce
    qui garde l'operation supportable pour un service benevole.
    """
    fichier = SORTIE / "traces.geojson"
    if not fichier.exists():
        print("Rien a couvrir : lancez d'abord `python -m olifant calcule`.")
        return 2
    formes = json.loads(fichier.read_text(encoding="utf-8"))["features"]
    voulus = set(args.ids) if args.ids else None

    besoin = set()
    for forme in formes:
        if voulus and forme["properties"]["id"] not in voulus:
            continue
        besoin |= tuiles.couloir([(c[0], c[1]) for c in forme["geometry"]["coordinates"]],
                                 zooms=tuple(args.zooms), marge_m=args.marge)
    if not besoin:
        print("Aucune trace ne correspond.")
        return 2

    print("%d carreaux couvrent %d trace(s), du zoom %d au zoom %d."
          % (len(besoin), len(formes) if not voulus else len(voulus),
             min(args.zooms), max(args.zooms)))
    if args.compte_seulement:
        return 0

    pris, deja, echecs = tuiles.recupere(besoin, TUILES, pause=args.pause,
                                         journal=print)
    poids = sum(f.stat().st_size for f in TUILES.rglob("*.png")) if TUILES.exists() else 0
    print("\n%d pris, %d deja la, %d echec(s). %s contient %.1f Mo."
          % (pris, deja, len(echecs), TUILES, poids / 1024 / 1024))
    for souci in echecs[:5]:
        print("   " + souci)
    return 1 if echecs else 0


def essaie(args: argparse.Namespace) -> int:
    """Mesure une suite d'etapes sans rien ecrire : sert a composer un parcours.

    On tatonne beaucoup pour caler une boucle sur la bonne distance ; autant
    que le tatonnement ne salisse pas le fichier de reference. Une etape est
    une cle du fichier ou un lieu de passage ecrit `lon,lat` -- de quoi essayer
    un lieu trouve par `candidats` avant de lui donner un nom.
    """
    recueil = donnees.charge(args.fichier)
    routeur = Routeur(args.cache, profil=args.profil, hors_ligne=args.hors_ligne)
    points = dict(recueil.points)
    try:
        etapes = [_etape(texte, points) for texte in args.etapes]
    except ValueError as e:
        print("ECHEC %s" % e)
        return 2
    brouillon = Parcours(id="essai", nom="Essai", etapes=etapes)
    try:
        trace = routeur.trace(brouillon, points)
    except ErreurRoutage as e:
        print("ECHEC %s" % e)
        return 1
    bilan = qualite.juge(brouillon, trace, points)
    print("%5.1f km  D+%4d m  chemin %3d%%  bitume %3d%%  route %3d%%  balise %3d%%"
          "  repasse %3d%%"
          % (bilan.km, round(bilan.montee), round(bilan.chemin), round(bilan.bitume),
             round(bilan.route), round(bilan.balise), round(bilan.recouvrement)))

    # Ce qu'on a deja : les traces des parcours du fichier, depuis le cache.
    # Un parcours jamais calcule manque a la comparaison, et on le dit.
    deja = Routeur(args.cache, profil=args.profil, hors_ligne=True)
    autres, absents = [], 0
    for parcours in recueil.parcours:
        # L'essai d'un parcours du fichier ne se compare pas a lui-meme, ni a
        # la version qu'il vient remplacer.
        if parcours.etapes == etapes or parcours.id in args.sauf:
            continue
        try:
            autres.append(deja.trace(parcours, recueil.points))
        except ErreurRoutage:
            absents += 1
    print("neuf %3d%%  (hors des %d parcours connus%s)"
          % (round(composition.part_neuve(trace, autres)), len(autres),
             ", %d jamais calcules" % absents if absents else ""))
    if bilan.liaison_m:
        print("liaison %d m, faite a l'aller et au retour" % bilan.liaison_m)

    print()
    for t in composition.troncons(brouillon, trace, points):
        print("  %-24s -> %-24s %5.1f km  (x%.1f le vol d'oiseau)"
              % (points[t.de].nom[:24], points[t.a].nom[:24], t.metres / 1000,
                 t.detour))
    for branche in bilan.branches:
        if branche.metres >= 100:
            print("  branche de %d m au km %.1f  (%.5f, %.5f)"
                  % (branche.metres, branche.km, *branche.lonlat))
    for alerte in bilan.alertes:
        print("  ! " + alerte)
    return 0


def _etape(texte: str, points: dict[str, Point]) -> str:
    """La cle d'une etape, en inscrivant au passage un lieu ecrit `lon,lat`."""
    if texte in points:
        return texte
    morceaux = texte.split(",")
    try:
        lon, lat = (float(m) for m in morceaux)
    except ValueError:
        raise ValueError("« %s » n'est ni un point du fichier ni un lieu lon,lat"
                         % texte) from None
    points[texte] = Point(cle=texte, nom="%.5f, %.5f" % (lon, lat), lon=lon, lat=lat)
    return texte


def cherche_des_candidats(args: argparse.Namespace) -> int:
    """Les lieux des environs qui valent une etape et qu'aucun point ne touche.

    C'est la premiere question quand on compose : ou aller qu'on ne connait
    pas deja. On la pose a OpenStreetMap, une fois, et la reponse est gardee.
    """
    recueil = donnees.charge(args.fichier)
    points = dict(recueil.points)
    try:
        centre = points[_etape(args.centre, points)].lonlat
    except ValueError as e:
        print("ECHEC %s" % e)
        return 2
    sonde = reperes.Sonde(args.cache, hors_ligne=args.hors_ligne)
    try:
        reponse = sonde.interroge(composition.requete_lieux(centre, args.rayon))
    except reperes.ErreurOverpass as e:
        print("ECHEC %s" % e)
        return 1
    trouves = composition.candidats(reponse, centre, list(recueil.points.values()),
                                    ecart_m=args.ecart)
    for c in trouves:
        print("%4.1f km  %-12s %-44s %.5f,%.5f   (%d m du point connu le plus proche)"
              % (c.eloignement_m / 1000, c.genre, c.nom[:44], c.lon, c.lat,
                 c.plus_proche_m))
    print("\n%d lieux a plus de %d m de tout point connu, dans un rayon de %.1f km."
          % (len(trouves), args.ecart, args.rayon / 1000))
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


def _reperes_connus() -> dict:
    """Le releve OSM s'il a ete fait ; un dictionnaire vide sinon.

    Le catalogue se publie avec ou sans : un parcours reste utilisable meme si
    personne n'a lance `reperes`.
    """
    fichier = SORTIE / "reperes.json"
    if not fichier.exists():
        return {}
    try:
        return json.loads(fichier.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print("Le releve des reperes est illisible, on continue sans.")
        return {}


def _avec_reperes(etapes: list[dict], par_etape: dict) -> list[dict]:
    """Accroche a chaque etape ce qu'OSM a trouve autour d'elle."""
    for etape in etapes:
        trouves = par_etape.get(etape["cle"]) or []
        if trouves:
            etape["reperes"] = trouves
    return etapes


def _catalogue(recueil, resultats) -> dict:
    """Ce que le site consomme : le fichier de reference, mesures comprises.

    Le serveur ne recalcule rien et n'appelle aucun routeur : il sert ce que
    `calcule` a mis ici. Le NAS peut donc etre eteint sans que les traces
    deja emportees cessent d'exister.
    """
    tous_les_reperes = _reperes_connus()
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
            "etapes": _avec_reperes(jalons.etapes_situees(p, t, recueil.points),
                                    tous_les_reperes.get(p.id, {})),
        } for p, t, b in resultats],
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

    r = sous.add_parser("reperes", help="releve ce qu'OSM sait autour des etapes")
    r.add_argument("ids", nargs="*", help="identifiants a traiter, tous par defaut")
    r.add_argument("--hors-ligne", action="store_true",
                   help="n'appelle pas Overpass, se contente du cache")
    r.set_defaults(fonction=releve_les_reperes)

    tu = sous.add_parser("tuiles", help="emporte le fond de carte des traces")
    tu.add_argument("ids", nargs="*", help="identifiants a couvrir, tous par defaut")
    tu.add_argument("--zooms", type=int, nargs="+", default=list(tuiles.ZOOMS),
                    help="niveaux de zoom (defaut : %s)"
                         % " ".join(str(z) for z in tuiles.ZOOMS))
    tu.add_argument("--marge", type=int, default=tuiles.MARGE_M,
                    help="largeur du couloir de part et d'autre, en metres")
    tu.add_argument("--pause", type=float, default=tuiles.PAUSE,
                    help="secondes entre deux carreaux")
    tu.add_argument("--compte-seulement", action="store_true",
                    help="dit combien de carreaux il faudrait, sans rien prendre")
    tu.set_defaults(fonction=emporte_les_tuiles)

    e = sous.add_parser("essaie", help="mesure une suite d'etapes sans rien ecrire")
    e.add_argument("etapes", nargs="+",
                   help="cles de points ou lieux lon,lat, dans l'ordre")
    e.add_argument("--sauf", action="append", default=[], metavar="ID",
                   help="parcours a ne pas compter dans la part neuve")
    e.add_argument("--profil", default=PROFIL_DEFAUT)
    e.add_argument("--hors-ligne", action="store_true")
    e.set_defaults(fonction=essaie)

    ca = sous.add_parser("candidats",
                         help="les lieux des environs qu'aucun point ne touche")
    ca.add_argument("centre", nargs="?", default="gare",
                    help="cle de point ou lieu lon,lat (defaut : gare)")
    ca.add_argument("--rayon", type=int, default=composition.RAYON_M,
                    help="en metres (defaut : %d)" % composition.RAYON_M)
    ca.add_argument("--ecart", type=int, default=composition.ECART_CONNU_M,
                    help="distance minimale a tout point connu, en metres "
                         "(defaut : %d)" % composition.ECART_CONNU_M)
    ca.add_argument("--hors-ligne", action="store_true")
    ca.set_defaults(fonction=cherche_des_candidats)

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
