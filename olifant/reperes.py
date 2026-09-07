"""Ce qu'il y a a voir et a faire autour d'une etape, releve dans OpenStreetMap.

On ne saisit pas ces choses a la main. Personne ne tiendra a jour, pour dix
boucles et cinquante etapes, la liste des fontaines et des bancs -- et OSM la
tient deja. Ce module va donc la chercher et la range par etape.

Comme pour le routage : un appel reseau par parcours, garde sur disque, et une
commande a part. `calcule` ne depend pas d'Overpass ; il lit ce fichier s'il
existe et s'en passe sinon. Le serveur, lui, ne fait jamais d'appel.

Overpass est un service public qui ploie sous la charge : il repond 429 ou 504
des qu'on insiste. On interroge donc d'abord le miroir de kumi.systems, on
attend entre deux appels, et on double l'attente a chaque refus.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .modele import Point, distance_m

MIROIRS = ("https://overpass.kumi.systems/api/interpreter",
           "https://overpass-api.de/api/interpreter")
ENTETE = {"User-Agent": "olifant/1.0 (randonnee, usage personnel)"}
RAYON_M = 400        # au-dela, le detour ne vaut plus la peine a pied
# Un releve brut donne une vingtaine de trouvailles par etape en ville : plus
# personne ne lit. On en garde une poignee, en s'assurant qu'aucun genre ne
# disparait -- perdre la seule fontaine parce que six cafes sont plus proches
# serait exactement le contraire du service rendu.
PAR_ETAPE_MAX = 8
# Deux entrees OSM du meme nom a moins de cela sont le meme objet decrit deux
# fois (un noeud et son contour), pas deux objets : le chateau de Hombourg
# s'affichait « x2 ». Au-dela, ce sont bien deux choses distinctes.
MEME_OBJET_M = 120.0

# Ce qui porte le bon tag sans etre ce qu'on cherche. `amenity=shelter` couvre
# aussi bien la cabane de chasse que l'abribus : le parvis de la gare de Metz
# annoncait « Abri x17 ».
DISQUALIFIANT = {
    "shelter_type": {"public_transport"},
    "bus": {"yes"},
    "highway": {"bus_stop"},
}
PAUSE = 3.0          # secondes entre deux appels, par politesse
REESSAIS = 3
ATTENTE = 25.0

# Ce qu'on retient, et sous quel nom on le presente. L'ordre compte : c'est
# celui dans lequel les reperes d'une etape sont affiches, du plus utile en
# marchant au plus anecdotique.
GENRES = (
    ("eau", "de l'eau", (
        ("amenity", "drinking_water"),
        ("man_made", "water_tap"),
        ("amenity", "water_point"),
    )),
    ("vue", "un point de vue", (
        ("tourism", "viewpoint"),
        ("natural", "peak"),
        ("man_made", "tower"),
    )),
    ("halte", "de quoi s'asseoir", (
        ("tourism", "picnic_site"),
        ("amenity", "shelter"),
        ("leisure", "firepit"),
    )),
    ("ravitaillement", "de quoi manger ou boire", (
        ("amenity", "cafe"), ("amenity", "restaurant"), ("amenity", "pub"),
        ("amenity", "bar"), ("shop", "bakery"), ("shop", "convenience"),
    )),
    ("patrimoine", "a voir", (
        ("historic", "castle"), ("historic", "ruins"), ("historic", "fort"),
        ("historic", "monument"), ("historic", "memorial"),
        ("historic", "archaeological_site"), ("historic", "wayside_cross"),
        ("historic", "wayside_shrine"), ("tourism", "artwork"),
    )),
    ("nature", "curiosite naturelle", (
        ("natural", "spring"), ("natural", "cave_entrance"),
        ("natural", "cliff"),
    )),
    ("commodite", "commodite", (
        ("amenity", "toilets"),
    )),
)

# Deux categories ont ete retirees apres mesure, pas par gout : `natural=tree`
# et `amenity=bench` ramenaient a elles seules jusqu'a 589 arbres et 401 bancs
# pour un seul parcours -- l'essentiel du volume, de quoi faire ployer Overpass
# et rendre la liste d'une etape illisible. Un arbre cartographie dans OSM est
# le plus souvent un arbre d'alignement de rue, pas un repere de randonnee, et
# quatre cents bancs n'informent personne.


class ErreurOverpass(RuntimeError):
    """Overpass n'a pas repondu, ou a repondu autre chose que du JSON."""


