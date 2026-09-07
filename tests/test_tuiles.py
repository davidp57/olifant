"""Le couloir de carreaux : ce qu'on emporte, et pas plus.

Aucun test ne telecharge : on ne verifie que la geometrie et le comptage.
"""

import pytest

from olifant.tuiles import Carreau, ZOOMS, carreau_de, couloir

# Le parvis de la gare de Metz, et un point a un kilometre au nord.
GARE = (6.177013, 49.109277)
NORD = (6.177013, 49.118277)


class TestNumerotation:
    def test_le_centre_du_monde_est_au_milieu_de_la_grille(self):
        """L'ancre qui ne demande aucune table de reference : au zoom 10 la
        grille fait 1024 carreaux de cote, et l'origine des coordonnees tombe
        pile a son milieu."""
        assert carreau_de(0.0, 0.0, 10) == (512, 512)

    @pytest.mark.parametrize("lon,lat,z,attendu", [
        (6.177013, 49.109277, 15, (16946, 11238)),   # le parvis de la gare
        (6.177013, 49.109277, 13, (4236, 2809)),
        (6.341200, 49.309500, 16, (33922, 22420)),   # Kedange-sur-Canner
        (13.4, 52.5, 14, (8801, 5374)),
    ])
    def test_place_un_point_dans_le_bon_carreau(self, lon, lat, z, attendu):
        """Valeurs croisees avec la formule OSM ecrite autrement -- en
        log(tan + sec) plutot qu'en asinh -- et non recopiees de la sortie du
        code teste, ce qui ne prouverait rien.
        """
        assert carreau_de(lon, lat, z) == attendu

    def test_concorde_avec_la_formule_ecrite_autrement(self):
        import math

        def autrement(lon, lat, z):
            n = 2 ** z
            r = math.radians(lat)
            return (int((lon + 180.0) / 360.0 * n),
                    int((1.0 - math.log(math.tan(r) + 1.0 / math.cos(r))
                         / math.pi) / 2.0 * n))

        for lon, lat, z in [(6.18, 49.11, 16), (-1.5, 47.2, 12), (0.0, 0.0, 10),
                            (6.35, 49.44, 15), (13.4, 52.5, 14)]:
            assert carreau_de(lon, lat, z) == autrement(lon, lat, z)

    def test_le_zoom_multiplie_par_deux_a_chaque_niveau(self):
        x14, y14 = carreau_de(*GARE, 14)
        x15, y15 = carreau_de(*GARE, 15)
        assert (x15 // 2, y15 // 2) == (x14, y14)

    def test_ne_sort_pas_du_monde(self):
        for lat in (-89.0, 89.0):
            x, y = carreau_de(0.0, lat, 4)
            assert 0 <= x < 16 and 0 <= y < 16


class TestCouloir:
    def test_couvre_le_point_demande(self):
        besoin = couloir([GARE], zooms=(15,), marge_m=0)
        x, y = carreau_de(*GARE, 15)
        assert Carreau(15, x, y) in besoin

    def test_la_marge_elargit_le_couloir(self):
        etroit = couloir([GARE], zooms=(16,), marge_m=50)
        large = couloir([GARE], zooms=(16,), marge_m=1000)
        assert len(large) > len(etroit)

    def test_couvre_tous_les_zooms_demandes(self):
        besoin = couloir([GARE], zooms=(13, 14, 15))
        assert {c.z for c in besoin} == {13, 14, 15}

    def test_suit_la_trace_et_non_son_rectangle(self):
        """Une boucle de quinze kilometres tient dans un rectangle de huit
        kilometres de cote dont on ne verra jamais les trois quarts : on
        elargit point par point, pas d'un bloc."""
        # Deux points eloignes, sans rien entre eux.
        deux_bouts = couloir([GARE, (6.35, 49.44)], zooms=(14,), marge_m=300)
        # Le rectangle englobant, lui, couvrirait tout l'entre-deux.
        x1, y1 = carreau_de(*GARE, 14)
        x2, y2 = carreau_de(6.35, 49.44, 14)
        rectangle = (abs(x2 - x1) + 1) * (abs(y2 - y1) + 1)
        assert len(deux_bouts) < rectangle / 2

    def test_le_compte_reste_raisonnable_pour_une_boucle(self):
        """Garde-fou : les serveurs de tuiles sont tenus par des benevoles, et
        un couloir qui explose se verrait ici avant de partir en requetes."""
        # Une ligne de quinze kilometres, echantillonnee tous les cent metres.
        trace = [(6.177013, 49.109277 + i * 0.0009) for i in range(150)]
        assert len(couloir(trace, zooms=ZOOMS)) < 400

    def test_un_carreau_est_son_chemin(self):
        assert Carreau(15, 16814, 11185).chemin() == "15/16814/11185.png"

    def test_ne_compte_pas_deux_fois_le_meme_carreau(self):
        """Deux points voisins tombent dans le meme carreau : l'ensemble ne
        doit le contenir qu'une fois, sinon on le telechargerait deux fois."""
        proches = [GARE, (GARE[0] + 0.00001, GARE[1] + 0.00001)]
        assert len(couloir(proches, zooms=(13,), marge_m=0)) == 1
