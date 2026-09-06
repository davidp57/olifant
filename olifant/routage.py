"""Calcul des traces : on demande au routeur de relier les etapes par des chemins.

Un seul appel reseau par parcours : BRouter accepte toute la suite de points
d'un coup, ce qui evite les recollements approximatifs et menage un service
public et benevole. Chaque reponse est gardee sur disque, indexee par une
empreinte des coordonnees et du profil : rejouer un calcul ne coute rien.

Le profil compte enormement. `hiking-beta` privilegie les sentiers et sait lire
les itineraires de randonnee balises d'OpenStreetMap ; `trekking`, le profil
qu'on prend spontanement, fait deux a trois fois plus de bitume.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from .modele import Parcours, Point, Segment, Trace

BROUTER = "https://brouter.de/brouter"
PROFIL_DEFAUT = "hiking-beta"
ENTETE = {"User-Agent": "olifant/1.0 (randonnee, usage personnel)"}
PAUSE = 2.0          # secondes entre deux appels reseau, par politesse
REESSAIS = 4         # BRouter refuse poliment quand on insiste : on attend
ATTENTE = 20.0       # secondes avant le premier reessai, doublees a chaque fois


class ErreurRoutage(RuntimeError):
    """Le routeur n'a pas su relier les points demandes."""


class Routeur:
    def __init__(self, cache: Path, profil: str = PROFIL_DEFAUT, hors_ligne: bool = False):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.profil = profil
        self.hors_ligne = hors_ligne
        self._dernier_appel = 0.0

    # -- cache -------------------------------------------------------------

    def _empreinte(self, lonlats: list[tuple[float, float]]) -> str:
        brut = json.dumps([[round(x, 6), round(y, 6)] for x, y in lonlats]) + "|" + self.profil
        return hashlib.sha1(brut.encode()).hexdigest()[:16]

    # -- reseau ------------------------------------------------------------

    def _appelle(self, lonlats: list[tuple[float, float]]) -> dict:
        url = "%s?lonlats=%s&profile=%s&alternativeidx=0&format=geojson" % (
            BROUTER,
            "|".join("%.6f,%.6f" % (x, y) for x, y in lonlats),
            self.profil,
        )
        attente = PAUSE - (time.monotonic() - self._dernier_appel)
        if attente > 0:
            time.sleep(attente)
        requete = urllib.request.Request(url, headers=ENTETE)
        attente = ATTENTE
        for essai in range(REESSAIS):
            try:
                with urllib.request.urlopen(requete, timeout=120) as reponse:
                    brut = reponse.read().decode("utf-8")
                break
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:200]
                # 403 et 429 veulent dire « tu vas trop vite », pas « c'est faux ».
                if e.code in (403, 429, 502, 503) and essai < REESSAIS - 1:
                    print("   BRouter demande d'attendre, reprise dans %d s" % attente)
                    time.sleep(attente)
                    attente *= 2
                    continue
                self._dernier_appel = time.monotonic()
                raise ErreurRoutage("BRouter a refuse (%s) : %s" % (e.code, detail)) from e
            except OSError as e:
                self._dernier_appel = time.monotonic()
                raise ErreurRoutage("BRouter injoignable : %s" % e) from e
        self._dernier_appel = time.monotonic()
        try:
            donnees = json.loads(brut)
        except json.JSONDecodeError:
            # BRouter renvoie un message en clair quand il ne trouve pas de route.
            raise ErreurRoutage("BRouter : %s" % brut.strip()[:300]) from None
        if not donnees.get("features"):
            raise ErreurRoutage("BRouter n'a renvoye aucune trace")
        return donnees

    def geojson(self, lonlats: list[tuple[float, float]]) -> dict:
        """Le geojson brut du routeur, depuis le cache si possible."""
        fichier = self.cache / ("%s.json" % self._empreinte(lonlats))
        if fichier.exists():
            return json.loads(fichier.read_text(encoding="utf-8"))
        if self.hors_ligne:
            raise ErreurRoutage("rien en cache et mode hors ligne")
        donnees = self._appelle(lonlats)
        fichier.write_text(json.dumps(donnees), encoding="utf-8")
        return donnees

    # -- lecture de la reponse --------------------------------------------

    def trace(self, parcours: Parcours, points: dict[str, Point]) -> Trace:
        manquants = [c for c in parcours.etapes if c not in points]
        if manquants:
            raise ErreurRoutage("points inconnus : %s" % ", ".join(manquants))
        lonlats = [points[c].lonlat for c in parcours.etapes]
        donnees = self.geojson(lonlats)
        forme = donnees["features"][0]
        coords = [(c[0], c[1], float(c[2]) if len(c) > 2 else 0.0)
                  for c in forme["geometry"]["coordinates"]]
        props = forme.get("properties", {})
        return Trace(
            parcours_id=parcours.id,
            profil=self.profil,
            points=coords,
            segments=_segments(props.get("messages")),
            montee=float(props.get("filtered ascend") or 0),
        )


def _segments(messages: list[list[str]] | None) -> list[Segment]:
    """Traduit le tableau `messages` de BRouter en troncons exploitables.

    La premiere ligne est un en-tete qui nomme les colonnes ; on s'y refere par
    nom plutot que par position, le format ayant deja bouge par le passe.
    """
    if not messages or len(messages) < 2:
        return []
    entete = messages[0]
    try:
        i_dist, i_tags = entete.index("Distance"), entete.index("WayTags")
    except ValueError:
        return []
    troncons = []
    for ligne in messages[1:]:
        try:
            metres = float(ligne[i_dist])
        except (ValueError, IndexError):
            continue
        brut = ligne[i_tags] if len(ligne) > i_tags else ""
        tags = dict(t.split("=", 1) for t in brut.split() if "=" in t)
        troncons.append(Segment(metres=metres, tags=tags))
    return troncons
