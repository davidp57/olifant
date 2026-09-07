"""Situer chaque etape le long de la trace : a quel kilometre on y arrive.

Sans ce calcul, une liste d'etapes ne dit rien d'utile quand on marche. On sait
qu'on passera par le fort de Queuleu, pas si c'est dans dix minutes ou dans
deux heures. Le routeur, lui, ne renvoie qu'une suite de points : c'est a nous
de retrouver ou chaque etape tombe dessus.

Le calcul se fait a la compilation, jamais dans le navigateur : le chiffre
voyage dans le catalogue, et le telephone n'a rien a recalculer -- ni au bord
du reseau, ni au milieu d'un bois.

Une subtilite : sur une boucle, le depart et l'arrivee sont le meme lieu, et
certains parcours repassent par un endroit deja vu. Chercher betement le point
de trace le plus proche donnerait donc a la derniere etape le kilometre de la
premiere. On avance donc le long de la trace en meme temps qu'on avance dans
la liste des etapes : chaque etape est cherchee apres celle qui la precede.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import accumulate

from .modele import Parcours, Point, Trace, distance_m


@dataclass
class Jalon:
    """Une etape, replacee sur la trace."""

    cle: str
    metres: float        # distance parcourue depuis le depart pour y arriver
    ecart_m: float       # de combien l'etape est a cote de la trace
    indice: int          # position dans la liste des points de la trace

    @property
    def km(self) -> float:
        return self.metres / 1000


def jalonne(parcours: Parcours, trace: Trace,
            points: dict[str, Point]) -> list[Jalon]:
    """Le kilometrage de chaque etape, dans l'ordre ou on les traverse.

    Renvoie un jalon par element de `parcours.etapes` -- donc deux pour le
    point de depart d'une boucle, l'un a 0 et l'autre a la distance totale.
    """
    if len(trace.points) < 2:
        return []

    # Distance cumulee le long de la trace, point par point.
    ecarts = [distance_m(a, b) for a, b in zip(trace.points, trace.points[1:])]
    cumuls = [0.0, *accumulate(ecarts)]

    jalons: list[Jalon] = []
    depuis = 0
    for rang, cle in enumerate(parcours.etapes):
        cible = points[cle].lonlat
        # La derniere etape d'une boucle est le point de depart : on la cherche
        # dans la fin de la trace, sinon elle retomberait au kilometre zero.
        debut = depuis if rang else 0
        indice, ecart = _plus_proche(trace.points, cible, debut)
        jalons.append(Jalon(cle=cle, metres=cumuls[indice], ecart_m=ecart,
                            indice=indice))
        # On ne recule jamais : l'etape suivante est forcement plus loin.
        depuis = indice
    return jalons


def _plus_proche(points: list[tuple[float, float, float]],
                 cible: tuple[float, float], debut: int) -> tuple[int, float]:
    """Indice du point de trace le plus proche de la cible, a partir de `debut`."""
    meilleur, distance = debut, distance_m(cible, points[debut])
    for i in range(debut + 1, len(points)):
        d = distance_m(cible, points[i])
        if d < distance:
            meilleur, distance = i, d
    return meilleur, distance


def etapes_situees(parcours: Parcours, trace: Trace,
                   points: dict[str, Point]) -> list[dict]:
    """Les etapes telles que le catalogue les publie, kilometrage compris.

    Le depart d'une boucle n'est ecrit qu'une fois, au kilometre zero ; ce
    qu'il faut savoir de son retour, c'est la distance totale, et elle est
    deja donnee par le parcours.
    """
    jalons = jalonne(parcours, trace, points)
    total = cumul_total(jalons)
    vues, sorties = set(), []
    for rang, jalon in enumerate(jalons):
        if jalon.cle in vues:
            continue
        vues.add(jalon.cle)
        point = points[jalon.cle]
        sorties.append({
            "cle": jalon.cle,
            "nom": point.nom,
            "note": point.note,
            "lon": point.lon,
            "lat": point.lat,
            "depart": rang == 0,
            "km": round(jalon.km, 1),
            "part": round(100 * jalon.metres / total) if total else 0,
        })
    return sorties


def cumul_total(jalons: list[Jalon]) -> float:
    return max((j.metres for j in jalons), default=0.0)
