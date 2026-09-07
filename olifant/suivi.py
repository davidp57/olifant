"""Relire une trace reellement suivie, pour la remettre sur la carte.

Jusqu'ici les GPX rapportes d'une sortie etaient seulement stockes : on les
gardait sans jamais les ouvrir, ce qui evitait d'avoir a se mefier de leur
contenu. Les afficher demande de les lire, donc de les lire prudemment -- un
fichier XML venu de l'exterieur peut contenir de quoi epuiser la machine qui
le parse (entites recursives) ou lui faire ouvrir des fichiers locaux. D'ou
`defusedxml`, qui desactive tout cela.

Le parcours prevu et la trace suivie ne coincident jamais tout a fait : on
coupe un virage, on rate un embranchement, on fait un detour pour une
fontaine. C'est justement ce qu'on veut voir.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from defusedxml import ElementTree

from .modele import distance_m

# Un enregistrement d'une matinee compte des milliers de points, dont la
# plupart ne disent rien de plus que leur voisin. On les allege avant de les
# envoyer au telephone : 8 m d'ecart, c'est deja plus fin que le GPS.
TOLERANCE_M = 8.0

# Un GPS de telephone se trompe de quelques metres a chaque releve, et releve
# une fois par seconde -- soit un point par metre parcouru a pied. Additionner
# ces points bout a bout compte tout le tremblement en plus du chemin : sur un
# essai, 10,3 km de marche donnaient 13,5 km et 660 m de denivele au lieu de
# 61. On ne garde donc un point que s'il est franchement plus loin que le
# precedent, ce qui noie le tremblement sans deformer le trajet.
PAS_MINIMUM_M = 12.0

# Meme raison pour l'altitude, en pire : le barometre derive et le GPS vertical
# est deux a trois fois moins precis que l'horizontal. Le seuil ci-dessous est
# choisi sur mesure, pas au jugement : sur trois boucles connues et un
# enregistrement bruite expres, 3 m donne les deniveles les plus proches de
# la verite (-6 a +13 %) ; 6 m, qui semblait plus prudent, en perdait 15 %.
# C'est le lissage qui fait le travail contre le bruit, pas le seuil.
MARCHE_MINIMUM_M = 3.0
LISSAGE = 5              # nombre de releves moyennes pour degrossir le bruit
NOMMAGE = "{http://www.topografix.com/GPX/1/1}"


class ErreurGpx(ValueError):
    """Le fichier n'est pas un GPX exploitable."""


@dataclass
class TraceSuivie:
    """Ce qu'on a reellement marche : un ou plusieurs troncons enregistres."""

    troncons: list[list[tuple[float, float]]]
    metres: float
    montee: float

    @property
    def km(self) -> float:
        return self.metres / 1000

    @property
    def points(self) -> int:
        return sum(len(t) for t in self.troncons)

    def geojson(self, nom: str = "") -> dict:
        return {
            "type": "Feature",
            "properties": {"nom": nom, "km": round(self.km, 2),
                           "montee": round(self.montee)},
            "geometry": {"type": "MultiLineString",
                         "coordinates": [[[round(x, 6), round(y, 6)] for x, y in t]
                                         for t in self.troncons]},
        }


def lis(contenu: bytes | str) -> TraceSuivie:
    """Extrait les segments d'un GPX, allege la geometrie et mesure.

    On accepte le GPX avec ou sans espace de noms : les applications de
    randonnee ne s'accordent pas la-dessus, et un fichier refuse pour un
    detail de forme serait incomprehensible pour qui l'a rapporte.
    """
    try:
        racine = ElementTree.fromstring(contenu)
    except Exception as e:               # defusedxml leve des types varies
        raise ErreurGpx("XML illisible : %s" % str(e)[:120]) from e

    troncons, montee = [], 0.0
    for segment in _trouve(racine, "trkseg"):
        points, altitudes = [], []
        for point in _trouve(segment, "trkpt"):
            lon, lat = point.get("lon"), point.get("lat")
            if lon is None or lat is None:
                continue
            try:
                couple = (float(lon), float(lat))
            except ValueError:
                continue
            points.append(couple)
            altitudes.append(_altitude(point))
        if len(points) < 2:
            continue
        # L'ordre compte : on debruite d'abord, on mesure ensuite. Mesurer sur
        # les points bruts reviendrait a mesurer le tremblement du GPS.
        gardes = _pas_reguliers(points)
        montee += _montee([altitudes[i] for i in gardes])
        franche = [points[i] for i in gardes]
        if len(franche) < 2:
            continue
        troncons.append(allege(franche))

    if not troncons:
        # Certaines applications exportent la sortie en points de passage
        # plutot qu'en trace : mieux vaut le dire que d'afficher du vide.
        raise ErreurGpx("aucun segment de trace dans ce GPX")

    metres = sum(distance_m(a, b) for t in troncons for a, b in zip(t, t[1:]))
    return TraceSuivie(troncons=troncons, metres=metres, montee=montee)


