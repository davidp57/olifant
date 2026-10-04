"""Le controle qualite doit attraper ce qui gache une randonnee.

Aucun de ces tests ne touche au reseau : on fabrique des traces a la main.
"""

import math

import pytest

from olifant.modele import Parcours, Point, Segment, Trace
from olifant.qualite import branches, juge, recouvrement


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
    def parcours(self, etapes, themes=()):
        return Parcours(id="essai", nom="Essai", etapes=etapes, themes=list(themes))

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

    def test_une_boucle_de_ville_s_autorise_plus_de_bitume(self):
        # 60 % de trottoir : reproche a une boucle de campagne, pas a une
        # boucle urbaine, ou il n'existe pas de 5 km sans revetement dur.
        points = {"a": point("a", 6.10, 49.10)}
        trace = Trace("essai", "p", ligne((6.10, 49.10), (6.10, 49.10)),
                      [Segment(600, {"highway": "footway", "surface": "asphalt"}),
                       Segment(400, {"highway": "path"})])
        campagne = juge(self.parcours(["a", "a"]), trace, points)
        ville = juge(self.parcours(["a", "a"], themes=["ville"]), trace, points)
        assert any("revetement dur" in a for a in campagne.alertes)
        assert not any("revetement dur" in a for a in ville.alertes)

    def test_le_tout_trottoir_est_signale_meme_en_ville(self):
        points = {"a": point("a", 6.10, 49.10)}
        trace = Trace("essai", "p", ligne((6.10, 49.10), (6.10, 49.10)),
                      [Segment(800, {"highway": "footway", "surface": "asphalt"}),
                       Segment(200, {"highway": "path"})])
        bilan = juge(self.parcours(["a", "a"], themes=["ville"]), trace, points)
        assert any("revetement dur" in a for a in bilan.alertes)


def test_la_distance_est_bien_en_metres():
    from olifant.modele import distance_m
    # Un centieme de degre de latitude vaut a peu pres 1111 m partout.
    assert distance_m((6.0, 49.0), (6.0, 49.01)) == pytest.approx(1111, abs=5)
    assert distance_m((6.0, 49.0), (6.0, 49.0)) == 0


def carre(origine=(6.10, 49.10), cote=0.02):
    """Une boucle carree sans rien de refait, a parcourir dans le sens direct."""
    x, y = origine
    return (ligne((x, y), (x + cote, y)) + ligne((x + cote, y), (x + cote, y + cote))[1:]
            + ligne((x + cote, y + cote), (x, y + cote))[1:]
            + ligne((x, y + cote), (x, y))[1:])


class TestBranches:
    def test_une_boucle_franche_n_a_ni_liaison_ni_branche(self):
        assert branches(Trace("x", "p", carre(), [])) == (0.0, [])

    def test_trouve_le_cul_de_sac_et_sa_longueur(self):
        # Au milieu du premier cote, un crochet de 600 m vers le sud, et retour.
        boucle = carre()
        milieu = boucle[20]
        crochet = ligne(milieu[:2], (milieu[0], milieu[1] - 0.0054), pas=12)
        trace = Trace("x", "p", boucle[:20] + crochet + list(reversed(crochet))[1:]
                      + boucle[21:], [])
        liaison, trouvees = branches(trace)
        assert liaison == 0.0
        assert len(trouvees) == 1
        # La pointe du demi-tour n'est pas comptee : on mesure un peu moins.
        assert trouvees[0].metres == pytest.approx(600, abs=60)

    def test_le_chemin_pour_rejoindre_la_boucle_est_une_liaison(self):
        approche = ligne((6.08, 49.10), (6.10, 49.10), pas=20)
        trace = Trace("x", "p", approche + carre()[1:] + list(reversed(approche))[1:], [])
        liaison, trouvees = branches(trace, boucle=True)
        assert liaison == pytest.approx(1460, abs=100)
        assert trouvees == []

    def test_hors_d_une_boucle_le_debut_refait_est_une_branche(self):
        approche = ligne((6.08, 49.10), (6.10, 49.10), pas=20)
        trace = Trace("x", "p", approche + carre()[1:] + list(reversed(approche))[1:], [])
        liaison, trouvees = branches(trace, boucle=False)
        assert liaison == 0.0 and len(trouvees) == 1

    def test_une_branche_voulue_est_mesuree_mais_pas_reprochee(self):
        # Le crochet mene a « belvedere » : on y va pour lui, et on le dit.
        boucle = carre()
        milieu = boucle[20]
        bout = (milieu[0], milieu[1] - 0.0054)
        crochet = ligne(milieu[:2], bout, pas=12)
        trace = Trace("essai", "p", boucle[:20] + crochet + list(reversed(crochet))[1:]
                      + boucle[21:], [Segment(10000, {"highway": "path"})])
        points = {"a": point("a", 6.10, 49.10), "belvedere": point("belvedere", *bout)}
        def jugement(voulues):
            return juge(Parcours(id="e", nom="e", etapes=["a", "belvedere", "a"],
                                 branches_voulues=voulues), trace, points)
        reproche, assume = jugement({}), jugement({"belvedere": "la vue"})
        assert [b.vers for b in assume.branches] == ["belvedere"]
        assert any("branche" in a for a in reproche.alertes)
        assert not any("branche" in a for a in assume.alertes)
        assert assume.branches[0].metres == reproche.branches[0].metres

    def test_le_jugement_signale_une_longue_branche(self):
        boucle = carre()
        milieu = boucle[20]
        crochet = ligne(milieu[:2], (milieu[0], milieu[1] - 0.0054), pas=12)
        points = {"a": point("a", 6.10, 49.10)}
        trace = Trace("essai", "p", boucle[:20] + crochet + list(reversed(crochet))[1:]
                      + boucle[21:], [Segment(10000, {"highway": "path"})])
        bilan = juge(Parcours(id="e", nom="e", etapes=["a", "b", "a"]), trace,
                     {**points, "b": point("b", 6.12, 49.10)})
        assert any("branche" in a for a in bilan.alertes)
