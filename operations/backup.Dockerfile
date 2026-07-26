ARG POSTGRES_IMAGE=postgres:18.3-bookworm@sha256:80630f83606d8db77d30b3851b16a9f78be2d0d4dda6f7b82a1fdca5ebe3acba

FROM ${POSTGRES_IMAGE}

RUN apt-get update \
    && apt-get install --yes --no-install-recommends age=1.1.1-1+b3 \
    && rm -rf /var/lib/apt/lists/*

USER backup
WORKDIR /work
