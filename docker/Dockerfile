FROM python:3.12-slim-bookworm
COPY uv.lock pyproject.toml
COPY conf /conf
COPY bin /usr/local/bin/

RUN pip imstall uv \
    && uv sync

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
