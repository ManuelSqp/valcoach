# nexus web app. Ollama stays on the host (it needs the GPU); see docker-compose.yml.

# vrfkit reads the game's replay files (.vrf), see nexus/replayfile.py. Built from a pinned commit;
# to update it, change VRFKIT_REF to a newer commit of https://github.com/yakisoba0728/vrfkit.
FROM rust:1.86-slim-bookworm AS vrfkit
ARG VRFKIT_REF=b9ba3f70735c7219fef41ba61a80626a4bb88757
ADD https://github.com/yakisoba0728/vrfkit/archive/${VRFKIT_REF}.tar.gz /tmp/vrfkit.tar.gz
RUN mkdir /src && tar -xzf /tmp/vrfkit.tar.gz -C /src --strip-components=1 \
 && cd /src && cargo build --release --locked -p vrfkit \
 && cp target/release/vrfkit /usr/local/bin/vrfkit

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
RUN groupadd --gid ${GID} nexus && useradd --uid ${UID} --gid ${GID} --create-home nexus

COPY --from=vrfkit /usr/local/bin/vrfkit /usr/local/bin/vrfkit

WORKDIR /app
COPY pyproject.toml README.md CHANGELOG.md ./
COPY nexus ./nexus
RUN pip install .

USER nexus
VOLUME ["/data"]
EXPOSE 10070

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:10070/login', timeout=4)" || exit 1

CMD ["nexus", "web", "--host", "0.0.0.0", "--port", "10070", "--data", "/data"]
