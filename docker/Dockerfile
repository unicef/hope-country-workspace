FROM python:3.12-slim-bookworm as python_base

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
RUN pip install uwsgi uv


COPY docker/conf /conf/
COPY docker/bin /usr/local/bin/

WORKDIR /app
COPY . /app/

RUN uv venv \
    && uv sync --no-dev --no-editable --frozen \
    && uv pip install . \
    && ls -al /app/.venv/

FROM python_base


FROM python_base
ENV PATH=/app/.venv/bin:$PATH

COPY docker/conf /conf/
COPY docker/bin /usr/local/bin/
COPY --chown=user:app --from=builder /app/.venv /app/.venv


EXPOSE 8000
ENTRYPOINT exec docker-entrypoint.sh "$0" "$@"
CMD ["run"]

LABEL distro="final"
LABEL maintainer="hope@unicef.org"
LABEL org.opencontainers.image.authors="hope@unicef.org"
LABEL org.opencontainers.image.created="$BUILD_DATE"
LABEL org.opencontainers.image.description="Hope Country Workspace"
LABEL org.opencontainers.image.documentation="https://github.com/unicef/hope-country-workspace/"
LABEL org.opencontainers.image.licenses="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/blob/${SOURCE_COMMIT:-master}/LICENSE"
LABEL org.opencontainers.image.revision=$SOURCE_COMMIT
LABEL org.opencontainers.image.source="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/tree/${SOURCE_COMMIT:-master}/"
LABEL org.opencontainers.image.title="Hope Country Workspace"
LABEL org.opencontainers.image.version="$VERSION"
#LABEL org.opencontainers.image.url="https://app.io/"
#LABEL org.opencontainers.image.vendor="App ltd"
