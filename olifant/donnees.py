"""Lecture du fichier de reference, data/parcours.yaml.

Ce fichier est la seule chose ecrite a la main. Il est en YAML pour qu'on
puisse y mettre des commentaires et le relire sans plisser les yeux.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .modele import Parcours, Point


@dataclass
class Recueil:
    meta: dict
    points: dict[str, Point]
    parcours: list[Parcours]

    def par_id(self, pid: str) -> Parcours | None:
        return next((p for p in self.parcours if p.id == pid), None)


def charge(chemin: Path) -> Recueil:
    brut = yaml.safe_load(Path(chemin).read_text(encoding="utf-8")) or {}
    points = {
        cle: Point(cle=cle, nom=v["nom"], lon=float(v["lon"]), lat=float(v["lat"]),
                   note=v.get("note", ""))
        for cle, v in (brut.get("points") or {}).items()
    }
    parcours = [
        Parcours(
            id=p["id"], nom=p["nom"], etapes=list(p["etapes"]),
            acces=p.get("acces", "a pied"), parking=p.get("parking", ""),
            resume=p.get("resume", ""), themes=list(p.get("themes") or []),
            couleur=p.get("couleur", "3388ff"),
        )
        for p in (brut.get("parcours") or [])
    ]
    _verifie(points, parcours)
    return Recueil(meta=brut.get("meta") or {}, points=points, parcours=parcours)


def _verifie(points: dict[str, Point], parcours: list[Parcours]) -> None:
    """Attrape tout de suite les fautes de frappe, plutot qu'a l'appel reseau."""
    vus = set()
    for p in parcours:
        if p.id in vus:
            raise ValueError("deux parcours portent l'identifiant « %s »" % p.id)
        vus.add(p.id)
        inconnus = [c for c in p.etapes if c not in points]
        if inconnus:
            raise ValueError("parcours « %s » : etapes inconnues %s"
                             % (p.id, ", ".join(sorted(set(inconnus)))))
        if len(p.etapes) < 2:
            raise ValueError("parcours « %s » : il faut au moins deux etapes" % p.id)
