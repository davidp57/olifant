"""Emporter le fond de carte, pour que la carte existe encore sans reseau.

En foret de Hombourg-Budange il n'y a pas de reseau. Sans fond de carte, la
page affiche la trace et la position sur du blanc : on navigue en fil de fer.
C'est utilisable, mais savoir qu'on longe une clairiere ou qu'un chemin part
sur la droite change tout.

Le principe du projet s'applique ici comme ailleurs : ce qui coute du reseau
se fait avant, en ligne de commande, une fois. La commande `tuiles` recupere
les carreaux qui couvrent les traces et les range dans un dossier ; le
serveur les sert ensuite comme des fichiers, sans jamais rien demander a
personne.

Une precaution qui n'est pas technique : les serveurs de tuiles
d'OpenStreetMap sont tenus par des benevoles et leur reglement demande de ne
pas les aspirer. On ne prend donc que le couloir des traces, on s'arrete a un
zoom qui suffit a marcher, on annonce qui on est, et on attend entre deux
carreaux. Le cache etant permanent, la depense n'est faite qu'une fois.
"""

from __future__ import annotations

import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# Le couloir emporte : au-dela, on ne regarde pas la carte en marchant.
MARGE_M = 500
# z13 pour se situer dans la vallee, z16 pour distinguer deux chemins qui
# divergent. Au-dela le nombre de carreaux quadruple pour peu de gain a pied.
ZOOMS = (13, 14, 15, 16)


@dataclass(frozen=True)
class Carreau:
    z: int
    x: int
    y: int

    def chemin(self) -> str:
        return "%d/%d/%d.png" % (self.z, self.x, self.y)


def carreau_de(lon: float, lat: float, z: int) -> tuple[int, int]:
    """Le carreau qui contient ce point, en numerotation Web Mercator."""
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(max(-85.05, min(85.05, lat)))
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def _degres_par_metre(lat: float) -> tuple[float, float]:
    return 1 / 111320.0, 1 / (111320.0 * max(math.cos(math.radians(lat)), 0.1))


def couloir(points: list[tuple[float, float]], zooms: tuple[int, ...] = ZOOMS,
            marge_m: int = MARGE_M) -> set[Carreau]:
    """Les carreaux qui couvrent la trace, elargie de `marge_m` de chaque cote.

    On elargit point par point plutot que de prendre le rectangle englobant :
    une boucle de 15 km tient dans un rectangle de 8 km de cote, dont on ne
    verra jamais les trois quarts.
    """
    besoin: set[Carreau] = set()
    for z in zooms:
        for lon, lat in points:
            par_lat, par_lon = _degres_par_metre(lat)
            dlat, dlon = marge_m * par_lat, marge_m * par_lon
            x1, y1 = carreau_de(lon - dlon, lat + dlat, z)
            x2, y2 = carreau_de(lon + dlon, lat - dlat, z)
            for x in range(min(x1, x2), max(x1, x2) + 1):
                for y in range(min(y1, y2), max(y1, y2) + 1):
                    besoin.add(Carreau(z, x, y))
    return besoin


# --------------------------------------------------------------- recuperation

FOURNISSEUR = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
ENTETE = {"User-Agent": "olifant/1.0 (randonnee, usage personnel et local)"}
PAUSE = 1.0          # secondes entre deux carreaux
TAILLE_MAX = 512 * 1024


class ErreurTuile(RuntimeError):
    """Le carreau n'a pas pu etre recupere."""


def recupere(besoin: set[Carreau], dossier, pause: float = PAUSE,
             journal=None) -> tuple[int, int, list[str]]:
    """Telecharge les carreaux absents du dossier. Rend (pris, deja la, echecs).

    Rien n'est retelecharge : c'est ce qui rend l'operation acceptable pour un
    service tenu par des benevoles. Un carreau deja sur le disque est un
    carreau qu'on ne demandera plus jamais.
    """
    dossier = Path(dossier)
    dire = journal or (lambda _: None)
    pris = deja = 0
    echecs: list[str] = []
    a_prendre = sorted((c for c in besoin
                        if not (dossier / c.chemin()).exists()),
                       key=lambda c: (c.z, c.x, c.y))
    deja = len(besoin) - len(a_prendre)
    if not a_prendre:
        return 0, deja, []

    dire("%d carreaux a prendre, %d deja la (environ %d min)"
         % (len(a_prendre), deja, max(1, round(len(a_prendre) * pause / 60))))
    for i, carreau in enumerate(a_prendre):
        cible = dossier / carreau.chemin()
        cible.parent.mkdir(parents=True, exist_ok=True)
        url = FOURNISSEUR.format(z=carreau.z, x=carreau.x, y=carreau.y)
        try:
            demande = urllib.request.Request(url, headers=ENTETE)
            with urllib.request.urlopen(demande, timeout=30) as reponse:
                contenu = reponse.read(TAILLE_MAX + 1)
            if len(contenu) > TAILLE_MAX or not contenu.startswith(b"\x89PNG"):
                raise ErreurTuile("ce n'est pas un PNG")
            cible.write_bytes(contenu)
            pris += 1
        except (urllib.error.HTTPError, urllib.error.URLError, OSError,
                ErreurTuile) as e:
            echecs.append("%s : %s" % (carreau.chemin(), str(e)[:60]))
            # Un refus franc veut dire qu'on insiste trop : on s'arrete la
            # plutot que de continuer a frapper a la porte.
            if isinstance(e, urllib.error.HTTPError) and e.code in (403, 429):
                dire("Le serveur de tuiles refuse (%s) : on s'arrete." % e.code)
                break
        if i % 50 == 49:
            dire("   %d / %d" % (i + 1, len(a_prendre)))
        time.sleep(pause)
    return pris, deja, echecs
