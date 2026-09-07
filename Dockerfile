# Olifant, en une image.
#
# L'image contient le code, les traces deja calculees et le fond de carte qui
# les couvre ; le volume /data contient ce qui s'ecrit apres coup : le carnet
# de sorties et les traces reellement suivies. Sauvegarder le NAS suffit donc
# a tout sauvegarder, et une mise a jour de l'image ne touche a rien de ce qui
# a ete note.
#
# Le fond de carte voyage dans l'image et non dans le volume, et c'est une
# correction. Le service le telechargeait lui-meme au premier demarrage, un
# carreau par seconde pendant un quart d'heure ; or les serveurs de tuiles
# comptent par adresse IP, et celle du NAS est celle de la maison. Pendant
# qu'il preparait le hors-ligne, il faisait refuser les tuiles du navigateur
# de la personne assise a cote. C'est desormais la construction de l'image qui
# les recupere, une fois, depuis les machines de GitHub.

FROM python:3.13-slim

# OLIFANT_TUILES pointe vers le fond livre dans l'image, et non vers le
# volume : les carreaux dependent des traces, ils sont donc un produit du
# calcul comme les GPX, pas une donnee d'usage.
#
# OLIFANT_TUILES_AUTO n'est deliberement pas pose : le service ne telecharge
# rien de lui-meme. La variable existe encore pour un deploiement qui n'aurait
# pas construit son image, en connaissance de ce qu'elle coute au reseau local.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OLIFANT_DATA=/data \
    OLIFANT_TUILES=/app/data/tuiles

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.30" \
        "pyyaml>=6" "python-multipart>=0.0.9" "defusedxml>=0.7"

COPY olifant/ ./olifant/
# Le fichier de reference, les traces calculees et le fond de carte. Ce que
# .dockerignore ecarte : le cache des routeurs, le carnet, les traces suivies.
COPY data/ ./data/

# Le service tourne sans privileges : il n'ecrit que dans /data.
RUN useradd --system --uid 1001 marcheur \
    && mkdir -p /data/traces \
    && chown -R marcheur:marcheur /data
USER marcheur

# Tout en bas : le numero de version change a chaque poussee, et le placer
# plus haut invaliderait les couches d'installation a chaque fois.
ARG OLIFANT_VERSION=dev
ARG OLIFANT_CONSTRUITE=
ENV OLIFANT_VERSION=$OLIFANT_VERSION \
    OLIFANT_CONSTRUITE=$OLIFANT_CONSTRUITE

EXPOSE 8137
HEALTHCHECK --interval=60s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8137/api/parcours', timeout=4)"

CMD ["uvicorn", "olifant.api:app", "--host", "0.0.0.0", "--port", "8137"]
