# Contributing


Install [uv](https://docs.astral.sh/uv/)


    git clone ..
    uv venv .venv --python 3.12
    source .venv/bin/activate
    uv sync --all-extras
    pre-commit install --hook-type pre-commit --hook-type pre-push

## PyMiniRacer on Apple Silicon

1. Found your site-packages

        python -m site
        >>> /opt/homebrew/Caskroom/miniconda/base/lib/python3.8/site-packages

1. Download the Dylib file

        wget https://github.com/sqreen/PyMiniRacer/files/7575004/libmini_racer.dylib.zip

1. Unzip The Dylib file

       unzip libmini_racer.dylib.zip

1. MV Dylib file to your site-packages

       mv libmini_racer.dylib /opt/homebrew/Caskroom/miniconda/base/lib/python3.8/site-packages/py_mini_racer/.

1. Import Success.

        >>> from py_mini_racer import MiniRacer



## Tailwind CSS

This project uses [django-tailwind](https://django-tailwind.readthedocs.io/en/latest/installation.html) to manage
CSS. CSS sources are located in the `country_workspace/workspaces/theme/static_src/src/`.
If you need to edit the CSS follow the below steps:

1. Install node dependencies

        ./manage.py tailwind install

1. Configure the enviroment

        export EXTRA_APPS="country_workspace.contrib.hope,django_browser_reload"
        export EXTRA_MIDDLEWARES="django_browser_reload.middleware.BrowserReloadMiddleware,"

1. Build the final CSS

        ./manage.py tailwind build

    Or you can run the [development mode](https://django-tailwind.readthedocs.io/en/latest/usage.html#running-in-development-mode)

        ./manage.py tailwind start



## Run tests

    pytest tests

## Run Selenium tests (ONLY)

    pytest tests -m selenium


## Run Selenium any tests

    pytest tests --selenium


!!! note

    You can disable selenium headless mode (show the browser activity on the screen) using  `--show-browser` flag




## Run local server


    ./manage.py runserver


!!! note

    To facililate developing you can use:

        export AUTHENTICATION_BACKENDS="country_workspace.security.backends.AnyUserAuthBackend"

    It works only if `DEBUG=True`



## Docker compose

Alternatively you can use provided docker compose for development

    docker compose up

Alternatively you can use provided docker compose for development

    docker compose up
