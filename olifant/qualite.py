"""Juger une trace avant de la proposer.

Un parcours n'est bon que si on peut le suivre sans se perdre et qu'il est
agreable a marcher. Ces deux choses se mesurent sur la trace calculee, on n'a
pas besoin d'y aller pour savoir qu'un parcours fait 60 % de bitume ou qu'une
etape a ete accrochee a 400 m du chemin le plus proche.

Chaque controle repond a une facon precise de se faire avoir :

- l'etape lointaine : on a place un point sur une carte satellite, le routeur
  l'a rattache au chemin le plus proche, et le parcours ne passe pas du tout
  la ou on croyait ;
- la boucle qui ne boucle pas : depart et arrivee ne coincident pas, on finit
  a pied le long d'une departementale ;
- le recouvrement : la moitie du parcours est un aller-retour sur le meme
  chemin, ce qui se voit mal sur une carte et tres bien en marchant ;
- le bitume : le routeur a trouve une route, elle est plus directe, il la prend.
  Le seuil depend du terrain : une boucle marquee « ville » s'autorise plus de
  revetement dur qu'une boucle de campagne, parce qu'il n'existe pas de 5 km
  sans trottoir au depart du centre de Metz ;
- la branche : un bout de trace qu'on parcourt a l'aller puis au retour pour
  aller toucher un lieu plante a l'ecart. Le recouvrement ne l'attrape pas --
  300 m aller-retour sur 13 km n'en font que 5 % -- et pourtant ca se voit
  tres bien sur la carte, en deux traits superposes. Le bout refait au depart
  d'une boucle n'en est pas une : c'est le chemin pour rejoindre la boucle,
  qu'on prend forcement dans les deux sens. On l'appelle la liaison, on la
  mesure, on ne la reproche pas.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import accumulate

from .modele import Parcours, Point, Trace, distance_m

# Seuils au-dela desquels on prefere regarder le parcours de plus pres.
ETAPE_LOIN_M = 150         # une etape rattachee plus loin que ca est suspecte
BOUCLE_OUVERTE_M = 250     # ecart tolere entre le depart et l'arrivee
BITUME_MAX = 45.0          # part de revetement dur, en %
# Une boucle urbaine assumee -- theme « ville » -- n'a pas le meme terrain de
# jeu : mesure sur cinquante essais de 5 km au depart de la Nouvelle Ville, le
# revetement dur ne descend jamais sous 24 %, et tourne autour de 45 %. Juger
# ces boucles-la au seuil de la rando reviendrait a signaler tout le lot, donc
# a ne plus rien signaler du tout. Au-dela de 65 %, en revanche, on marche sur
# du trottoir et ca vaut d'etre dit.
BITUME_MAX_VILLE = 65.0
RECOUVREMENT_MAX = 25.0    # part de la trace parcourue deux fois, en %
MAILLE_M = 30              # taille de la maille qui detecte le recouvrement
# Les dix balades courtes ont ete composees en refusant, a l'oeil, toute branche
# de plus de 250 m ; mesuree apres coup, la plus longue fait 216 m.
BRANCHE_MAX_M = 250
REPASSE_M = 20             # deux points de trace plus proches sont le meme lieu
# En deca de cette distance le long de la trace, se retrouver au meme endroit
# n'est pas repasser : c'est la pointe d'un demi-tour, ou un virage serre.
DETOUR_MIN_M = 60


@dataclass
class Branche:
    """Un bout de trace qu'on refait plus loin, souvent en sens inverse."""

    metres: float        # longueur du bout parcouru deux fois
    depuis_m: float      # ou il commence, en metres depuis le depart
    lonlat: tuple[float, float]

    @property
    def km(self) -> float:
        return self.depuis_m / 1000


@dataclass
class Bilan:
    km: float
    montee: float
    chemin: float
    bitume: float
    route: float
    balise: float
    recouvrement: float
    boucle_ouverte_m: float
    etapes_loin: list[tuple[str, float]] = field(default_factory=list)
    liaison_m: float = 0.0
    branches: list[Branche] = field(default_factory=list)
    alertes: list[str] = field(default_factory=list)

    @property
    def bon(self) -> bool:
        return not self.alertes

    def ligne(self, largeur: int = 22) -> str:
        """Une ligne de tableau, pour la sortie en console."""
        return "%-*s %5.1f km  D+%4d m  chemin %3d%%  bitume %3d%%  balise %3d%%  %s" % (
            largeur, self.km and "" or "", self.km, round(self.montee),
            round(self.chemin), round(self.bitume), round(self.balise),
            "ok" if self.bon else "%d alerte(s)" % len(self.alertes),
        )


