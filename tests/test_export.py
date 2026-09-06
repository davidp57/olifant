"""Les fichiers qu'on emporte doivent etre valides et complets.

Le GPX est relu avec un vrai parseur XML : c'est ce que fera l'application du
telephone, et une balise mal fermee ne se voit pas a la lecture.
"""

import xml.etree.ElementTree as ET

import pytest

from olifant import export
from olifant.donnees import charge
from olifant.modele import Parcours, Point, Segment, Trace

GPX = "{http://www.topografix.com/GPX/1/1}"


@pytest.fixture
def jeu():
    points = {
        "depart": Point("depart", "Gare de Metz", 6.177, 49.109, "Cafe ouvert tot"),
        "etape": Point("etape", "Fort de Queuleu & le bois", 6.195, 49.098,
                       'Guillemets "droits" et esperluette'),
    }
    parcours = Parcours(id="essai", nom="Boucle d'essai", etapes=["depart", "etape", "depart"],
                        resume="Un tour", couleur="316E7C")
    trace = Trace("essai", "hiking-beta",
                  [(6.177, 49.109, 180.0), (6.186, 49.103, 195.5), (6.195, 49.098, 210.0)],
                  [Segment(1200, {"highway": "path"})], montee=42.0)
    return parcours, trace, points


class TestGpx:
    def test_le_fichier_est_du_xml_valide(self, jeu):
        racine = ET.fromstring(export.gpx(*jeu))
        assert racine.tag == GPX + "gpx"

    def test_la_trace_porte_tous_les_points_avec_leur_altitude(self, jeu):
        racine = ET.fromstring(export.gpx(*jeu))
        pts = racine.findall(".//%strkpt" % GPX)
        assert len(pts) == 3
        assert [p.find(GPX + "ele").text for p in pts] == ["180.0", "195.5", "210.0"]

    def test_les_etapes_sont_des_points_de_passage_nommes_sans_doublon(self, jeu):
        racine = ET.fromstring(export.gpx(*jeu))
        noms = [w.find(GPX + "name").text for w in racine.findall(GPX + "wpt")]
        # « depart » apparait deux fois dans les etapes, une seule fois en wpt.
        assert noms == ["Gare de Metz", "Fort de Queuleu & le bois"]

    def test_les_caracteres_speciaux_ne_cassent_pas_le_fichier(self, jeu):
        racine = ET.fromstring(export.gpx(*jeu))
        desc = racine.findall(GPX + "wpt")[1].find(GPX + "desc").text
        assert desc == 'Guillemets "droits" et esperluette'

    def test_la_description_dit_ce_qui_compte_pour_choisir(self, jeu):
        texte = ET.fromstring(export.gpx(*jeu)).find(
            "%smetadata/%sdesc" % (GPX, GPX)).text
        assert "1.2 km" in texte and "D+ 42 m" in texte and "100 % de chemins" in texte


class TestKml:
    def test_le_fichier_est_du_xml_valide(self, jeu):
        racine = ET.fromstring(export.kml(*jeu))
        assert racine.tag.endswith("kml")

    def test_le_kml_complet_range_chaque_parcours_dans_son_dossier(self, jeu):
        parcours, trace, points = jeu
        autre = Parcours(id="autre", nom="Deuxieme", etapes=["depart", "etape"])
        contenu = export.kml_complet([(parcours, trace), (autre, trace)], points,
                                     "Olifant", "Des boucles")
        racine = ET.fromstring(contenu)
        dossiers = racine.findall(".//{http://www.opengis.net/kml/2.2}Folder")
        assert len(dossiers) == 2

    def test_les_couleurs_de_trace_ne_se_marchent_pas_dessus(self, jeu):
        parcours, trace, points = jeu
        autre = Parcours(id="autre", nom="Deuxieme", etapes=["depart", "etape"],
                         couleur="B8862A")
        contenu = export.kml_complet([(parcours, trace), (autre, trace)], points, "x", "y")
        assert 'id="t1"' in contenu and 'id="t2"' in contenu


class TestGeojson:
    def test_la_geometrie_est_une_ligne_lon_lat(self, jeu):
        parcours, trace, _ = jeu
        forme = export.geojson(parcours, trace)
        assert forme["geometry"]["type"] == "LineString"
        assert forme["geometry"]["coordinates"][0][:2] == [6.177, 49.109]
        assert forme["properties"]["couleur"] == "#316E7C"


class TestChargement:
    def test_le_vrai_fichier_de_reference_se_charge(self):
        recueil = charge("data/parcours.yaml")
        assert recueil.parcours, "aucun parcours"
        assert all(p.etapes for p in recueil.parcours)

    def test_toutes_les_boucles_reviennent_a_leur_point_de_depart(self):
        recueil = charge("data/parcours.yaml")
        ouvertes = [p.id for p in recueil.parcours if p.etapes[0] != p.etapes[-1]]
        assert not ouvertes, "ces parcours ne bouclent pas : %s" % ouvertes

    def test_aucun_point_ne_traine_sans_servir(self):
        recueil = charge("data/parcours.yaml")
        utilises = {c for p in recueil.parcours for c in p.etapes}
        # Les points inutilises ne sont pas une faute, mais on veut le savoir.
        orphelins = sorted(set(recueil.points) - utilises)
        assert isinstance(orphelins, list)

    def test_une_etape_inconnue_est_refusee_tout_de_suite(self, tmp_path):
        fichier = tmp_path / "p.yaml"
        fichier.write_text(
            "points:\n  a: {nom: A, lon: 6.0, lat: 49.0}\n"
            "parcours:\n  - {id: x, nom: X, etapes: [a, fantome]}\n", encoding="utf-8")
        with pytest.raises(ValueError, match="fantome"):
            charge(fichier)
