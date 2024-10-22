FROM python:3.12-slim-bookworm AS python_base
ARG GOSU_VERSION=1.17
ARG GOSU_SHA256=bbc4136d03ab138b1ad66fa4fc051bafc6cc7ffae632b069a53657279a450de3


RUN set -x \
  && runtimeDeps=" \
    libxml2 \
  " \
  && buildDeps=" \
wget \
" \
  && apt-get update && apt-get install -y --no-install-recommends ${buildDeps} ${runtimeDeps} \
  && rm -rf /var/lib/apt/lists/* \
  && wget --quiet -O /usr/local/bin/gosu "https://github.com/tianon/gosu/releases/download/$GOSU_VERSION/gosu-amd64" \
  && echo "$GOSU_SHA256 /usr/local/bin/gosu" | sha256sum --check --status \
  && chmod +x /usr/local/bin/gosu \
  && apt-get purge -y --auto-remove $buildDeps

RUN groupadd --gid 1024 app \
    && adduser --disabled-login --disabled-password --no-create-home --ingroup app -q user


# ------- builder -------
FROM python_base AS builder
RUN set -x \
    && buildDeps="build-essential \
cmake \
curl \
gcc \
git \
libssl-dev \
libxml2-dev  \
python3-dev \
zlib1g-dev  \
" \
    && apt-get update \
    && apt-get install -y --no-install-recommends $buildDeps \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
RUN pip install uv

#COPY AUTHORS LICENSE README.md MANIFEST.in /app/

WORKDIR /app
RUN --mount=type=cache,target=/root/.uv-cache \
    --mount=type=bind,source=uv.lock,target=/app/uv.lock \
    --mount=type=bind,source=pyproject.toml,target=/app/pyproject.toml \
    --mount=type=bind,source=MANIFEST.in,target=/app/MANIFEST.in \
    --mount=type=bind,source=./src/country_workspace,target=/app/src/country_workspace \
    uv sync --cache-dir=/root/.uv-cache --no-dev --no-editable --frozen --extra distribution


# ------- tests -------
FROM builder AS tests
ARG BUILD_DATE
ARG VERSION

LABEL distro="tests"
LABEL org.opencontainers.image.created="$BUILD_DATE"
LABEL org.opencontainers.image.version="$VERSION"

ENV PATH=/app/.venv/bin:/usr/local/bin/:/usr/bin:/bin \
    DJANGO_SETTINGS_MODULE=country_workspace.config.settings \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=""\
    UWSGI_PROCESSES=4
WORKDIR /app
RUN --mount=type=cache,target=/root/.uv-cache \
    --mount=type=bind,source=uv.lock,target=/app/uv.lock \
    --mount=type=bind,source=pyproject.toml,target=/app/pyproject.toml \
    --mount=type=bind,source=MANIFEST.in,target=/app/MANIFEST.in \
    --mount=type=bind,source=./src/country_workspace,target=/app/src/country_workspace \
    uv sync --cache-dir=/root/.uv-cache --no-editable --frozen --extra distribution

# ------- production only deps-------
FROM builder AS production
ENV PATH=/app/.venv/bin:/usr/local/bin/:/usr/bin:/bin \
    DJANGO_SETTINGS_MODULE=country_workspace.config.settings \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=""\
    UWSGI_PROCESSES=4
WORKDIR /app

RUN --mount=type=cache,target=/root/.uv-cache \
    --mount=type=bind,source=uv.lock,target=/app/uv.lock \
    --mount=type=bind,source=pyproject.toml,target=/app/pyproject.toml \
    --mount=type=bind,source=MANIFEST.in,target=/app/MANIFEST.in \
    --mount=type=bind,source=./src/country_workspace,target=/app/src/country_workspace \
    uv sync --cache-dir=/root/.uv-cache --no-dev --no-editable --frozen --extra distribution

# ------- dist -------
FROM python_base AS dist
ARG BUILD_DATE
ARG VERSION
ARG GIT_SHA

ENV PATH=/app/.venv/bin:/usr/local/bin/:/usr/bin:/bin \
    DJANGO_SETTINGS_MODULE=country_workspace.config.settings \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STATIC_URL="/static/" \
    PYTHONPATH=""\
    PGSSLCERT="/tmp/postgresql.crt" \
    UWSGI_PROCESSES=4

RUN <<EOF cat> /RELEASE
{"version": "$VERSION",
 "commit": "$GIT_SHA",
 "date": "$BUILD_DATE",
}
EOF
WORKDIR /app
COPY docker/conf /conf/
COPY docker/bin/* /usr/local/bin/
COPY AUTHORS LICENSE README.md /
COPY --chown=user:app --from=production /app/.venv /app/.venv

EXPOSE 8000
ENTRYPOINT exec docker-entrypoint.sh "$0" "$@"
CMD ["run"]

LABEL maintainer="hope@unicef.org"
LABEL org.opencontainers.image.authors="hope@unicef.org"
LABEL org.opencontainers.image.description="Hope Country Workspace"
LABEL org.opencontainers.image.documentation="https://github.com/unicef/hope-country-workspace/"
LABEL org.opencontainers.image.title="Hope Country Workspace"
LABEL org.opencontainers.image.licenses="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/blob/${GIT_SHA:-master}/LICENSE"
LABEL org.opencontainers.image.revision=$GIT_SHA
LABEL org.opencontainers.image.source="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/tree/${GIT_SHA:-master}/"
LABEL org.opencontainers.image.url="https://hub.docker.com/repository/docker/unicef/hope-country-workspace/tags/"
LABEL org.opencontainers.image.vendor="UNICEF"
LABEL org.opencontainers.image.created="$BUILD_DATE"
LABEL org.opencontainers.image.version="$VERSION"
