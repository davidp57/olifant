"""Fabrique les fichiers qu'on emporte : GPX pour la montre ou le telephone,
KML pour Google My Maps et Google Earth.

Le GPX est du 1.1 standard, avec l'altitude sur chaque point : c'est ce
qu'attend Iphigenie pour afficher une trace a suivre et un profil. Les etapes
y sont aussi comme points de passage nommes, avec leur note.
"""

from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

from .modele import Parcours, Point, Trace


def _description(parcours: Parcours, trace: Trace) -> str:
    morceaux = ["%.1f km" % trace.km, "D+ %d m" % round(trace.montee),
                "%d %% de chemins" % round(trace.part("chemin"))]
    if parcours.acces == "voiture" and parcours.parking:
        morceaux.append("Depart : " + parcours.parking)
    if parcours.resume:
        morceaux.append(parcours.resume)
    return ". ".join(morceaux)


def gpx(parcours: Parcours, trace: Trace, points: dict[str, Point]) -> str:
    lignes = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="olifant"',
        '     xmlns="http://www.topografix.com/GPX/1/1"',
        '     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"',
        '     xsi:schemaLocation="http://www.topografix.com/GPX/1/1'
        ' http://www.topografix.com/GPX/1/1/gpx.xsd">',
        "  <metadata><name>%s</name><desc>%s</desc></metadata>"
        % (escape(parcours.nom), escape(_description(parcours, trace))),
    ]
    for cle in dict.fromkeys(parcours.etapes):
        p = points[cle]
        lignes.append(
            '  <wpt lat="%.7f" lon="%.7f"><name>%s</name>%s</wpt>'
            % (p.lat, p.lon, escape(p.nom),
               "<desc>%s</desc>" % escape(p.note) if p.note else ""))
    lignes.append("  <trk><name>%s</name><trkseg>" % escape(parcours.nom))
    for lon, lat, alt in trace.points:
        lignes.append('    <trkpt lat="%.7f" lon="%.7f"><ele>%.1f</ele></trkpt>'
                      % (lat, lon, alt))
    lignes.append("  </trkseg></trk>")
    lignes.append("</gpx>")
    return "\n".join(lignes)


ICONE = "http://maps.google.com/mapfiles/kml/paddle/%s.png"
STYLES = (
    '  <Style id="depart"><IconStyle><scale>1.2</scale>'
    "<Icon><href>%s</href></Icon></IconStyle></Style>\n" % (ICONE % "grn-circle")
    + '  <Style id="etape"><IconStyle>'
    "<Icon><href>%s</href></Icon></IconStyle></Style>" % (ICONE % "wht-blank")
)


def _placemarks(parcours: Parcours, trace: Trace, points: dict[str, Point],
                indice: int) -> list[str]:
    sortie, rang = [], 0
    for cle in dict.fromkeys(parcours.etapes):
        p = points[cle]
        depart = cle == parcours.etapes[0]
        if depart:
            titre, style = "Depart : " + p.nom, "#depart"
        else:
            rang += 1
            titre, style = "%d. %s" % (rang, p.nom), "#etape"
        sortie.append(
            "    <Placemark><name>%s</name><description>%s</description>"
            "<styleUrl>%s</styleUrl><Point><coordinates>%.7f,%.7f,0</coordinates>"
            "</Point></Placemark>" % (escape(titre), escape(p.note), style, p.lon, p.lat))
    sortie.append(
        '    <Style id="t%d"><LineStyle><color>ff%s</color><width>4</width>'
        "</LineStyle></Style>" % (indice, parcours.couleur))
    coords = " ".join("%.7f,%.7f,%.0f" % (lon, lat, alt) for lon, lat, alt in trace.points)
    sortie.append(
        "    <Placemark><name>%s</name><description>%s</description>"
        '<styleUrl>#t%d</styleUrl><LineString><tessellate>1</tessellate>'
        "<coordinates>%s</coordinates></LineString></Placemark>"
        % (escape(parcours.nom), escape(_description(parcours, trace)), indice, coords))
    return sortie


def kml(parcours: Parcours, trace: Trace, points: dict[str, Point]) -> str:
    corps = _placemarks(parcours, trace, points, 1)
    return _document(parcours.nom, _description(parcours, trace), corps)


def kml_complet(elements: list[tuple[Parcours, Trace]], points: dict[str, Point],
                titre: str, accroche: str) -> str:
    """Un seul KML avec toutes les randos, une par dossier."""
    corps = []
    for indice, (parcours, trace) in enumerate(elements, 1):
        corps.append("  <Folder><name>%s</name><description>%s</description>"
                     % (escape(parcours.nom), escape(_description(parcours, trace))))
        corps.extend(_placemarks(parcours, trace, points, indice))
        corps.append("  </Folder>")
    return _document(titre, accroche, corps)


def _document(nom: str, description: str, corps: list[str]) -> str:
    return "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
        "  <name>%s</name><description>%s</description>" % (escape(nom), escape(description)),
        STYLES, *corps, "</Document></kml>",
    ])


def geojson(parcours: Parcours, trace: Trace) -> dict:
    """La trace au format que la carte du site consomme directement."""
    return {
        "type": "Feature",
        "properties": {"id": parcours.id, "nom": parcours.nom,
                       "couleur": "#" + parcours.couleur},
        "geometry": {"type": "LineString",
                     "coordinates": [[round(lon, 6), round(lat, 6), round(alt)]
                                     for lon, lat, alt in trace.points]},
    }
