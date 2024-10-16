FROM python:3.12-slim-bookworm as python_base
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

COPY pyproject.toml uv.lock AUTHORS LICENSE README.md MANIFEST.in /app/
COPY src /app/src

WORKDIR /app
RUN uv sync --no-dev --no-editable --frozen

FROM builder AS test
ENV PATH=/app/.venv/bin:$PATH \
    DJANGO_SETTINGS_MODULE=country_workspace.config.settings \
    UWSGI_PROCESSES=4
WORKDIR /app
RUN uv sync --no-editable --frozen
COPY pytest.ini /app/
COPY tests /app/tests


FROM python_base as prod
ENV PATH=/app/.venv/bin:$PATH \
    DJANGO_SETTINGS_MODULE=country_workspace.config.settings \
    UWSGI_PROCESSES=4

COPY docker/conf /conf/
COPY docker/bin/* /usr/local/bin/
COPY --chown=user:app --from=builder /app/.venv /app/.venv

EXPOSE 8000
ENTRYPOINT exec docker-entrypoint.sh "$0" "$@"
CMD ["run"]


LABEL distro="final"
LABEL maintainer="hope@unicef.org"
LABEL org.opencontainers.image.authors="hope@unicef.org"
#LABEL org.opencontainers.image.created="$BUILD_DATE"
LABEL org.opencontainers.image.description="Hope Country Workspace"
LABEL org.opencontainers.image.documentation="https://github.com/unicef/hope-country-workspace/"
LABEL org.opencontainers.image.licenses="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/blob/${SOURCE_COMMIT:-master}/LICENSE"
LABEL org.opencontainers.image.revision=$SOURCE_COMMIT
LABEL org.opencontainers.image.source="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/tree/${SOURCE_COMMIT:-master}/"
LABEL org.opencontainers.image.title="Hope Country Workspace"
LABEL org.opencontainers.image.version="$VERSION"
#LABEL org.opencontainers.image.url="https://app.io/"
#LABEL org.opencontainers.image.vendor="App ltd"
