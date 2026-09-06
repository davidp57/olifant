"""Le controle qualite doit attraper ce qui gache une randonnee.

Aucun de ces tests ne touche au reseau : on fabrique des traces a la main.
"""

import math

import pytest

from olifant.modele import Parcours, Point, Segment, Trace
from olifant.qualite import juge, recouvrement


def point(cle, lon, lat):
    return Point(cle=cle, nom=cle, lon=lon, lat=lat)


def ligne(depart, arrivee, pas=40):
    """Une suite de points reguliers entre deux coordonnees."""
    return [(depart[0] + (arrivee[0] - depart[0]) * i / pas,
             depart[1] + (arrivee[1] - depart[1]) * i / pas, 200.0)
            for i in range(pas + 1)]


class TestRevetement:
    @pytest.mark.parametrize("tags,attendu", [
        ({"highway": "path"}, "chemin"),
        ({"highway": "track", "tracktype": "grade3"}, "chemin"),
        ({"highway": "residential"}, "route"),
        ({"highway": "tertiary", "surface": "asphalt"}, "route"),
        ({"highway": "footway", "surface": "asphalt"}, "bitume"),
        ({"highway": "footway", "surface": "ground"}, "chemin"),
        ({"highway": "pedestrian", "surface": "paving_stones"}, "bitume"),
    ])
    def test_classe_les_voies(self, tags, attendu):
        assert Segment(100, tags).revetement == attendu

    def test_repere_un_itineraire_balise(self):
        assert Segment(100, {"highway": "path", "route_hiking_rwn": "yes"}).balise
        assert not Segment(100, {"highway": "path"}).balise


class TestParts:
    def test_les_parts_se_calculent_sur_la_distance_pas_le_nombre(self):
        trace = Trace("x", "hiking-beta", [], [
            Segment(900, {"highway": "path"}),
            Segment(100, {"highway": "residential"}),
        ])
        # Deux segments, mais neuf dixiemes de la distance sur du chemin.
        assert trace.part("chemin") == pytest.approx(90)
        assert trace.part("route") == pytest.approx(10)

    def test_une_trace_vide_ne_divise_pas_par_zero(self):
        assert Trace("x", "p", [], []).part("chemin") == 0.0


class TestRecouvrement:
    def test_un_aller_retour_compte_pour_moitie(self):
        aller = ligne((6.10, 49.10), (6.12, 49.10))
        trace = Trace("x", "p", aller + list(reversed(aller)), [])
        assert recouvrement(trace) == pytest.approx(50, abs=8)

    def test_une_boucle_ne_repasse_pas_sur_elle_meme(self):
        cote = 0.02
        boucle = (ligne((6.10, 49.10), (6.10 + cote, 49.10))
                  + ligne((6.10 + cote, 49.10), (6.10 + cote, 49.10 + cote))
                  + ligne((6.10 + cote, 49.10 + cote), (6.10, 49.10 + cote))
                  + ligne((6.10, 49.10 + cote), (6.10, 49.10)))
        assert recouvrement(Trace("x", "p", boucle, [])) < 5


class TestJugement:
    def parcours(self, etapes):
        return Parcours(id="essai", nom="Essai", etapes=etapes)

    def test_signale_une_etape_que_le_routeur_a_rattachee_ailleurs(self):
        # Le point « bois » est a 500 m au nord de tout ce que la trace touche.
        points = {"a": point("a", 6.10, 49.10), "bois": point("bois", 6.11, 49.1045),
                  "b": point("b", 6.12, 49.10)}
        trace = Trace("essai", "p", ligne((6.10, 49.10), (6.12, 49.10)), [])
        bilan = juge(self.parcours(["a", "bois", "b"]), trace, points)
        assert [cle for cle, _ in bilan.etapes_loin] == ["bois"]
        assert any("rattachee" in a for a in bilan.alertes)

    def test_signale_une_boucle_qui_ne_se_referme_pas(self):
        points = {"a": point("a", 6.10, 49.10), "b": point("b", 6.12, 49.10)}
        trace = Trace("essai", "p", ligne((6.10, 49.10), (6.12, 49.10)), [])
        bilan = juge(self.parcours(["a", "b", "a"]), trace, points)
        assert bilan.boucle_ouverte_m > 1000
        assert any("ne se referme pas" in a for a in bilan.alertes)

    def test_ne_reproche_rien_a_une_bonne_boucle(self):
        cote = 0.02
        chemin = (ligne((6.10, 49.10), (6.12, 49.10))
                  + ligne((6.12, 49.10), (6.12, 49.10 + cote))
                  + ligne((6.12, 49.10 + cote), (6.10, 49.10)))
        points = {"a": point("a", 6.10, 49.10), "b": point("b", 6.12, 49.10)}
        trace = Trace("essai", "p", chemin, [Segment(10000, {"highway": "path"})])
        bilan = juge(self.parcours(["a", "b", "a"]), trace, points)
        assert bilan.bon, bilan.alertes

    def test_signale_le_bitume(self):
        points = {"a": point("a", 6.10, 49.10)}
        trace = Trace("essai", "p", ligne((6.10, 49.10), (6.10, 49.10)),
                      [Segment(900, {"highway": "footway", "surface": "asphalt"}),
                       Segment(100, {"highway": "path"})])
        bilan = juge(self.parcours(["a", "a"]), trace, points)
        assert any("revetement dur" in a for a in bilan.alertes)


def test_la_distance_est_bien_en_metres():
    from olifant.modele import distance_m
    # Un centieme de degre de latitude vaut a peu pres 1111 m partout.
    assert distance_m((6.0, 49.0), (6.0, 49.01)) == pytest.approx(1111, abs=5)
    assert distance_m((6.0, 49.0), (6.0, 49.0)) == 0