@dataclass
class Repere:
    genre: str
    nom: str
    lon: float
    lat: float
    etape: str = ""
    distance_m: float = 0.0
    combien: int = 1        # nombre d'homonymes autour de la meme etape

    @property
    def lonlat(self) -> tuple[float, float]:
        return (self.lon, self.lat)

    def publiable(self) -> dict:
        publie = {"genre": self.genre, "nom": self.nom, "lon": round(self.lon, 6),
                  "lat": round(self.lat, 6), "distance_m": round(self.distance_m)}
        if self.combien > 1:
            publie["combien"] = self.combien
        return publie


# ------------------------------------------------------------------ requete

def requete(cibles: list[Point], rayon_m: int = RAYON_M) -> str:
    """La requete Overpass qui ramene tout ce qui nous interesse d'un coup.

    Une seule requete pour toutes les etapes d'un parcours : Overpass sait
    faire l'union, et cela lui epargne autant d'interrogations qu'on a
    d'etapes.
    """
    morceaux = []
    for cle, _, paires in GENRES:
        # Un seul filtre par cle OSM plutot qu'un par valeur : la requete est
        # plus courte et Overpass la traite plus vite.
        par_cle: dict[str, list[str]] = {}
        for osm_cle, valeur in paires:
            par_cle.setdefault(osm_cle, []).append(valeur)
        for osm_cle, valeurs in par_cle.items():
            motif = "^(%s)$" % "|".join(valeurs)
            for point in cibles:
                morceaux.append('nwr(around:%d,%.6f,%.6f)["%s"~"%s"];'
                                % (rayon_m, point.lat, point.lon, osm_cle, motif))
    return "[out:json][timeout:120];\n(\n%s\n);\nout center tags;" % "\n".join(morceaux)


def _empreinte(corps: str) -> str:
    return hashlib.sha1(corps.encode()).hexdigest()[:16]


class Sonde:
    """Interroge Overpass, en gardant chaque reponse sur disque."""

    def __init__(self, cache: Path, hors_ligne: bool = False):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.hors_ligne = hors_ligne
        self._dernier_appel = 0.0

    def interroge(self, corps: str) -> dict:
        fichier = self.cache / ("overpass-%s.json" % _empreinte(corps))
        if fichier.exists():
            return json.loads(fichier.read_text(encoding="utf-8"))
        if self.hors_ligne:
            raise ErreurOverpass("rien en cache et mode hors ligne")
        donnees = self._appelle(corps)
        fichier.write_text(json.dumps(donnees), encoding="utf-8")
        return donnees

    def _appelle(self, corps: str) -> dict:
        attente, dernier_souci = ATTENTE, "aucun essai"
        for essai in range(REESSAIS):
            for miroir in MIROIRS:
                pause = PAUSE - (time.monotonic() - self._dernier_appel)
                if pause > 0:
                    time.sleep(pause)
                try:
                    return self._une_fois(miroir, corps)
                except ErreurOverpass as e:
                    dernier_souci = str(e)
            if essai < REESSAIS - 1:
                print("   Overpass sature, reprise dans %d s" % attente)
                time.sleep(attente)
                attente *= 2
        raise ErreurOverpass(dernier_souci)

    def _une_fois(self, miroir: str, corps: str) -> dict:
        donnees = urllib.parse.urlencode({"data": corps}).encode()
        demande = urllib.request.Request(miroir, data=donnees, headers=ENTETE)
        try:
            with urllib.request.urlopen(demande, timeout=180) as reponse:
                brut = reponse.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            raise ErreurOverpass("%s a refuse (%s)" % (miroir, e.code)) from e
        except OSError as e:
            raise ErreurOverpass("%s injoignable : %s" % (miroir, e)) from e
        finally:
            self._dernier_appel = time.monotonic()
        try:
            return json.loads(brut)
        except json.JSONDecodeError:
            raise ErreurOverpass("%s : reponse illisible (%s)"
                                 % (miroir, brut.strip()[:120])) from None


# ------------------------------------------------- lecture de la reponse

def _genre_de(tags: dict[str, str]) -> tuple[str, str] | None:
    for cle, valeurs in DISQUALIFIANT.items():
        if tags.get(cle) in valeurs:
            return None
    for cle, libelle, paires in GENRES:
        for osm_cle, valeur in paires:
            if tags.get(osm_cle) == valeur:
                return cle, libelle
    return None


