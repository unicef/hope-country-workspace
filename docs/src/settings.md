
# Setttings


### ADMIN_EMAIL
_Default_: ``

Initial user created at first deploy


__Suggested value for development__: `admin`

### ADMIN_PASSWORD
_Default_: ``

Password for initial user created at first deploy


### ALLOWED_HOSTS
_Default_: `[]`

@see https://docs.djangoproject.com/en/5.0/ref/settings#allowed-hosts


__Suggested value for development__: `['127.0.0.1', 'localhost']`

### AUTHENTICATION_BACKENDS
_Default_: `[]`

Extra authentications backends enabled to add. Es. `country_workspace.security.backends.AnyUserAuthBackend`


### CACHE_URL
_Default_: ``

@see https://docs.djangoproject.com/en/5.0/ref/settings#cache-url


__Suggested value for development__: `redis://localhost:6379/0`

### CELERY_BROKER_URL
_Default_: ``

https://docs.celeryq.dev/en/stable/django/first-steps-with-django.html


### CELERY_TASK_ALWAYS_EAGER
_Default_: `False`

@see https://docs.celeryq.dev/en/stable/userguide/configuration.html##std-setting-task_always_eager


__Suggested value for development__: `True`

### CELERY_TASK_EAGER_PROPAGATES
_Default_: `True`

@see https://docs.celeryq.dev/en/stable/userguide/configuration.html##task-eager-propagates


__Suggested value for development__: `True`

### CELERY_VISIBILITY_TIMEOUT
_Default_: `1800`

@see https://docs.celeryq.dev/en/stable/userguide/configuration.html##broker-transport-options


__Suggested value for development__: `1800`

### CSRF_COOKIE_SECURE
_Default_: `True`

@see https://docs.djangoproject.com/en/5.0/ref/settings#csrf-cookie-secure


### CSRF_TRUSTED_ORIGINS
_Default_: `localhost`




### DATABASE_URL
_Default_: `<NoValue>`

https://django-environ.readthedocs.io/en/latest/types.html#environ-env-db-url


__Suggested value for development__: `<NoValue>`

### DEBUG
_Default_: `False`

@see https://docs.djangoproject.com/en/5.0/ref/settings#debug


__Suggested value for development__: `True`

### EMAIL_HOST
_Default_: ``

@see https://docs.djangoproject.com/en/5.0/ref/settings#email-host


### EMAIL_HOST_PASSWORD
_Default_: ``

@see https://docs.djangoproject.com/en/5.0/ref/settings#email-host-password


### EMAIL_HOST_USER
_Default_: ``

@see https://docs.djangoproject.com/en/5.0/ref/settings#email-host-user


### EMAIL_PORT
_Default_: `25`

@see https://docs.djangoproject.com/en/5.0/ref/settings#email-port


__Suggested value for development__: `25`

### EMAIL_SUBJECT_PREFIX
_Default_: `[Hope-cw]`

@see https://docs.djangoproject.com/en/5.0/ref/settings#email-subject-prefix


__Suggested value for development__: `[Hope-ce]`

### EMAIL_TIMEOUT
_Default_: `None`

@see https://docs.djangoproject.com/en/5.0/ref/settings#email-timeout


### EMAIL_USE_LOCALTIME
_Default_: `False`

@see https://docs.djangoproject.com/en/5.0/ref/settings#email-use-localtime


### EMAIL_USE_SSL
_Default_: `False`

@see https://docs.djangoproject.com/en/5.0/ref/settings#email-use-ssl


### EMAIL_USE_TLS
_Default_: `False`

@see https://docs.djangoproject.com/en/5.0/ref/settings#email-use-tls


### FILE_STORAGE_DEFAULT
_Default_: `django.core.files.storage.FileSystemStorage`




__Suggested value for development__: `@see https://docs.djangoproject.com/en/5.0/ref/settings#storages`

### FILE_STORAGE_MEDIA
_Default_: `django.core.files.storage.FileSystemStorage`




__Suggested value for development__: `@see https://docs.djangoproject.com/en/5.0/ref/settings#storages`

### FILE_STORAGE_STATIC
_Default_: `django.contrib.staticfiles.storage.StaticFilesStorage`




__Suggested value for development__: `@see https://docs.djangoproject.com/en/5.0/ref/settings#storages`

### HOPE_API_TOKEN
_Default_: ``

Hope API token


### LOGGING_LEVEL
_Default_: `CRITICAL`

@see https://docs.djangoproject.com/en/5.0/ref/settings#logging-level


__Suggested value for development__: `DEBUG`

### MEDIA_ROOT
_Default_: `/var/media/`

@see https://docs.djangoproject.com/en/5.0/ref/settings#media-root


__Suggested value for development__: `/tmp/media`

### MEDIA_URL
_Default_: `/media/`

@see https://docs.djangoproject.com/en/5.0/ref/settings#media-root


__Suggested value for development__: `/media`

### ROOT_TOKEN
_Default_: ``




### ROOT_TOKEN_HEADER
_Default_: `x-root-token`




__Suggested value for development__: `x-root-token`

### SECRET_KEY
_Default_: ``

@see https://docs.djangoproject.com/en/5.0/ref/settings#secret-key


__Suggested value for development__: `super_secret_key_just_for_testing`

### SENTRY_DSN
_Default_: ``

Sentry DSN


### SENTRY_ENVIRONMENT
_Default_: `production`

Sentry Environment


__Suggested value for development__: `develop`

### SENTRY_URL
_Default_: ``

Sentry server url


### SOCIAL_AUTH_LOGIN_URL
_Default_: `/login/`




### SOCIAL_AUTH_RAISE_EXCEPTIONS
_Default_: `False`




__Suggested value for development__: `True`

### SOCIAL_AUTH_REDIRECT_IS_HTTPS
_Default_: `True`




### STATIC_ROOT
_Default_: `/var/static`

@see https://docs.djangoproject.com/en/5.0/ref/settings#static-root


__Suggested value for development__: `/tmp/static`

### STATIC_URL
_Default_: `/static/`

@see https://docs.djangoproject.com/en/5.0/ref/settings#static-url


__Suggested value for development__: `/static/`

### SUPERUSERS
_Default_: `[]`

"list of emails/or usernames that will automatically granted superusers privileges ONLY the first time they are created .
This is designed to be used in dev/qa environments deployed by CI, where database can be empty.  
        


### TIME_ZONE
_Default_: `UTC`

@see https://docs.djangoproject.com/en/5.0/ref/settings#std-setting-TIME_ZONE


__Suggested value for development__: `UTC`
