# valcoach web app. Ollama stays on the host (it needs the GPU); see docker-compose.yml.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# runtime library for OpenCV (headless build, no libGL needed)
RUN apt-get update \
 && apt-get install -y --no-install-recommends libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

# Run as a normal user. Match UID/GID to the owner of your data folder (`id -u`, `id -g`).
ARG UID=1000
ARG GID=1000
RUN groupadd --gid ${GID} valcoach && useradd --uid ${UID} --gid ${GID} --create-home valcoach

WORKDIR /app
COPY pyproject.toml README.md CHANGELOG.md ./
COPY valcoach ./valcoach
RUN pip install .

USER valcoach
VOLUME ["/data"]
EXPOSE 10070

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:10070/login', timeout=4)" || exit 1

CMD ["valcoach", "web", "--host", "0.0.0.0", "--port", "10070", "--data", "/data"]
