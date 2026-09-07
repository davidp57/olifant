"""Ce que la page embarque et qu'on ne verrait pas en la relisant.

Un fichier HTML n'a pas de tests unitaires, mais certaines de ses constantes
sont des donnees binaires encodees, illisibles a l'oeil : c'est exactement la
ou une erreur peut vivre longtemps sans se faire remarquer.
"""

import base64
import re
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parent.parent / "olifant" / "web" / "index.html"
SERVICE_WORKER = PAGE.parent / "sw.js"


@pytest.fixture(scope="module")
def source():
    return PAGE.read_text(encoding="utf-8")


class TestCarreauVide:
    """Le carreau que la carte pose la ou le fond emporte n'a rien.

    Il est empile au-dessus de la couche d'OpenStreetMap : s'il n'est pas
    transparent, il la masque. C'est arrive -- le carreau valait un pixel
    blanc opaque, et la carte apparaissait trouee de blanc partout hors du
    couloir des parcours, sans qu'aucun carreau ne tombe en erreur.
    """

    @pytest.fixture
    def octets(self, source):
        motif = r'const TRANSPARENT = "data:image/gif;base64,"\s*\+\s*"([A-Za-z0-9+/=]+)"'
        trouve = re.search(motif, source)
        assert trouve, "la constante TRANSPARENT a change de forme"
        return base64.b64decode(trouve.group(1))

    def test_est_un_gif_d_un_pixel(self, octets):
        assert octets[:6] == b"GIF89a"
        assert int.from_bytes(octets[6:8], "little") == 1
        assert int.from_bytes(octets[8:10], "little") == 1

    def test_declare_une_couleur_transparente(self, octets):
        """Le bloc de controle graphique, sans lequel un GIF est opaque."""
        debut = octets.find(b"\x21\xf9")
        assert debut >= 0, "pas de bloc de controle graphique : le carreau est opaque"
        drapeaux = octets[debut + 3]
        assert drapeaux & 1, "le drapeau de transparence n'est pas leve"

    def test_l_indice_transparent_existe_dans_la_palette(self, octets):
        debut = octets.find(b"\x21\xf9")
        indice = octets[debut + 6]
        # Table globale de couleurs : sa taille tient dans les trois bits bas
        # de l'octet de drapeaux de l'ecran logique.
        couleurs = 2 ** ((octets[10] & 0b111) + 1)
        assert indice < couleurs


class TestConstantesDeLaPage:
    def test_la_version_est_un_jeton_a_remplacer(self, source):
        """Le serveur y injecte la version ; si le jeton disparait, la page ne
        sait plus dire d'ou elle vient."""
        assert 'data-version="__VERSION__"' in source

    def test_le_service_worker_porte_aussi_son_jeton(self):
        assert '"__VERSION__"' in SERVICE_WORKER.read_text(encoding="utf-8")

    def test_les_ressources_sont_servies_localement(self, source):
        """Aucun CDN : le site doit marcher quand le NAS est seul joignable.
        Seules les tuiles peuvent venir d'OpenStreetMap."""
        externes = set(re.findall(r'(?:src|href)="(https?://[^"]+)"', source))
        for url in externes:
            assert "openstreetmap.org" in url, "ressource externe inattendue : %s" % url

    def test_l_etat_des_filtres_est_pose_au_rendu(self, source):
        """Il ne l'etait qu'au chargement : le filtre s'appliquait mais le
        bouton restait eteint jusqu'au rechargement de la page."""
        rendu = source[source.index("function rendre()"):]
        rendu = rendu[:rendu.index("\nfunction ")]
        assert "data-filtre" in rendu and "aria-pressed" in rendu


class TestCapVersLEtape:
    """Le relevement affiche pendant la marche.

    La formule vit dans la page ; on la reimplemente ici pour verifier qu'elle
    donne les valeurs attendues sur des cas dont la reponse est connue
    d'avance -- plein nord, plein est, et deux vraies etapes du carnet.
    """

    @staticmethod
    def cap(depuis, vers):
        import math
        dlon = math.radians(vers[0] - depuis[0])
        lat1, lat2 = math.radians(depuis[1]), math.radians(vers[1])
        y = math.sin(dlon) * math.cos(lat2)
        x = (math.cos(lat1) * math.sin(lat2)
             - math.sin(lat1) * math.cos(lat2) * math.cos(dlon))
        return (math.degrees(math.atan2(y, x)) + 360) % 360

    @pytest.mark.parametrize("vers,attendu", [
        ((6.0, 50.0), 0),      # plein nord
        ((7.0, 49.0), 90),     # plein est, a l'equateur de notre latitude pres
        ((6.0, 48.0), 180),    # plein sud
        ((5.0, 49.0), 270),    # plein ouest
    ])
    def test_les_quatre_aires_cardinales(self, vers, attendu):
        assert self.cap((6.0, 49.0), vers) == pytest.approx(attendu, abs=1.0)

    def test_le_cap_est_dans_la_page(self, source):
        """Si la fonction disparait ou change de nom, ce test le dit."""
        assert "function capVers(" in source
        assert "Math.atan2" in source

    def test_deux_etapes_reelles(self):
        """De la gare de Metz au fort de Queuleu : au sud-est."""
        gare, fort = (6.177013, 49.109277), (6.195434, 49.098452)
        c = self.cap(gare, fort)
        assert 120 < c < 150, "attendu vers le sud-est, obtenu %.0f" % c

    def test_le_cap_inverse_est_a_180_degres(self):
        """A un degre pres : sur un grand cercle les meridiens convergent, et
        l'aller et le retour ne sont pas exactement opposes."""
        gare, fort = (6.177013, 49.109277), (6.195434, 49.098452)
        aller, retour = self.cap(gare, fort), self.cap(fort, gare)
        assert abs(abs(aller - retour) - 180) < 1
