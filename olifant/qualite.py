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
  sans trottoir au depart du centre de Metz.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

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