def _nom_de(tags: dict[str, str], libelle: str) -> str:
    """Le nom OSM s'il existe, sinon ce que la chose est.

    Une fontaine n'a presque jamais de nom, et « de l'eau » vaut mieux que
    « sans nom » quand on cherche a boire.
    """
    nom = tags.get("name") or tags.get("inscription") or ""
    if nom:
        return nom
    precisions = {
        "drinking_water": "Point d'eau", "spring": "Source",
        "viewpoint": "Point de vue", "peak": "Sommet", "tower": "Tour",
        "picnic_site": "Aire de pique-nique", "shelter": "Abri",
        "bench": "Banc", "toilets": "Toilettes", "ruins": "Ruines",
        "wayside_cross": "Croix de chemin", "wayside_shrine": "Chapelle",
        "cave_entrance": "Entree de grotte", "cliff": "Falaise",
        "fort": "Fortification", "castle": "Chateau", "monument": "Monument",
        "memorial": "Memorial", "archaeological_site": "Site archeologique",
        "cafe": "Cafe", "restaurant": "Restaurant", "bakery": "Boulangerie",
        "convenience": "Epicerie", "pub": "Pub", "bar": "Bar",
        "artwork": "Oeuvre", "tree": "Arbre remarquable",
    }
    for valeur in tags.values():
        if valeur in precisions:
            return precisions[valeur]
    return libelle.capitalize()


def range_par_etape(reponse: dict, cibles: dict[str, Point],
                    rayon_m: int = RAYON_M) -> dict[str, list[dict]]:
    """Attribue chaque repere a l'etape dont il est le plus proche.

    Overpass rend une liste plate : c'est ici qu'on retrouve a quelle etape
    chaque trouvaille appartient. Un repere plus loin que le rayon de toutes
    les etapes est ecarte -- il vient du voisinage d'une autre boucle.
    """
    par_etape: dict[str, list[Repere]] = {cle: [] for cle in cibles}
    vus: set[tuple[str, int, int]] = set()

    for element in reponse.get("elements", []):
        tags = element.get("tags") or {}
        genre = _genre_de(tags)
        if genre is None:
            continue
        centre = element.get("center") or element
        lon, lat = centre.get("lon"), centre.get("lat")
        if lon is None or lat is None:
            continue

        proche, ecart = None, float("inf")
        for cle, point in cibles.items():
            d = distance_m((lon, lat), point.lonlat)
            if d < ecart:
                proche, ecart = cle, d
        if proche is None or ecart > rayon_m:
            continue

        par_etape[proche].append(Repere(genre=genre[0], nom=_nom_de(tags, genre[1]),
                                        lon=lon, lat=lat, etape=proche,
                                        distance_m=ecart))

    ordre = [cle for cle, _, _ in GENRES]
    return {
        cle: [r.publiable() for r in _les_plus_parlants(_sans_doublons(liste), ordre)]
        for cle, liste in par_etape.items() if liste
    }


def _sans_doublons(liste: list[Repere]) -> list[Repere]:
    """Un seul repere par nom autour d'une etape, le plus proche.

    Deux cas, et le meme remede. OSM decrit souvent une chose deux fois -- le
    chateau de Hombourg apparaissait en noeud et en contour, a une trentaine
    de metres l'un de l'autre, donc deux fois dans la liste. Et une etape
    urbaine compte quatre abris et quatre fontaines sans nom : « Abri, Abri,
    Abri, Abri » n'apprend rien de plus que « Abri ×4 », qui tient sur une
    ligne et dit la meme chose.
    """
    par_nom: dict[tuple[str, str], Repere] = {}
    for repere in sorted(liste, key=lambda r: r.distance_m):
        clef = (repere.genre, repere.nom.casefold())
        garde = par_nom.get(clef)
        if garde is None:
            par_nom[clef] = repere
        elif distance_m(garde.lonlat, repere.lonlat) > MEME_OBJET_M:
            # Assez loin pour etre un deuxieme abri, pas le meme decrit deux fois.
            garde.combien += 1
    return list(par_nom.values())


def _les_plus_parlants(liste: list[Repere], ordre: list[str],
                       maximum: int = PAR_ETAPE_MAX) -> list[Repere]:
    """Trie par utilite puis par proximite, en gardant un de chaque genre.

    Deux passes : d'abord le plus proche de chaque genre present, ce qui
    garantit qu'on voit la fontaine meme entouree de cafes ; ensuite les
    suivants par proximite, jusqu'a remplir la place.
    """
    par_utilite = lambda r: (ordre.index(r.genre), r.distance_m)
    triee = sorted(liste, key=par_utilite)

    gardes, vus = [], set()
    for repere in triee:
        if repere.genre not in vus:
            vus.add(repere.genre)
            gardes.append(repere)
    for repere in sorted(triee, key=lambda r: r.distance_m):
        if len(gardes) >= maximum:
            break
        if repere not in gardes:
            gardes.append(repere)
    return sorted(gardes, key=par_utilite)
