#!/bin/sh -e


export MEDIA_ROOT="${MEDIA_ROOT:-/var/run/app/media}"
export STATIC_ROOT="${STATIC_ROOT:-/var/run/app/static}"
export UWSGI_PROCESSES="${UWSGI_PROCESSES:-"4"}"
#export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-"country_workspace.config.settings"}"

ls -al /app/

case "$1" in
    run)
      django-admin check --deploy
      django-admin upgrade
	    set -- tini -- "$@"
  		set -- gosu user:app uwsgi --ini /conf/uwsgi.ini
	    ;;
esac

exec "$@"

#
#case "$1" in
#    run)
#      if [ "$INIT_RUN_CHECK" = "1" ];then
#        echo "Running Django checks..."
#        django-admin check --deploy
#      fi
#      OPTS="--no-check -v 1"
#      if [ "$INIT_RUN_UPGRADE" = "1" ];then
#        if [ "$INIT_RUN_COLLECTSTATIC" != "1" ];then
#          OPTS="$OPTS --no-static"
#        fi
#        if [ "$INIT_RUN_MIGRATATIONS" != "1" ];then
#          OPTS="$OPTS --no-migrate"
#        fi
#        echo "Running 'upgrade $OPTS'"
#        django-admin upgrade $OPTS
#      fi
#      set -- tini -- "$@"
#      echo "Starting uwsgi..."
#      exec uwsgi --ini /conf/uwsgi.ini
#      ;;
#    worker)
#      exec celery -A country_workspace.celery worker -E --loglevel=ERROR --concurrency=4
#      ;;
#    beat)
#      exec celery -A country_workspace.celery beat -E --loglevel=ERROR ---scheduler django_celery_beat.schedulers:DatabaseScheduler
#      ;;
#    dev)
#      until pg_isready -h db -p 5432;
#        do echo "waiting for database"; sleep 2; done;
#      django-admin collectstatic --no-input
#      django-admin migrate
#      django-admin runserver 0.0.0.0:8000
#      ;;
#    *)
#      exec "$@"
#      ;;
#esac
