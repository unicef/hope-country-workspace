FROM python:3.12-slim-bookworm AS base_os

RUN set -x \
  && runtimeDeps="libmagic1 libxml2 tini" \
  && apt-get update && apt-get install -y --no-install-recommends $runtimeDeps \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1024 unicef \
    && adduser --disabled-login --disabled-password --no-create-home --ingroup unicef -q hope


# ------- builder -------
FROM base_os AS builder

RUN set -x \
    && buildDeps="build-essential cmake curl gcc git libfontconfig1 libgconf-2-4 libglib2.0-0 libnss3 libssl-dev libxml2-dev python3-dev zlib1g-dev" \
    && runtimeDeps="gnupg wget curl unzip" \
    && apt-get update \
    && apt-get install -y --no-install-recommends $buildDeps $runtimeDeps \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google.list \
    && apt-get update -y \
    && apt-get install -y --no-install-recommends google-chrome-stable \
    && CHROME_VERSION=$(google-chrome --product-version) \
    && wget -q --continue -P /chromedriver "https://edgedl.me.gvt1.com/edgedl/chrome/chrome-for-testing/$CHROME_VERSION/linux64/chromedriver-linux64.zip" \
    && unzip /chromedriver/chromedriver* -d /usr/local/bin/ \
    && apt-get purge -y --auto-remove $runtimeDeps \
    && apt-get clean && rm -rf /var/lib/apt/lists/* /var/cache/apt/* /chromedriver

RUN pip install uv uwsgi

# ------- tests -------
FROM builder AS tests
ARG BUILD_DATE
ARG GIT_SHA
ARG VERSION

LABEL distro="tests"
LABEL org.opencontainers.image.created="$BUILD_DATE"
LABEL org.opencontainers.image.version="$VERSION"

ENV PATH=/venv/bin:/usr/local/bin/:/usr/bin:/bin \
    DJANGO_SETTINGS_MODULE=country_workspace.config.settings \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/venv \
    VIRTUAL_ENV=/venv \
    UWSGI_PROCESSES=4

WORKDIR /app
COPY uv.lock README.md MANIFEST.in pyproject.toml /app/
COPY src /app/src/

RUN --mount=type=cache,target=/root/.uv-cache \
    find ../src -name 'node_modules' -prune \
        -o -name *.py -o -name *.html -o -name *.js -o -name *.css \
        -type f \
        -exec ls -l "{}" \;  | sha1sum | awk '{print $1}' > CODE_CHECKSUM \
    && uv sync --cache-dir=/root/.uv-cache \
        --python=/usr/local/bin/python \
        --python-preference=system \
        --frozen

# ------- production only deps-------
FROM builder AS production
ENV PATH=/venv/bin:/usr/local/bin/:/usr/bin:/bin \
    DJANGO_SETTINGS_MODULE=country_workspace.config.settings \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/venv \
    VIRTUAL_ENV=/venv \
    UWSGI_PROCESSES=4

WORKDIR /app
COPY uv.lock README.md MANIFEST.in pyproject.toml /app/
COPY src /app/src/

RUN --mount=type=cache,target=/root/.uv-cache \
    uv sync --cache-dir=/root/.uv-cache \
        --python=/usr/local/bin/python \
        --python-preference=system \
        --no-dev --frozen --extra distribution



# ------- dist -------
FROM base_os AS dist
ARG BUILD_DATE
ARG GIT_SHA
ARG BRANCH
ARG VERSION
ARG GITHUB_SERVER_URL
ARG GITHUB_REPOSITORY

ENV PATH=/venv/bin:/usr/local/bin/:/usr/bin:/bin \
    DJANGO_SETTINGS_MODULE=country_workspace.config.settings \
    BUILD_DATE=$BUILD_DATE \
    GIT_SHA=$GIT_SHA \
    VERSION=$VERSION \
    BRANCH=$BRANCH \
    PYTHONUNBUFFERED=1 \
    STATIC_URL="/static/" \
    PYTHONPATH=""\
    PGSSLCERT="/tmp/postgresql.crt" \
    UV_PROJECT_ENVIRONMENT=/venv \
    VIRTUAL_ENV=/venv \
    UWSGI_PROCESSES=4 \
    MEDIA_ROOT="${MEDIA_ROOT:-/var/run/app/media}" \
    STATIC_ROOT="${STATIC_ROOT:-/var/run/app/static}"

RUN <<EOF cat> /RELEASE
{"version": "$VERSION",
 "commit": "$GIT_SHA",
 "date": "$BUILD_DATE",
}
EOF
WORKDIR /app
COPY docker/conf /conf/
COPY docker/bin/* /usr/local/bin/

COPY . /app/

COPY --chown=hope:unicef --from=production /venv /venv
COPY --from=builder /usr/local/bin/uwsgi /usr/local/bin/uv /usr/local/bin/
RUN --mount=type=cache,target=/root/.uv-cache \
    uv --cache-dir=/root/.uv-cache  pip install --no-deps . \
    && rm -fr /app/*

RUN mkdir -p /var/run/app/media /var/run/app/static \
    && chown -R hope:unicef /var/run/app/media /var/run/app/static

USER hope:unicef
WORKDIR /app

EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
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
