"""Les objets du domaine : un point, un parcours, une trace calculee.

Le fichier de reference est data/parcours.yaml. Il ne contient que ce qu'un
humain ecrit : des points nommes et l'ordre dans lequel on les enchaine.
Tout le reste -- la trace reelle, la distance, le denivele, la part de chemin --
est calcule et n'est jamais saisi a la main.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Point:
    """Un lieu qu'on nomme : depart, etape, point de vue, parking."""

    cle: str
    nom: str
    lon: float
    lat: float
    note: str = ""

    @property
    def lonlat(self) -> tuple[float, float]:
        return (self.lon, self.lat)


@dataclass
class Parcours:
    """Une boucle : une suite de points a enchainer, plus ce qui la decrit."""

    id: str
    nom: str
    etapes: list[str]
    acces: str = "a pied"          # "a pied" ou "voiture"
    parking: str = ""              # pertinent si acces == "voiture"
    resume: str = ""
    themes: list[str] = field(default_factory=list)
    couleur: str = "3388ff"

    @property
    def boucle(self) -> bool:
        return len(self.etapes) > 2 and self.etapes[0] == self.etapes[-1]


@dataclass
class Segment:
    """Un troncon homogene de la trace, tel que le routeur le decrit.

    C'est la brique qui permet de juger un parcours : chaque segment porte
    les tags OpenStreetMap du chemin emprunte, donc on sait sur quoi on marche.
    """

    metres: float
    tags: dict[str, str]

    @property
    def revetement(self) -> str:
        """Classe le troncon en une des quatre familles qui nous interessent."""
        voie = self.tags.get("highway", "")
        surface = self.tags.get("surface", "")
        if voie in ("path", "track", "bridleway"):
            return "chemin"
        if voie in ("footway", "pedestrian", "steps"):
            # Un trottoir goudronne n'est pas un chemin, une allee de parc si.
            return "bitume" if surface in DUR else "chemin"
        if voie in ("residential", "living_street", "service", "unclassified",
                    "tertiary", "secondary", "primary", "trunk", "busway"):
            return "route"
        return "bitume" if surface in DUR else "chemin"

    @property
    def balise(self) -> bool:
        """Vrai si le chemin porte un itineraire de randonnee balise."""
        return any(c.startswith("route_hiking") for c in self.tags)


DUR = {"asphalt", "paved", "concrete", "concrete:plates", "paving_stones",
       "sett", "cobblestone", "metal", "wood"}


@dataclass
class Trace:
    """Le resultat du calcul : la geometrie reelle et de quoi la juger."""

    parcours_id: str
    profil: str
    points: list[tuple[float, float, float]]   # lon, lat, altitude
    segments: list[Segment]
    montee: float = 0.0                        # denivele positif, en metres

    @property
    def metres(self) -> float:
        return sum(s.metres for s in self.segments)

    @property
    def km(self) -> float:
        return self.metres / 1000

    def part(self, famille: str) -> float:
        """Part de la distance passee sur une famille de revetement, en %."""
        if not self.metres:
            return 0.0
        cumul = sum(s.metres for s in self.segments if s.revetement == famille)
        return 100 * cumul / self.metres

    @property
    def part_balisee(self) -> float:
        if not self.metres:
            return 0.0
        return 100 * sum(s.metres for s in self.segments if s.balise) / self.metres


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance en metres entre deux (lon, lat), formule de haversine."""
    (lon1, lat1), (lon2, lat2) = a[:2], b[:2]
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return 6371000 * 2 * math.asin(math.sqrt(h))