def _pas_reguliers(points: list[tuple[float, float]],
                   minimum_m: float = PAS_MINIMUM_M) -> list[int]:
    """Les indices des points assez espaces pour dire quelque chose.

    Renvoie des indices et non des points : l'appelant doit pouvoir aligner
    les altitudes sur le meme filtrage.
    """
    gardes = [0]
    for i in range(1, len(points)):
        if distance_m(points[gardes[-1]], points[i]) >= minimum_m:
            gardes.append(i)
    # Le dernier point ferme la trace : on le garde meme s'il est proche.
    if gardes[-1] != len(points) - 1:
        gardes.append(len(points) - 1)
    return gardes


def _trouve(noeud, balise: str) -> list:
    """Les descendants portant cette balise, espace de noms ou pas."""
    trouves = noeud.iter(NOMMAGE + balise)
    resultat = list(trouves)
    return resultat or [n for n in noeud.iter() if _sans_nommage(n.tag) == balise]


def _sans_nommage(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _altitude(point) -> float | None:
    for enfant in point:
        if _sans_nommage(enfant.tag) == "ele":
            try:
                return float((enfant.text or "").strip())
            except ValueError:
                return None
    return None


def _montee(altitudes: list[float | None]) -> float:
    """Denivele positif cumule, une fois le bruit vertical ecarte.

    Deux precautions, et il faut les deux : on moyenne les releves voisins
    pour degrossir la derive du barometre, puis on ne compte une montee que
    si elle depasse franchement la precision de l'appareil. Sans la premiere,
    un terrain plat rend des centaines de metres ; sans la seconde, une pente
    reguliere est comptee deux fois.
    """
    connues = [a for a in altitudes if a is not None]
    if len(connues) < 2:
        return 0.0
    lissees = _moyenne_glissante(connues, LISSAGE)

    cumul, reference = 0.0, lissees[0]
    for altitude in lissees[1:]:
        if altitude - reference >= MARCHE_MINIMUM_M:
            cumul += altitude - reference
            reference = altitude
        elif reference - altitude >= MARCHE_MINIMUM_M:
            reference = altitude
    return cumul


def _moyenne_glissante(valeurs: list[float], fenetre: int) -> list[float]:
    if fenetre < 2 or len(valeurs) < fenetre:
        return list(valeurs)
    demi = fenetre // 2
    lissees = []
    for i in range(len(valeurs)):
        debut, fin = max(0, i - demi), min(len(valeurs), i + demi + 1)
        lissees.append(sum(valeurs[debut:fin]) / (fin - debut))
    return lissees


def allege(points: list[tuple[float, float]],
           tolerance_m: float = TOLERANCE_M) -> list[tuple[float, float]]:
    """Simplifie la ligne en gardant sa forme (Ramer-Douglas-Peucker).

    Ecrit sans recursion : un enregistrement de plusieurs heures peut aligner
    des dizaines de milliers de points, de quoi epuiser la pile.
    """
    if len(points) < 3:
        return list(points)

    garde = [False] * len(points)
    garde[0] = garde[-1] = True
    a_traiter = [(0, len(points) - 1)]
    while a_traiter:
        debut, fin = a_traiter.pop()
        if fin <= debut + 1:
            continue
        pire, ecart = debut, -1.0
        for i in range(debut + 1, fin):
            d = _ecart_a_la_corde(points[i], points[debut], points[fin])
            if d > ecart:
                pire, ecart = i, d
        if ecart > tolerance_m:
            garde[pire] = True
            a_traiter.append((debut, pire))
            a_traiter.append((pire, fin))
    return [p for p, g in zip(points, garde) if g]


def _ecart_a_la_corde(point: tuple[float, float], a: tuple[float, float],
                      b: tuple[float, float]) -> float:
    """Distance en metres du point au segment [a, b]."""
    if a == b:
        return distance_m(point, a)
    # Projection dans un repere metrique local : sur quelques centaines de
    # metres, la terre est bien assez plate pour cela.
    par_degre_lat = 111320.0
    par_degre_lon = 111320.0 * max(math.cos(math.radians(a[1])), 0.1)
    bx = (b[0] - a[0]) * par_degre_lon
    by = (b[1] - a[1]) * par_degre_lat
    px = (point[0] - a[0]) * par_degre_lon
    py = (point[1] - a[1]) * par_degre_lat
    longueur2 = bx * bx + by * by
    t = max(0.0, min(1.0, (px * bx + py * by) / longueur2))
    dx, dy = px - t * bx, py - t * by
    return (dx * dx + dy * dy) ** 0.5
