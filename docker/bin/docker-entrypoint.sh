#!/bin/sh -e


export UWSGI_PROCESSES="${UWSGI_PROCESSES:-"4"}"
export DJANGO_SETTINGS_MODULE="country_workspace.config.settings"


case "$1" in
    run)
      django-admin upgrade --with-check
	    set -- tini -- "$@"
	    MAPPING=""
	    if [ "${STATIC_URL}" = "/static/" ]; then
	      MAPPING="--static-map ${STATIC_URL}=${STATIC_ROOT}"
	    fi
      set -- tini -- "$@"
	    set -- uwsgi --http :8000 \
	          -H /venv \
	          --module country_workspace.config.wsgi \
	          --mimefile=/conf/mime.types \
	          --uid hope \
	          --gid unicef \
            --buffer-size 8192 \
            --http-buffer-size 8192 \
	          $MAPPING
	    ;;
    upgrade)
      django-admin upgrade --with-check
      ;;
    worker)
      set -- tini -- "$@"
      set -- gosu hope:unicef celery -A country_workspace.config.celery worker --statedb worker -E --loglevel=ERROR
      ;;
    beat)
      set -- tini -- "$@"
      set -- gosu hope:unicef celery -A country_workspace.config.celery beat --loglevel=ERROR --scheduler django_celery_beat.schedulers:DatabaseScheduler
      ;;
    flower)
      export DATABASE_URL="sqlite://:memory:"
      set -- tini -- "$@"
      set -- gosu hope:unicef celery -A country_workspace.config.celery flower
      ;;
esac

exec "$@"


# case "$1" in
#     run)
#         django-admin upgrade --with-check
#         MAPPING=""
#         if [ "${STATIC_URL}" = "/static/" ]; then
#             MAPPING="--static-map ${STATIC_URL}=${STATIC_ROOT}"
#         fi
#         set -- tini -- uwsgi --http :8000 \
#             -H /venv \
#             --module country_workspace.config.wsgi \
#             --mimefile=/conf/mime.types \
#             --uid hope \
#             --gid unicef \
#             --buffer-size 8192 \
#             --http-buffer-size 8192 \
#             $MAPPING "$@"
#         ;;
#     upgrade)
#         set -- tini -- django-admin upgrade --with-check "$@"
#         ;;
#     worker)
#         set -- tini -- celery -A country_workspace.config.celery worker --statedb worker -E --loglevel=ERROR "$@"
#         ;;
#     beat)
#         set -- tini -- celery -A country_workspace.config.celery beat --loglevel=ERROR --scheduler django_celery_beat.schedulers:DatabaseScheduler "$@"
#         ;;
#     flower)
#         if [ -z "$DATABASE_URL" ]; then
#             echo "Warning: DATABASE_URL is not set, defaulting to in-memory SQLite for Flower"
#             export DATABASE_URL="sqlite://:memory:"
#         fi
#         set -- tini -- celery -A country_workspace.config.celery flower "$@"
#         ;;
#     *)
#         echo "Unknown command: $1"
#         echo "Supported commands: run, upgrade, worker, beat, flower"
#         exit 1
#         ;;
# esac

# exec "$@"
