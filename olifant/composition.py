"""Composer un parcours : trouver ou aller, et savoir ce que vaut un essai.

Le routeur relie des etapes ; il ne dit pas lesquelles choisir. Ce module
outille le tatonnement qui precede l'ecriture d'un parcours dans le fichier de
reference, avec trois questions qu'on se pose a chaque essai :

- ou aller : les parcs, bois, forts et points de vue des environs qu'aucun
  parcours ne touche encore, releves dans OpenStreetMap ;
- par ou ca passe : la longueur de chaque troncon, comparee au vol d'oiseau.
  Un troncon deux fois plus long que la ligne droite bute sur un obstacle --
  une riviere, un faisceau ferroviaire, une rocade -- et c'est la qu'il faut
  deplacer une etape ;
- est-ce nouveau : la part de la trace qui ne passe sur aucun autre parcours.
  Sans elle, on recompose sans le voir une boucle qu'on a deja.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .jalons import jalonne
from .modele import Parcours, Point, Trace, distance_m

# Ce qui vaut le detour quand on cherche ou aller, a la difference des reperes
# qui disent ce qu'on trouve sur place. Une fontaine ne justifie pas une boucle,
# un bois si.
LIEUX = (
    ("leisure", "park|nature_reserve|garden"),
    ("natural", "wood|water|wetland"),
    ("landuse", "forest"),
    ("historic", "fort|castle|ruins"),
)
RAYON_M = 5000          # une boucle de 9 a 14 km s'eloigne rarement plus
ECART_CONNU_M = 500     # en deca, le lieu est deja touche par un point connu
MARGE_NEUF_M = 40       # a moins de ca d'un autre parcours, on est dessus


@dataclass
class Candidat:
    genre: str
    nom: str
    lon: float
    lat: float
    eloignement_m: float    # depuis le centre de la recherche
    plus_proche_m: float    # du point connu le plus proche


def requete_lieux(centre: tuple[float, float], rayon_m: int = RAYON_M) -> str:
    """Les lieux qui valent une etape autour d'un centre, en une requete.

    Seuls les lieux nommes sont retenus : un bois sans nom est le plus souvent
    une haie epaisse. Les points de vue font exception, ils n'en ont presque
    jamais.
    """
    lon, lat = centre
    morceaux = ['nwr(around:%d,%.6f,%.6f)["%s"~"^(%s)$"]["name"];'
                % (rayon_m, lat, lon, cle, valeurs) for cle, valeurs in LIEUX]
    morceaux.append('nwr(around:%d,%.6f,%.6f)["tourism"="viewpoint"];'
                    % (rayon_m, lat, lon))
    return "[out:json][timeout:120];\n(\n%s\n);\nout center tags;" % "\n".join(morceaux)


def candidats(reponse: dict, centre: tuple[float, float], connus: list[Point],
              ecart_m: float = ECART_CONNU_M) -> list[Candidat]:
    """Les lieux de la reponse qu'aucun point connu ne touche, du plus proche.

    Un meme bois revient souvent en plusieurs morceaux homonymes : on n'en
    garde qu'un par nom et par genre, le plus proche du centre.
    """
    vus: dict[tuple[str, str], Candidat] = {}
    for element in reponse.get("elements", []):
        tags = element.get("tags") or {}
        position = element.get("center") or element
        lon, lat = position.get("lon"), position.get("lat")
        if lon is None or lat is None:
            continue
        genre = next((tags[cle] for cle, _ in LIEUX if cle in tags),
                     tags.get("tourism", ""))
        nom = tags.get("name") or "Point de vue"
        proche = min((distance_m((lon, lat), p.lonlat) for p in connus),
                     default=math.inf)
        if proche < ecart_m:
            continue
        trouve = Candidat(genre=genre, nom=nom, lon=lon, lat=lat,
                          eloignement_m=distance_m(centre, (lon, lat)),
                          plus_proche_m=proche)
        clef = (genre, nom.casefold())
        if clef not in vus or trouve.eloignement_m < vus[clef].eloignement_m:
            vus[clef] = trouve
    return sorted(vus.values(), key=lambda c: c.eloignement_m)


@dataclass
class Troncon:
    de: str
    a: str
    metres: float
    vol_m: float            # a vol d'oiseau entre les deux etapes

    @property
    def detour(self) -> float:
        """Combien de fois plus long que la ligne droite."""
        return self.metres / self.vol_m if self.vol_m else 1.0


def troncons(parcours: Parcours, trace: Trace,
             points: dict[str, Point]) -> list[Troncon]:
    """La longueur de chaque troncon, d'une etape a la suivante."""
    jalons = jalonne(parcours, trace, points)
    return [Troncon(de=a.cle, a=b.cle, metres=b.metres - a.metres,
                    vol_m=distance_m(points[a.cle].lonlat, points[b.cle].lonlat))
            for a, b in zip(jalons, jalons[1:])]


def part_neuve(trace: Trace, autres: list[Trace],
               marge_m: float = MARGE_NEUF_M) -> float:
    """Part de la trace, en %, a plus de `marge_m` de toutes les autres.

    On pose une grille de pas `marge_m` sur les autres traces, en marquant
    chaque case et ses huit voisines : tout point a moins de `marge_m` d'un
    autre parcours tombe dans une case marquee, et certains jusqu'a trois fois
    plus loin aussi. Le chiffre est donc prudent : ce qui est compte comme neuf
    l'est vraiment.
    """
    if len(trace.points) < 2:
        return 0.0
    pas_lat = marge_m / 111320
    pas_lon = marge_m / (111320 * max(math.cos(math.radians(trace.points[0][1])), 0.1))
    case = lambda p: (int(p[0] // pas_lon), int(p[1] // pas_lat))
    marquees = set()
    for autre in autres:
        for p in autre.points:
            x, y = case(p)
            marquees.update((x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
    total = neuf = 0.0
    for a, b in zip(trace.points, trace.points[1:]):
        d = distance_m(a, b)
        total += d
        if case(a) not in marquees:
            neuf += d
    return 100 * neuf / total if total else 0.0
