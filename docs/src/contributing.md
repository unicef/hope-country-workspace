# Contributing


Install [uv](https://docs.astral.sh/uv/)


    git clone ..
    uv venv .venv --python 3.12
    source .venv/bin/activate
    uv sync --all-extras
    pre-commit install --hook-type pre-commit --hook-type pre-push


## Run tests

    pytests tests

## Run Selenium tests (ONLY)

    pytests tests -m selenium


## Run Selenium any tests

    pytests tests --selenium


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
