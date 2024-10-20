# Run Development Version

!!! warning

    This is an unsecure development configuration.
        DO NOT USE IN PRODUCTION OR


To locally run stable not officially released version, simply

    docker run \
	 		--rm \
			-p 8000:8000 \
			-e HOPE_API_TOKEN=${HOPE_API_TOKEN} \
			-e ADMIN_EMAIL="${ADMIN_EMAIL}" \
			-e ADMIN_PASSWORD="${ADMIN_PASSWORD}" \
			-e ALLOWED_HOSTS="*" \
			-e CACHE_URL="redis://[REDIS_SERVER]:[PORT]/0" \
			-e CELERY_BROKER_URL=redis://POSTGRES_SERVER]:[PORT]/0 \
			-e CSRF_COOKIE_SECURE=False \
			-e CSRF_TRUSTED_ORIGINS=http://localhost \
			-e DATABASE_URL="${DATABASE_URL}" \
			-e DEBUG="1" \
			-e DJANGO_ADMIN_URL=admin/ \
			-e DJANGO_SETTINGS_MODULE=country_workspace.config.settings \
			-e LOGGING_LEVEL="DEBUG" \
			-e SECRET_KEY=${SECRET_KEY} \
			-e SOCIAL_AUTH_REDIRECT_IS_HTTPS="False" \
			-e SENTRY_DSN="${SENTRY_DSN}" \
			-e SUPERUSERS="admin," \
			unicef/hope-country-workspace:develop