def juge(parcours: Parcours, trace: Trace, points: dict[str, Point]) -> Bilan:
    ecarts = _ecarts_etapes(parcours, trace, points)
    ouverture = (distance_m(trace.points[0], trace.points[-1])
                 if parcours.boucle and trace.points else 0.0)
    bilan = Bilan(
        km=trace.km,
        montee=trace.montee,
        chemin=trace.part("chemin"),
        bitume=trace.part("bitume"),
        route=trace.part("route"),
        balise=trace.part_balisee,
        recouvrement=recouvrement(trace),
        boucle_ouverte_m=ouverture,
        etapes_loin=[(cle, d) for cle, d in ecarts if d > ETAPE_LOIN_M],
    )
    bilan.liaison_m, bilan.branches = branches(trace, boucle=parcours.boucle)
    for cle, distance in bilan.etapes_loin:
        bilan.alertes.append(
            "l'etape « %s » est a %d m de la trace : le routeur l'a rattachee "
            "ailleurs, deplacez le point sur un chemin" % (points[cle].nom, distance))
    if ouverture > BOUCLE_OUVERTE_M:
        bilan.alertes.append(
            "la boucle ne se referme pas : %d m entre l'arrivee et le depart" % ouverture)
    plafond = bitume_max(parcours)
    if bilan.bitume > plafond:
        bilan.alertes.append(
            "%d %% de revetement dur, au-dessus des %d %% qu'on s'autorise"
            % (round(bilan.bitume), plafond))
    if bilan.recouvrement > RECOUVREMENT_MAX:
        bilan.alertes.append(
            "%d %% du parcours est fait deux fois : c'est un aller-retour deguise"
            % round(bilan.recouvrement))
    for branche in bilan.branches:
        if branche.metres > BRANCHE_MAX_M:
            bilan.alertes.append(
                "une branche de %d m au km %.1f : on la parcourt a l'aller et "
                "au retour" % (branche.metres, branche.km))
    return bilan


def bitume_max(parcours: Parcours) -> float:
    """Le plafond de revetement dur applicable a ce parcours.

    Une boucle de campagne et une boucle de ville ne se jugent pas pareil :
    le bitume qu'on reproche a la premiere est le pave que la seconde vient
    chercher. Le theme « ville » du fichier de reference sert de declarateur.
    """
    return BITUME_MAX_VILLE if "ville" in parcours.themes else BITUME_MAX


def _ecarts_etapes(parcours: Parcours, trace: Trace,
                   points: dict[str, Point]) -> list[tuple[str, float]]:
    """Pour chaque etape, la distance au point le plus proche de la trace.

    Grande valeur = le routeur n'a pas pu approcher le lieu demande.
    """
    ecarts = []
    for cle in dict.fromkeys(parcours.etapes):
        cible = points[cle].lonlat
        ecarts.append((cle, min((distance_m(cible, p) for p in trace.points), default=0.0)))
    return ecarts


def recouvrement(trace: Trace, maille_m: int = MAILLE_M) -> float:
    """Part de la distance passee sur un endroit deja parcouru, en %.

    On pose une grille sur le terrain et on compte la distance des troncons
    dont la case a deja ete visitee plus tot -- en ignorant les cases voisines
    immediates, sinon un simple demi-tour de dix metres compterait.
    """
    if len(trace.points) < 3:
        return 0.0
    lat_moy = sum(p[1] for p in trace.points) / len(trace.points)
    pas_lat = maille_m / 111320
    pas_lon = maille_m / (111320 * max(math.cos(math.radians(lat_moy)), 0.1))
    vues: dict[tuple[int, int], int] = {}
    total = refait = 0.0
    for i, (a, b) in enumerate(zip(trace.points, trace.points[1:])):
        d = distance_m(a, b)
        total += d
        case = (int(a[0] / pas_lon), int(a[1] / pas_lat))
        precedent = vues.get(case)
        if precedent is not None and i - precedent > 10:
            refait += d
        else:
            vues.setdefault(case, i)
    return 100 * refait / total if total else 0.0


def branches(trace: Trace, boucle: bool = True) -> tuple[float, list[Branche]]:
    """La liaison d'une boucle, et les bouts de trace qu'on refait ailleurs.

    Un point est « repris » si la trace repasse a moins de REPASSE_M de lui
    plus loin -- et pas juste apres, ce qui serait la pointe d'un demi-tour.
    Refaire le meme chemin, c'est repasser par les memes noeuds OSM ; la
    tolerance absorbe les chemins doubles et les arrondis du routeur.

    Chaque bout repris n'est compte qu'une fois, a l'aller. Sur une boucle,
    celui qui part du depart est la liaison ; les autres sont des branches.
    """
    pts = trace.points
    if len(pts) < 3:
        return 0.0, []
    cumuls = [0.0, *accumulate(distance_m(a, b) for a, b in zip(pts, pts[1:]))]
    pas_lat = REPASSE_M / 111320
    pas_lon = REPASSE_M / (111320 * max(math.cos(math.radians(pts[0][1])), 0.1))
    case = lambda p: (int(p[0] // pas_lon), int(p[1] // pas_lat))
    grille: dict[tuple[int, int], list[int]] = {}
    for j, p in enumerate(pts):
        grille.setdefault(case(p), []).append(j)

    def repris(i: int) -> bool:
        x, y = case(pts[i])
        return any(j > i and cumuls[j] - cumuls[i] > DETOUR_MIN_M
                   and distance_m(pts[i], pts[j]) < REPASSE_M
                   for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                   for j in grille.get((x + dx, y + dy), ()))

    marques = [repris(i) for i in range(len(pts))]
    liaison, trouvees = 0.0, []
    i = 0
    while i < len(pts) - 1:
        if not marques[i]:
            i += 1
            continue
        fin = i
        while fin + 1 < len(pts) - 1 and marques[fin + 1]:
            fin += 1
        # D'un point repris au dernier : un point isole -- le depart qu'on
        # retrouve a l'arrivee, un carrefour traverse deux fois -- ne pese rien.
        metres = cumuls[fin] - cumuls[i]
        if metres and boucle and i == 0:
            liaison = metres
        elif metres:
            trouvees.append(Branche(metres=metres, depuis_m=cumuls[i],
                                    lonlat=(pts[i][0], pts[i][1])))
        i = fin + 1
    return liaison, trouvees
