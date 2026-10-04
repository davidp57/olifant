"""Les outils de composition : ou aller, par ou ca passe, est-ce nouveau.

Rien ne touche au reseau : les traces et les reponses Overpass sont fabriquees.
"""

import argparse

import pytest

from olifant import cli
from olifant.composition import (Candidat, candidats, part_neuve, requete_lieux,
                                 troncons)
from olifant.modele import Parcours, Point, Trace


def point(cle, lon, lat):
    return Point(cle=cle, nom=cle, lon=lon, lat=lat)


def ligne(depart, arrivee, pas=40):
    return [(depart[0] + (arrivee[0] - depart[0]) * i / pas,
             depart[1] + (arrivee[1] - depart[1]) * i / pas, 200.0)
            for i in range(pas + 1)]


class TestPartNeuve:
    def test_une_trace_seule_est_toute_neuve(self):
        assert part_neuve(Trace("x", "p", ligne((6.10, 49.10), (6.12, 49.10)), []),
                          []) == pytest.approx(100)

    def test_une_trace_deja_parcourue_n_a_rien_de_neuf(self):
        meme = ligne((6.10, 49.10), (6.12, 49.10))
        assert part_neuve(Trace("x", "p", meme, []), [Trace("y", "p", meme, [])]) == 0

    def test_moitie_sur_un_parcours_connu(self):
        connu = Trace("y", "p", ligne((6.10, 49.10), (6.11, 49.10)), [])
        essai = Trace("x", "p", ligne((6.10, 49.10), (6.12, 49.10)), [])
        assert part_neuve(essai, [connu]) == pytest.approx(50, abs=5)

    def test_un_chemin_parallele_a_300_m_est_neuf(self):
        connu = Trace("y", "p", ligne((6.10, 49.10), (6.12, 49.10)), [])
        essai = Trace("x", "p", ligne((6.10, 49.1027), (6.12, 49.1027)), [])
        assert part_neuve(essai, [connu]) == pytest.approx(100)


class TestTroncons:
    def test_mesure_chaque_troncon_et_son_detour(self):
        a, b, c = point("a", 6.10, 49.10), point("b", 6.12, 49.10), point("c", 6.12, 49.11)
        # De b a c, on fait un crochet par l'est : le troncon est plus long
        # que la ligne droite.
        chemin = (ligne(a.lonlat, b.lonlat)
                  + ligne(b.lonlat, (6.13, 49.10))[1:]
                  + ligne((6.13, 49.10), (6.13, 49.11))[1:]
                  + ligne((6.13, 49.11), c.lonlat)[1:])
        parcours = Parcours(id="e", nom="e", etapes=["a", "b", "c"])
        t = troncons(parcours, Trace("e", "p", chemin, []), {"a": a, "b": b, "c": c})
        assert [(x.de, x.a) for x in t] == [("a", "b"), ("b", "c")]
        assert t[0].detour == pytest.approx(1.0, abs=0.02)
        # 730 m vers l'est, 1112 m vers le nord, 730 m retour : 2572 m pour
        # 1112 m a vol d'oiseau. Un degre de longitude est court a 49 degres.
        assert t[1].detour == pytest.approx(2.31, abs=0.05)


class TestCandidats:
    def reponse(self, *elements):
        return {"elements": list(elements)}

    def test_ecarte_ce_qu_un_point_connu_touche_deja(self):
        connus = [point("parc", 6.10, 49.10)]
        r = self.reponse(
            {"lon": 6.1001, "lat": 49.1001, "tags": {"leisure": "park", "name": "Deja vu"}},
            {"lon": 6.13, "lat": 49.10, "tags": {"natural": "wood", "name": "Bois neuf"}})
        trouves = candidats(r, (6.10, 49.10), connus)
        assert [c.nom for c in trouves] == ["Bois neuf"]
        assert trouves[0].genre == "wood"

    def test_un_bois_en_morceaux_ne_compte_qu_une_fois(self):
        r = self.reponse(
            {"center": {"lon": 6.15, "lat": 49.10},
             "tags": {"landuse": "forest", "name": "Bois Carre"}},
            {"center": {"lon": 6.14, "lat": 49.10},
             "tags": {"landuse": "forest", "name": "Bois carre"}})
        trouves = candidats(r, (6.10, 49.10), [])
        assert len(trouves) == 1 and trouves[0].lon == 6.14

    def test_deux_points_de_vue_sans_nom_restent_deux(self):
        r = self.reponse(
            {"lon": 6.12, "lat": 49.10, "tags": {"tourism": "viewpoint"}},
            {"lon": 6.15, "lat": 49.12, "tags": {"tourism": "viewpoint"}})
        assert len(candidats(r, (6.10, 49.10), [])) == 2

    def test_classe_du_plus_proche_au_plus_lointain(self):
        r = self.reponse(
            {"lon": 6.16, "lat": 49.10, "tags": {"historic": "fort", "name": "Loin"}},
            {"lon": 6.12, "lat": 49.10, "tags": {"tourism": "viewpoint"}})
        assert [c.nom for c in candidats(r, (6.10, 49.10), [])] == ["Point de vue", "Loin"]

    def test_la_requete_vise_le_centre_et_le_rayon(self):
        corps = requete_lieux((6.18, 49.11), 3000)
        assert "around:3000,49.110000,6.180000" in corps
        assert '"historic"~"^(fort|castle|ruins)$"' in corps


class TestEtapeAdHoc:
    def test_une_cle_connue_reste_telle_quelle(self):
        points = {"gare": point("gare", 6.17, 49.10)}
        assert cli._etape("gare", points) == "gare"
        assert len(points) == 1

    def test_un_lieu_lon_lat_devient_une_etape(self):
        points = {}
        cle = cli._etape("6.2157,49.1316", points)
        assert points[cle].lonlat == (6.2157, 49.1316)

    def test_le_reste_est_refuse(self):
        with pytest.raises(ValueError):
            cli._etape("bois-inconnu", {})
