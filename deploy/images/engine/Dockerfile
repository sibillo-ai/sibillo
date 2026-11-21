# The sandbox engine (SBX-025, ADR-0114): a Docker Engine of its own with
# gVisor in it, where sandboxes, their bridges and their workspaces live, so
# that the host needs Docker and nothing else (OPS-001). It is the only
# privileged container of the instance, and listens only on a Unix socket
# shared with the sandbox driver.
#
# Built from the repository root, with the sandbox image as a named context:
#   docker build -f deploy/images/sandbox/Dockerfile -t sibillo/sandbox:local .
#   docker build -f deploy/images/engine/Dockerfile \
#       --build-context sandbox-image=docker-image://sibillo/sandbox:local .

# gVisor, one release from its official repository, pinned and verified by
# checksum (SBX-017). The package holds `runsc` and the programs it runs with.
FROM debian:13.2-slim AS gvisor
ARG TARGETARCH
ARG GVISOR_RELEASE=20261116.0
ARG GVISOR_SHA256_AMD64=495796a56d811a43ea218bd0af3d89ea471df1cbd684edcb21c4a00356caeb1e
ARG GVISOR_SHA256_ARM64=89e0224e8035525324a8685c65f3454746aeb28a508f27db15b52c9d8a9b66e1
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
RUN case "$TARGETARCH" in \
        amd64) sum="$GVISOR_SHA256_AMD64" ;; \
        arm64) sum="$GVISOR_SHA256_ARM64" ;; \
        *) echo "unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac \
    && curl --fail --silent --show-error --location --output /tmp/runsc.deb \
        "https://storage.googleapis.com/gvisor/releases/pool/${GVISOR_RELEASE}/binary-${TARGETARCH}/runsc.deb" \
    && echo "$sum  /tmp/runsc.deb" | sha256sum --check --strict \
    && dpkg-deb --extract /tmp/runsc.deb /gvisor \
    && test -x /gvisor/usr/bin/runsc && test -d /gvisor/usr/bin/gvisor-bin

# The sandbox image as one archive, with the environment its commands need:
# the engine has no registry to pull it from (ADR-0114).
FROM sandbox-image AS sandbox
USER root
RUN mkdir /.engine \
    && env | grep -vE '^(HOSTNAME|HOME|PWD|OLDPWD|SHLVL|TERM|_)=' | sort > /.engine/environment \
    && pwd > /.engine/workdir \
    && tar --create --one-file-system --numeric-owner --xattrs --file /.engine/rootfs.tar \
        --exclude=./.engine --exclude=./proc --exclude=./sys --exclude=./dev --exclude=./tmp/* \
        --directory / . \
    && sha256sum /.engine/rootfs.tar /.engine/environment /.engine/workdir | sha256sum | cut -c1-16 > /.engine/id

FROM docker:29.10.0-dind@sha256:4bbc7223f81db790097c6dea42fb93e05b8fead4f0431fbe6ccaba6e8473201c
COPY --from=gvisor /gvisor/usr/bin/runsc /usr/local/bin/runsc
COPY --from=gvisor /gvisor/usr/bin/gvisor-bin /usr/local/bin/gvisor-bin
COPY --from=sandbox /.engine /sandbox
COPY deploy/images/engine/daemon.json /etc/docker/daemon.json
COPY deploy/images/engine/sibillo-engine /usr/local/bin/sibillo-engine
RUN chmod 0755 /usr/local/bin/sibillo-engine

VOLUME /var/lib/docker
# Ready when Docker answers on its socket and holds the sandbox image.
HEALTHCHECK --interval=2s --timeout=5s --start-period=120s --retries=3 \
    CMD ["test", "-f", "/run/sibillo-engine-ready"]
STOPSIGNAL SIGTERM
ENTRYPOINT ["/usr/local/bin/sibillo-engine"]
