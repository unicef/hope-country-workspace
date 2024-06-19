BUILD_DATE:=$(shell date +"%Y-%m-%d %H:%M")
CHECKSUM?=$(shell sha1sum ../pdm.lock | awk '{print $$1}')

VERSION?=0.1.0
HASH_SEEDS=pdm.lock docker/bin/* docker/conf/* docker/Dockerfile
AA=$(cd .. && sha1sum ${HASH_SEEDS})
LOCK_SHA?=$(shell cd .. && sha1sum ${HASH_SEEDS} | sha1sum | awk '{print $1}' | cut -c 1-8)

COMMIT_SHA?=$(shell git rev-parse --short HEAD)
CI_REGISTRY_IMAGE?="<set env var for this>"
CONTAINER_NAME?=hde


define PRINT_HELP_PYSCRIPT
import re, sys

for line in sys.stdin:
	match = re.match(r'^([a-zA-Z0-9_-]+):.*?## (.*)$$', line)
	if match:
		target, help = match.groups()
		print("%-20s %s" % (target, help))
endef
export PRINT_HELP_PYSCRIPT

help:
	@python -c "$$PRINT_HELP_PYSCRIPT" < $(MAKEFILE_LIST)


#			--cache-from "${CI_REGISTRY_IMAGE}/base:${LOCK_SHA}" \
#			--cache-from "${CI_REGISTRY_IMAGE}/deps:${LOCK_SHA}" \
#			--cache-from "${CI_REGISTRY_IMAGE}/builder:${LOCK_SHA}" \

sha:
#	@cd .. && sha1sum ${HASH_SEEDS} | sha1sum | awk '{print $1}' | cut -c 1-8
	@echo ${LOCK_SHA}
xxx:
	docker run -it --rm -t python:3.12-slim-bookworm /bin/bash


.build:
	@echo  ${DOCKERHUB_TOKEN} | docker login -u saxix --password-stdin
	cd .. && docker buildx build \
			--progress=plain \
			--build-arg BUILDKIT_INLINE_CACHE=1 \
			--build-arg VERSION=${VERSION} \
			--build-arg BUILD_DATE="${BUILD_DATE}" \
			--build-arg CHECKSUM="${LOCK_SHA}" \
			--build-arg COMMIT="${COMMIT_SHA}" \
			${EXTRA} \
			-t "${DOCKER_IMAGE}:${TAG}" \
			--push \
			-f docker/Dockerfile .
	docker image ls "${DOCKER_IMAGE}:${TAG}"
	@docker inspect -f "{{json .Config.Labels}}" ${DOCKER_IMAGE}:${TAG}

base:  ## build 'builder' image
	STAGE="python_base" \
	EXTRA='--target python_base' \
	DOCKER_IMAGE="${CI_REGISTRY_IMAGE}" \
	TAG="base-${LOCK_SHA}" \
	$(MAKE) .build

buildDeps:  ## build 'builder' image
	STAGE="build_deps" \
	EXTRA='--cache-from "${CI_REGISTRY_IMAGE}:base-${LOCK_SHA}" --target build_deps' \
	DOCKER_IMAGE="${CI_REGISTRY_IMAGE}" \
	TAG="deps-${LOCK_SHA}" \
	$(MAKE) .build

pythonDevDeps:  ## build 'builder' image
	STAGE="python_dev_deps" \
	EXTRA='--cache-from "${CI_REGISTRY_IMAGE}:dev-${LOCK_SHA}" --target python_dev_deps' \
	DOCKER_IMAGE="${CI_REGISTRY_IMAGE}" \
	TAG="dev-${LOCK_SHA}" \
	$(MAKE) .build

pythonProdDeps:  ## build 'builder' image
	STAGE="python_prod_deps" \
	EXTRA='--cache-from "${CI_REGISTRY_IMAGE}:deps-${LOCK_SHA}" --target python_prod_deps' \
	DOCKER_IMAGE="${CI_REGISTRY_IMAGE}" \
	TAG="python_prod_deps-${LOCK_SHA}" \
	$(MAKE) .build

#dev:  ## build dev image
#	STAGE='dev' \
#	EXTRA='--cache-from "${CI_REGISTRY_IMAGE}:python_dev_deps-${LOCK_SHA}" --target dev' \
#	DOCKER_IMAGE="${CI_REGISTRY_IMAGE}" \
#	TAG="dev" \
#	$(MAKE) .build


#test:  ## build test image
#	EXTRA='--target test ' \
#	DOCKER_IMAGE="${CI_REGISTRY_IMAGE}/test" \
#	TAG="${COMMIT_SHA}" \
#	$(MAKE) .build

dist:  ## build prod image
	STAGE='dist' \
	EXTRA='--cache-from "${CI_REGISTRY_IMAGE}:base-${LOCK_SHA}" \
		  --cache-from "${CI_REGISTRY_IMAGE}:deps-${LOCK_SHA}" --target dist' \
	DOCKER_IMAGE="${CI_REGISTRY_IMAGE}" \
	TAG="${VERSION}" \
	$(MAKE) .build
	docker tag ${CI_REGISTRY_IMAGE}:${VERSION} ${CI_REGISTRY_IMAGE}:latest

push:  ## build prod image

	echo ${IMAGE}

all: base buildDeps pythonDevDeps pythonProdDeps dev info

info:
	docker image ls "${CI_REGISTRY_IMAGE}"

check:
	DOCKER_IMAGE=${CI_REGISTRY_IMAGE}:${VERSION} \
	RUN_OPTIONS=-it \
	CMD="django-admin check" \
	$(MAKE) .run

#	DOCKER_IMAGE="${CI_REGISTRY_IMAGE}" \
#	TAG="${VERSION}-${COMMIT}" \
#	$(MAKE) .build

.run:
	cd .. && docker run \
		--rm \
		--name=${CONTAINER_NAME} \
		-p 8000:8000 \
		-e ADMINS="${ADMINS}" \
		-e ADMIN_EMAIL="${ADMIN_EMAIL}" \
		-e ADMIN_PASSWORD="${ADMIN_PASSWORD}" \
		-e ALLOWED_HOSTS="*" \
		-e CACHE_URL="${CACHE_URL}" \
		-e CELERY_BROKER_URL="${CELERY_BROKER_URL}" \
		-e CSRF_COOKIE_SECURE="${CSRF_COOKIE_SECURE}" \
		-e DATABASE_URL="${DATABASE_URL}" \
		-e DEBUG="0" \
		-e INIT_RUN_UPGRADE=1 \
		-e MEDIA_ROOT="/tmp/media" \
		-e SECRET_KEY="${SECRET_KEY}" \
		-e SENTRY_DSN="${SENTRY_DSN}" \
		-e STATIC_ROOT="/tmp/static" \
		${RUN_OPTIONS} \
		-t "${DOCKER_IMAGE}" \
		${CMD}

#		-v ${PWD}/docker/bin/docker-entrypoint.sh:/usr/local/bin/docker-entrypoint.sh \
#		-v ${PWD}/docker/conf/uwsgi.ini:/conf/uwsgi.ini \

shell:  ## run production image
	DOCKER_IMAGE=${CI_REGISTRY_IMAGE}:${VERSION} \
	RUN_OPTIONS=-it \
	CMD=/bin/bash \
	$(MAKE) .run


shell-target:  ## run production image
	DOCKER_IMAGE="${CI_REGISTRY_IMAGE}/$S:latest" \
	RUN_OPTIONS=-it \
	CMD=/bin/bash \
	$(MAKE) .run

run:  ## run production image
	DOCKER_IMAGE=${CI_REGISTRY_IMAGE}:${VERSION} \
	CMD=run \
	$(MAKE) .run

test:
	DOCKER_IMAGE=${CI_REGISTRY_IMAGE}/python_dev_deps:${LOCK_SHA} \
	RUN_OPTIONS="-v .:/hde/code/ -w /hde/code/ -it" \
	CMD="pytest tests/ --create-db -v; ls -al " \
	$(MAKE) .run
#
#run-target:  ## run production image
#	DOCKER_IMAGE="${CI_REGISTRY_IMAGE}/$S:latest" \
#	$(MAKE) .run
#
#test:  ## run production image
#	DOCKER_IMAGE="${CI_REGISTRY_IMAGE}/tests:${COMMIT}" \
#	RUN_OPTIONS=-it \
#	CMD="/bin/bash" \
#	$(MAKE) .run
