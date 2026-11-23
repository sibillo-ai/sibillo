# The network guard (ADR-0021, ADR-0053, ADR-0114): installs the egress table
# in the sandbox engine's network namespace. Run in that namespace, with
# NET_ADMIN and nothing else, never with host networking (SBX-025). Built from
# the repository root: `docker build -f deploy/images/netguard/Dockerfile .`
FROM python:3.13.9-slim-trixie@sha256:326df678c20c78d465db501563f3492d17c42a4afe33a1f2bf5406a1d56b0e86

RUN apt-get update \
    && apt-get install --yes --no-install-recommends nftables \
    && rm -rf /var/lib/apt/lists/*

COPY src/netguard/sibillo_netguard /opt/netguard/sibillo_netguard
ENV PYTHONPATH=/opt/netguard PYTHONDONTWRITEBYTECODE=1

# Unhealthy while the table is missing and for 10 seconds after it was
# last found missing; the sandbox driver stops sandboxes meanwhile.
HEALTHCHECK --interval=1s --timeout=3s --start-period=10s --retries=1 \
    CMD ["python", "-m", "sibillo_netguard", "check"]
STOPSIGNAL SIGTERM
CMD ["python", "-m", "sibillo_netguard"]
