"""Relire un GPX rapporte d'une sortie : ce fichier vient de l'exterieur.

Les tests couvrent ce qui peut mal tourner : un XML hostile, un GPX sans
trace, des altitudes bruitees, une geometrie beaucoup trop lourde pour un
telephone.
"""

import pytest

from olifant.suivi import ErreurGpx, TOLERANCE_M, allege, lis

ENTETE = ('<?xml version="1.0" encoding="UTF-8"?>'
          '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">')


def gpx(points, altitudes=None, nommage=True):
    """Un GPX minimal, avec ou sans espace de noms."""
    lignes = []
    for i, (lon, lat) in enumerate(points):
        ele = ""
        if altitudes is not None:
            ele = "<ele>%s</ele>" % altitudes[i]
        lignes.append('<trkpt lat="%s" lon="%s">%s</trkpt>' % (lat, lon, ele))
    corps = "<trk><trkseg>%s</trkseg></trk>" % "".join(lignes)
    if nommage:
        return ENTETE + corps + "</gpx>"
    return '<?xml version="1.0"?><gpx version="1.1">' + corps + "</gpx>"


class TestLecture:
    def test_lit_une_trace_simple(self):
        trace = lis(gpx([(6.0, 49.0), (6.0, 49.01), (6.0, 49.02)]))
        assert len(trace.troncons) == 1
        assert trace.km == pytest.approx(2.22, abs=0.05)

    def test_accepte_un_gpx_sans_espace_de_noms(self):
        """Les applications de randonnee ne s'accordent pas la-dessus, et un
        refus pour un detail de forme serait incomprehensible."""
        trace = lis(gpx([(6.0, 49.0), (6.0, 49.01)], nommage=False))
        assert trace.points == 2

    def test_accepte_des_octets(self):
        assert lis(gpx([(6.0, 49.0), (6.0, 49.01)]).encode()).points == 2

    def test_garde_les_troncons_separes(self):
        """Une pause qui coupe l'enregistrement ne doit pas creer un trait
        droit d'un kilometre entre les deux morceaux."""
        deux = (ENTETE + '<trk>'
                '<trkseg><trkpt lat="49.0" lon="6.0"/><trkpt lat="49.01" lon="6.0"/></trkseg>'
                '<trkseg><trkpt lat="49.1" lon="6.1"/><trkpt lat="49.11" lon="6.1"/></trkseg>'
                '</trk></gpx>')
        trace = lis(deux)
        assert len(trace.troncons) == 2
        assert trace.km == pytest.approx(2.22, abs=0.1)   # sans le saut
        assert len(trace.geojson()["geometry"]["coordinates"]) == 2

    def test_refuse_un_gpx_sans_trace(self):
        sans = ENTETE + '<wpt lat="49.0" lon="6.0"><name>Depart</name></wpt></gpx>'
        with pytest.raises(ErreurGpx, match="aucun segment"):
            lis(sans)

    def test_refuse_un_xml_casse(self):
        with pytest.raises(ErreurGpx, match="illisible"):
            lis("<gpx><trk>")

    def test_ignore_un_point_sans_coordonnees(self):
        bancal = (ENTETE + '<trk><trkseg>'
                  '<trkpt lat="49.0" lon="6.0"/><trkpt lat="49.01"/>'
                  '<trkpt lat="49.02" lon="6.0"/></trkseg></trk></gpx>')
        assert lis(bancal).points == 2

    def test_resiste_a_une_bombe_a_entites(self):
        """Le fichier vient d'un telephone qu'on ne controle pas : un XML
        recursif ne doit pas immobiliser le serveur."""
        bombe = ('<?xml version="1.0"?><!DOCTYPE gpx ['
                 '<!ENTITY a "aaaaaaaaaa">'
                 '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
                 '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">'
                 ']><gpx><trk><trkseg><trkpt lat="49.0" lon="6.0">&c;</trkpt>'
                 '</trkseg></trk></gpx>')
        with pytest.raises(ErreurGpx):
            lis(bombe)

    def test_refuse_une_entite_qui_lit_un_fichier_local(self):
        xxe = ('<?xml version="1.0"?><!DOCTYPE gpx ['
               '<!ENTITY fuite SYSTEM "file:///etc/passwd">]>'
               '<gpx><trk><trkseg><trkpt lat="49.0" lon="6.0">&fuite;</trkpt>'
               '</trkseg></trk></gpx>')
        with pytest.raises(ErreurGpx):
            lis(xxe)


