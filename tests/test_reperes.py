"""Le tri des reperes OSM par etape, sans jamais appeler Overpass.

On fabrique des reponses Overpass a la main : c'est la partie qui peut se
tromper -- rattacher un banc a la mauvaise etape, compter deux fois la meme
fontaine, nommer « sans nom » une chose qu'OSM decrit tres bien.
"""

import pytest

from olifant.modele import Point
from olifant.reperes import RAYON_M, Sonde, ErreurOverpass, range_par_etape, requete


def point(cle, lon, lat):
    return Point(cle=cle, nom=cle.capitalize(), lon=lon, lat=lat)


def noeud(id_, lon, lat, **tags):
    return {"type": "node", "id": id_, "lon": lon, "lat": lat, "tags": tags}


ETAPES = {"gare": point("gare", 6.177013, 49.109277),
          "fort": point("fort", 6.195434, 49.098452)}


class TestRequete:
    def test_demande_autour_de_chaque_etape(self):
        corps = requete(list(ETAPES.values()))
        assert corps.count("around:%d" % RAYON_M) >= 2 * len(ETAPES)
        assert "6.177013" not in corps or "49.109277,6.177013" in corps
        # Overpass veut lat,lon dans cet ordre : l'inverser deplace la
        # recherche a des centaines de kilometres, sans erreur visible.
        assert "around:400,49.109277,6.177013" in corps

    def test_groupe_les_valeurs_d_une_meme_cle(self):
        """Un filtre par cle OSM, pas un par valeur : la requete reste courte."""
        corps = requete([point("x", 6.0, 49.0)])
        assert '["historic"~"^(castle|ruins|fort|monument|memorial|' in corps

    def test_demande_le_centre_des_contours(self):
        # Un chateau est souvent un polygone : sans `out center`, il n'a pas
        # de coordonnees et disparait du releve.
        assert requete([point("x", 6.0, 49.0)]).endswith("out center tags;")


class TestRangement:
    def test_attribue_chaque_repere_a_l_etape_la_plus_proche(self):
        reponse = {"elements": [
            noeud(1, 6.1772, 49.1094, amenity="drinking_water"),
            noeud(2, 6.1955, 49.0985, historic="fort", name="Fort de Queuleu"),
        ]}
        par_etape = range_par_etape(reponse, ETAPES)

        assert set(par_etape) == {"gare", "fort"}
        assert par_etape["gare"][0]["nom"] == "Point d'eau"
        assert par_etape["fort"][0]["nom"] == "Fort de Queuleu"

    def test_ecarte_ce_qui_est_trop_loin_de_toute_etape(self):
        """Overpass rend une liste plate : un repere du voisinage d'une autre
        boucle ne doit pas s'inviter dans celle-ci."""
        reponse = {"elements": [noeud(1, 6.30, 49.30, amenity="cafe", name="Loin")]}
        assert range_par_etape(reponse, ETAPES) == {}

    def test_ne_compte_qu_une_fois_le_noeud_et_son_contour(self):
        """OSM decrit souvent une chose deux fois : un point et sa surface."""
        reponse = {"elements": [
            noeud(1, 6.1955, 49.0985, historic="fort", name="Fort de Queuleu"),
            {"type": "way", "id": 2, "center": {"lon": 6.19551, "lat": 49.09851},
             "tags": {"historic": "fort", "name": "Fort de Queuleu"}},
        ]}
        assert len(range_par_etape(reponse, ETAPES)["fort"]) == 1

    def test_classe_l_eau_avant_le_reste(self):
        """En marchant, une fontaine compte plus qu'un panorama, et un
        panorama plus que des toilettes : l'ordre de la liste est celui de
        l'utilite, pas celui d'Overpass."""
        reponse = {"elements": [
            noeud(1, 6.1770, 49.1092, amenity="toilets"),
            noeud(2, 6.1771, 49.1093, amenity="drinking_water"),
            noeud(3, 6.1772, 49.1094, tourism="viewpoint", name="Belvedere"),
        ]}
        genres = [r["genre"] for r in range_par_etape(reponse, ETAPES)["gare"]]
        assert genres == ["eau", "vue", "commodite"]

    def test_ne_releve_ni_les_arbres_ni_les_bancs(self):
        """Mesure faite : ces deux categories representaient l'essentiel du
        volume renvoye par Overpass (jusqu'a 589 arbres et 401 bancs pour un
        seul parcours) sans rien apprendre a qui marche."""
        reponse = {"elements": [
            noeud(1, 6.1770, 49.1092, natural="tree"),
            noeud(2, 6.1771, 49.1093, amenity="bench"),
        ]}
        assert range_par_etape(reponse, ETAPES) == {}

    def test_donne_un_nom_utile_a_ce_qui_n_en_a_pas(self):
        reponse = {"elements": [
            noeud(1, 6.1770, 49.1092, natural="spring"),
            noeud(2, 6.1771, 49.1093, tourism="picnic_site"),
            noeud(3, 6.1772, 49.1094, historic="wayside_cross"),
        ]}
        noms = {r["nom"] for r in range_par_etape(reponse, ETAPES)["gare"]}
        assert noms == {"Source", "Aire de pique-nique", "Croix de chemin"}

    def test_garde_la_distance_pour_juger_du_detour(self):
        reponse = {"elements": [noeud(1, 6.1790, 49.1093, amenity="cafe", name="Le Zinc")]}
        repere = range_par_etape(reponse, ETAPES)["gare"][0]
        assert 100 < repere["distance_m"] < 200

    def test_ignore_ce_qu_on_ne_sait_pas_classer(self):
        reponse = {"elements": [noeud(1, 6.1770, 49.1092, amenity="parcel_locker")]}
        assert range_par_etape(reponse, ETAPES) == {}

    def test_ignore_un_element_sans_coordonnees(self):
        reponse = {"elements": [{"type": "relation", "id": 9,
                                 "tags": {"historic": "castle", "name": "Sans point"}}]}
        assert range_par_etape(reponse, ETAPES) == {}


