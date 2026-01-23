# Build and use your docker

After you have cloned the repo, be sure to have a Redis and PostgreSQL server running on your machine

    export ADMIN_EMAIL=admin@example.com
    export ADMIN_PASSWORD=password
    export DATABASE_URL=postgres://postgres:@127.0.0.1:5432/hope_dedup_engine
    export CACHE_URL=redis://127.0.0.1:6379/1?client_class=django_redis.client.DefaultClient

    cd docker

    make build run


## Use provided compose.yml

    docker compose up

navigate to http://localhost:8000/admin/ and login using `admin@example.com/password`