class TestMontee:
    def test_additionne_les_montees(self):
        trace = lis(gpx([(6.0, 49.0), (6.0, 49.01), (6.0, 49.02)],
                        altitudes=[200, 250, 230]))
        assert trace.montee == pytest.approx(50, abs=1)

    def test_ignore_le_bruit_du_barometre(self):
        """Un GPS oscille de deux metres a l'arret : sommer toutes les
        variations donnerait des centaines de metres sur du plat."""
        oscillant = [200 + (2 if i % 2 else 0) for i in range(40)]
        points = [(6.0, 49.0 + i * 0.0001) for i in range(40)]
        assert lis(gpx(points, altitudes=oscillant)).montee == 0

    def test_se_passe_des_altitudes_absentes(self):
        assert lis(gpx([(6.0, 49.0), (6.0, 49.01)])).montee == 0


class TestAllegement:
    def test_garde_les_extremites(self):
        points = [(6.0, 49.0), (6.0, 49.001), (6.0, 49.002)]
        allege_ = allege(points)
        assert allege_[0] == points[0] and allege_[-1] == points[-1]

    def test_supprime_les_points_alignes(self):
        """Cent points sur une droite ne disent rien de plus que deux."""
        droite = [(6.0, 49.0 + i * 0.0001) for i in range(100)]
        assert len(allege(droite)) == 2

    def test_garde_un_virage_franc(self):
        coude = [(6.0, 49.0), (6.0, 49.01), (6.01, 49.01)]
        assert len(allege(coude)) == 3

    def test_ne_touche_pas_a_une_ligne_de_deux_points(self):
        deux = [(6.0, 49.0), (6.0, 49.01)]
        assert allege(deux) == deux

    def test_allege_vraiment_un_enregistrement_de_matinee(self):
        """Un point par seconde pendant trois heures, en zigzag serre : ce
        qui part au telephone doit tenir en quelques centaines de points."""
        import math
        brut = [(6.0 + 0.00002 * math.sin(i / 3), 49.0 + i * 0.000005)
                for i in range(10800)]
        assert len(brut) == 10800
        assert len(allege(brut)) < 400

    def test_ne_deforme_pas_la_ligne_au_dela_de_la_tolerance(self):
        import math
        brut = [(6.0 + 0.0004 * math.sin(i / 40), 49.0 + i * 0.00002)
                for i in range(2000)]
        leger = allege(brut)
        # Chaque point supprime reste a moins de la tolerance de la ligne
        # conservee : la forme est preservee, pas seulement la longueur.
        from olifant.suivi import _ecart_a_la_corde
        indices = {p: i for i, p in enumerate(leger)}
        pire = 0.0
        for point in brut:
            if point in indices:
                continue
            pire = max(pire, min(
                _ecart_a_la_corde(point, a, b) for a, b in zip(leger, leger[1:])))
        assert pire <= TOLERANCE_M * 1.5


class TestDebruitage:
    """Ce que la mesure a impose : un GPS bruite gonfle enormement distance et
    denivele si on l'additionne tel quel. Sur un essai, 10,3 km de marche
    donnaient 13,5 km et 660 m de denivele au lieu de 61."""

    @staticmethod
    def marche_bruitee(nb=600, bruit=0.00004, graine=7):
        import random
        alea = random.Random(graine)
        points, altitudes = [], []
        for i in range(nb):
            # Une montee reguliere de 60 m sur une ligne droite de 6,6 km.
            points.append((6.0 + alea.gauss(0, bruit),
                           49.0 + i * 0.0001 + alea.gauss(0, bruit)))
            altitudes.append(200 + i * 0.1 + alea.gauss(0, 1.5))
        return points, altitudes

    def test_ne_compte_pas_le_tremblement_comme_de_la_distance(self):
        points, altitudes = self.marche_bruitee()
        trace = lis(gpx(points, altitudes=altitudes))
        # La ligne droite fait 6,66 km : le bruit ne doit pas la rallonger
        # de plus de quelques pour cent.
        assert trace.km == pytest.approx(6.66, rel=0.08)

    def test_ne_compte_pas_le_bruit_vertical_comme_du_denivele(self):
        points, altitudes = self.marche_bruitee()
        trace = lis(gpx(points, altitudes=altitudes))
        # 60 m de montee reelle, et non les centaines qu'un cumul naif rend.
        assert 45 <= trace.montee <= 80

    def test_ne_raccourcit_pas_une_trace_propre(self):
        """Le debruitage ne doit pas se payer sur les traces nettes : moins de
        5 % d'ecart, sinon on ment dans l'autre sens."""
        propre = [(6.0, 49.0 + i * 0.0002) for i in range(300)]
        trace = lis(gpx(propre, altitudes=[200.0] * 300))
        assert trace.km == pytest.approx(6.66, rel=0.05)

    def test_garde_le_dernier_point_de_la_trace(self):
        """Le filtrage par pas minimum ne doit pas raboter la fin de la
        boucle : sinon une boucle ne se referme plus."""
        points = [(6.0, 49.0), (6.0, 49.001), (6.0, 49.0010001)]
        assert lis(gpx(points)).troncons[0][-1] == points[-1]