class TestSonde:
    def test_relit_le_cache_sans_toucher_au_reseau(self, tmp_path):
        sonde = Sonde(tmp_path)
        corps = requete([point("x", 6.0, 49.0)])
        attendu = {"elements": [noeud(1, 6.0, 49.0, amenity="cafe", name="Cafe")]}
        # On depose la reponse comme si un appel l'avait ecrite.
        from olifant.reperes import _empreinte
        (tmp_path / ("overpass-%s.json" % _empreinte(corps))).write_text(
            __import__("json").dumps(attendu), encoding="utf-8")

        hors_ligne = Sonde(tmp_path, hors_ligne=True)
        assert hors_ligne.interroge(corps) == attendu
        assert sonde.interroge(corps) == attendu

    def test_le_mode_hors_ligne_le_dit_plutot_que_d_appeler(self, tmp_path):
        sonde = Sonde(tmp_path, hors_ligne=True)
        with pytest.raises(ErreurOverpass, match="hors ligne"):
            sonde.interroge("[out:json];out;")


class TestPlafond:
    """Un releve brut donne une vingtaine de trouvailles par etape en ville."""

    def test_ne_garde_qu_une_poignee(self):
        from olifant.reperes import PAR_ETAPE_MAX
        reponse = {"elements": [
            noeud(i, 6.1770 + i * 0.0001, 49.1092, amenity="bench" if i % 2 else "cafe",
                  name="Cafe %d" % i)
            for i in range(30)]}
        garde = range_par_etape(reponse, ETAPES)["gare"]
        assert len(garde) <= PAR_ETAPE_MAX

    def test_ne_perd_pas_la_seule_fontaine_parmi_les_cafes(self):
        """Le cas qui justifie le plafond par genre : six cafes plus proches
        ne doivent pas faire disparaitre le seul point d'eau."""
        elements = [noeud(i, 6.1770 + i * 0.00002, 49.1092, amenity="cafe",
                          name="Cafe %d" % i) for i in range(12)]
        elements.append(noeud(99, 6.1785, 49.1096, amenity="drinking_water"))
        garde = range_par_etape({"elements": elements}, ETAPES)["gare"]
        assert any(r["genre"] == "eau" for r in garde)
        assert garde[0]["genre"] == "eau"      # et en tete, car le plus utile

    def test_garde_un_de_chaque_genre_present(self):
        elements = [
            noeud(1, 6.1770, 49.1092, amenity="drinking_water"),
            noeud(2, 6.1771, 49.1093, tourism="viewpoint", name="Vue"),
            noeud(3, 6.1772, 49.1094, historic="ruins", name="Ruines"),
            noeud(4, 6.1773, 49.1095, amenity="toilets"),
        ] + [noeud(10 + i, 6.17705, 49.10921, amenity="cafe", name="C%d" % i)
             for i in range(10)]
        genres = {r["genre"] for r in range_par_etape({"elements": elements}, ETAPES)["gare"]}
        assert {"eau", "vue", "patrimoine", "commodite", "ravitaillement"} <= genres


class TestFauxAmis:
    """Le bon tag OSM sans etre la bonne chose."""

    def test_ecarte_les_abribus(self):
        """Mesure faite : les quatre « abris » releves autour du fort de
        Queuleu etaient quatre abribus sur la route qui le longe, et le parvis
        de la gare de Metz en annoncait dix-sept."""
        reponse = {"elements": [
            noeud(1, 6.1770, 49.1092, amenity="shelter",
                  shelter_type="public_transport"),
            noeud(2, 6.1771, 49.1093, amenity="shelter", highway="bus_stop"),
            noeud(3, 6.1772, 49.1094, amenity="shelter", bus="yes"),
        ]}
        assert range_par_etape(reponse, ETAPES) == {}

    def test_garde_un_vrai_abri(self):
        reponse = {"elements": [
            noeud(1, 6.1770, 49.1092, amenity="shelter",
                  shelter_type="weather_shelter"),
        ]}
        assert range_par_etape(reponse, ETAPES)["gare"][0]["genre"] == "halte"


class TestDoublons:
    def test_le_meme_objet_decrit_deux_fois_ne_compte_qu_une(self):
        """Le chateau de Hombourg apparait en noeud et en contour, a une
        trentaine de metres : il s'affichait « x2 »."""
        reponse = {"elements": [
            noeud(1, 6.1955, 49.0985, historic="castle", name="Chateau"),
            {"type": "way", "id": 2, "center": {"lon": 6.19575, "lat": 49.09855},
             "tags": {"historic": "castle", "name": "Chateau"}},
        ]}
        garde = range_par_etape(reponse, ETAPES)["fort"]
        assert len(garde) == 1
        assert "combien" not in garde[0]

    def test_deux_objets_homonymes_eloignes_sont_comptes(self):
        """Trois fontaines sans nom autour d'une meme etape : « Point d'eau x3 »
        dit quelque chose que « Point d'eau » seul ne dit pas."""
        reponse = {"elements": [
            noeud(1, 6.1770, 49.1092, amenity="drinking_water"),
            noeud(2, 6.1790, 49.1100, amenity="drinking_water"),
            noeud(3, 6.1755, 49.1085, amenity="drinking_water"),
        ]}
        garde = range_par_etape(reponse, ETAPES)["gare"]
        assert len(garde) == 1
        assert garde[0]["combien"] == 3
