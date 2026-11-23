# The sandbox driver image (ADR-0022, ADR-0054): the only container with the
# sandbox engine's Docker socket, and never the host's (SBX-009, SBX-025).
# Built from the repository root:
# `docker build -f deploy/images/sandboxd/Dockerfile .`
FROM python:3.13.9-slim-trixie@sha256:326df678c20c78d465db501563f3492d17c42a4afe33a1f2bf5406a1d56b0e86

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src/server/pyproject.toml src/server/pyproject.toml
COPY src/sandboxd/pyproject.toml src/sandboxd/pyproject.toml
COPY src/netguard/pyproject.toml src/netguard/pyproject.toml
RUN uv sync --frozen --no-dev --package sibillo-sandboxd --no-install-workspace
COPY src/sandboxd src/sandboxd
RUN uv sync --frozen --no-dev --package sibillo-sandboxd --no-editable

ENV PATH=/opt/venv/bin:$PATH
# The engine's Docker socket is root's; the driver holds it alone (SBX-009).
ENTRYPOINT ["python", "-m", "sibillo_sandboxd"]
