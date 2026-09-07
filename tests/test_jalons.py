"""Le kilometrage des etapes doit tenir meme quand la trace repasse.

Aucun de ces tests ne touche au reseau : on fabrique des traces a la main.
"""

import pytest

from olifant.jalons import etapes_situees, jalonne
from olifant.modele import Parcours, Point, Segment, Trace


def point(cle, lon, lat, note=""):
    return Point(cle=cle, nom=cle.capitalize(), lon=lon, lat=lat, note=note)


def trace_de(coords, metres=None):
    """Une trace dont on ne se sert que pour la geometrie."""
    points = [(lon, lat, 200.0) for lon, lat in coords]
    return Trace(parcours_id="essai", profil="hiking-beta", points=points,
                 segments=[Segment(metres or 1000.0, {"highway": "path"})])


# Un degre de latitude vaut environ 111 km : les reperes ci-dessous sont donc
# espaces de 1,11 km, ce qui rend les kilometrages faciles a verifier de tete.
def colonne(nb, lon=6.0, lat0=49.0, pas=0.01):
    return [(lon, lat0 + i * pas) for i in range(nb)]


class TestJalonnement:
    def test_situe_les_etapes_dans_l_ordre(self):
        # Trois etapes le long d'une ligne droite de 2,22 km.
        points = {"a": point("a", 6.0, 49.0), "b": point("b", 6.0, 49.01),
                  "c": point("c", 6.0, 49.02)}
        p = Parcours(id="x", nom="X", etapes=["a", "b", "c"])
        jalons = jalonne(p, trace_de(colonne(3)), points)

        assert [j.cle for j in jalons] == ["a", "b", "c"]
        assert jalons[0].metres == pytest.approx(0, abs=1)
        assert jalons[1].metres == pytest.approx(1112, abs=20)
        assert jalons[2].metres == pytest.approx(2224, abs=40)

    def test_l_arrivee_d_une_boucle_n_est_pas_au_kilometre_zero(self):
        """Le piege que ce module existe pour eviter.

        Sur une boucle, la derniere etape est le point de depart. Prendre le
        point de trace le plus proche lui donnerait le kilometre zero ; c'est
        la distance totale qu'on veut.
        """
        aller = colonne(3)
        retour = [(6.001, 49.02), (6.001, 49.01), (6.0, 49.0)]
        points = {"a": point("a", 6.0, 49.0), "b": point("b", 6.0, 49.02)}
        p = Parcours(id="x", nom="X", etapes=["a", "b", "a"])
        jalons = jalonne(p, trace_de(aller + retour), points)

        assert jalons[0].metres == pytest.approx(0, abs=1)
        assert jalons[2].metres > jalons[1].metres
        assert jalons[2].metres == pytest.approx(4500, abs=300)

    def test_une_etape_traversee_deux_fois_garde_le_bon_ordre(self):
        """Un aller-retour repasse par le meme carrefour : les kilometrages
        doivent rester croissants, pas retomber sur la premiere visite."""
        trace = trace_de(colonne(5) + [(6.0, 49.03), (6.0, 49.02), (6.0, 49.05)])
        points = {"depart": point("depart", 6.0, 49.0),
                  "carrefour": point("carrefour", 6.0, 49.02),
                  "sommet": point("sommet", 6.0, 49.05)}
        p = Parcours(id="x", nom="X", etapes=["depart", "carrefour", "sommet"])
        jalons = jalonne(p, trace, points)

        assert [round(j.km, 1) for j in jalons] == sorted(round(j.km, 1) for j in jalons)
        assert jalons[1].metres > 0

    def test_mesure_l_ecart_entre_l_etape_et_la_trace(self):
        """Une etape posee a cote du chemin : on veut savoir de combien."""
        points = {"a": point("a", 6.0, 49.0), "b": point("b", 6.01, 49.01)}
        p = Parcours(id="x", nom="X", etapes=["a", "b"])
        jalons = jalonne(p, trace_de(colonne(2)), points)

        assert jalons[0].ecart_m == pytest.approx(0, abs=1)
        # 0,01 degre de longitude a cette latitude : environ 730 m.
        assert jalons[1].ecart_m == pytest.approx(730, abs=60)

    def test_une_trace_vide_ne_fait_pas_tomber_le_calcul(self):
        p = Parcours(id="x", nom="X", etapes=["a", "b"])
        vide = Trace(parcours_id="x", profil="hiking-beta", points=[], segments=[])
        assert jalonne(p, vide, {"a": point("a", 6.0, 49.0)}) == []


class TestEtapesPubliees:
    def test_le_depart_n_apparait_qu_une_fois(self):
        aller = colonne(3)
        retour = [(6.001, 49.02), (6.0, 49.0)]
        points = {"a": point("a", 6.0, 49.0, "Le parking"),
                  "b": point("b", 6.0, 49.02, "Le sommet")}
        p = Parcours(id="x", nom="X", etapes=["a", "b", "a"])
        etapes = etapes_situees(p, trace_de(aller + retour), points)

        assert [e["cle"] for e in etapes] == ["a", "b"]
        assert etapes[0]["depart"] is True
        assert etapes[0]["km"] == 0.0
        assert etapes[0]["note"] == "Le parking"

    def test_donne_l_avancement_en_pourcentage(self):
        """De quoi dessiner une reglette : ou en est-on de la boucle."""
        points = {"a": point("a", 6.0, 49.0), "b": point("b", 6.0, 49.01),
                  "c": point("c", 6.0, 49.02)}
        p = Parcours(id="x", nom="X", etapes=["a", "b", "c"])
        etapes = etapes_situees(p, trace_de(colonne(3)), points)

        assert [e["part"] for e in etapes] == [0, 50, 100]
