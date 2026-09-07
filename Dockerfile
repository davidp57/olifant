# Olifant, en une image.
#
# L'image contient le code et les traces deja calculees ; le volume /data
# contient ce qui s'ecrit apres coup : le carnet de sorties et les traces
# reellement suivies. Sauvegarder le NAS suffit donc a tout sauvegarder,
# et une mise a jour de l'image ne touche a rien de ce qui a ete note.

FROM python:3.13-slim

# OLIFANT_TUILES_AUTO : au premier demarrage, le service complete le fond de
# carte des traces -- un millier de carreaux, un quart d'heure, en tache de
# fond, une seule fois, puisqu'ils restent ensuite dans le volume. Mettre a 0
# pour s'en passer. Hors conteneur la variable n'est pas posee : un `uvicorn`
# lance sur un poste de developpement ne telecharge donc rien.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OLIFANT_DATA=/data \
    OLIFANT_TUILES_AUTO=1

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.30" \
        "pyyaml>=6" "python-multipart>=0.0.9" "defusedxml>=0.7"

COPY olifant/ ./olifant/
COPY data/parcours.yaml ./data/parcours.yaml
COPY data/sortie/ ./data/sortie/

# Le service tourne sans privileges : il n'ecrit que dans /data.
RUN useradd --system --uid 1001 marcheur \
    && mkdir -p /data/traces /data/tuiles \
    && chown -R marcheur:marcheur /data
USER marcheur

EXPOSE 8137
HEALTHCHECK --interval=60s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8137/api/parcours', timeout=4)"

CMD ["uvicorn", "olifant.api:app", "--host", "0.0.0.0", "--port", "8137"]
