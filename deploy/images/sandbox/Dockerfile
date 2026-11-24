# The sandbox image (ADR-0053): where the agent's commands run, under gVisor.
# It holds no credentials (SBX-008) and runs nothing until the driver execs
# commands in it.
FROM debian:13.2-slim@sha256:4bcb9db66237237d03b55b969271728dd3d955eaaa254b9db8a3db94550b1885

# Nothing a sandbox uses is left out (ADR-0080): package documentation, and
# the GPU drivers that Debian's ffmpeg depends on but loads only with a GPU,
# which a sandbox does not have.
RUN printf '%s\n' \
        'path-exclude=/usr/share/doc/*' 'path-include=/usr/share/doc/*/copyright' \
        'path-exclude=/usr/share/man/*' 'path-exclude=/usr/share/info/*' \
        'path-exclude=/usr/lib/*/libLLVM*' 'path-exclude=/usr/lib/*/libgallium*' \
        'path-exclude=/usr/lib/*/libz3.so*' 'path-exclude=/usr/lib/*/dri/*' \
        'path-exclude=/usr/lib/*/libvulkan_*' \
        > /etc/dpkg/dpkg.cfg.d/sibillo-sandbox

# The toolbox for a household's files (SBX-021, ADR-0080): documents and
# their fonts, images and media, data, and Node.js.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        bash ca-certificates coreutils curl git iproute2 procps python3 python3-venv \
        poppler-utils qpdf pandoc fontconfig fonts-dejavu-core fonts-liberation fonts-noto-core \
        imagemagick ffmpeg \
        jq sqlite3 file zip unzip xz-utils \
        nodejs \
    && rm -rf /var/lib/apt/lists/*

# npm from its own release, which bundles what it needs, instead of Debian's
# hundreds of packages; checked against the registry's sha512.
ARG NPM_VERSION=10.9.9
ARG NPM_SHA512=d60fba8cb42f688b81e33c2f1cbef2ad7b977166700ec0ad057f1b6d60ea6ef2524abf673e20c35931cd8305d1dbb8887134d6eefdc0e7b8435bd458bf65b862
RUN curl -fsSL "https://registry.npmjs.org/npm/-/npm-${NPM_VERSION}.tgz" -o /tmp/npm.tgz \
    && echo "${NPM_SHA512}  /tmp/npm.tgz" | sha512sum -c - \
    && mkdir -p /usr/local/lib/node_modules/npm \
    && tar -xzf /tmp/npm.tgz -C /usr/local/lib/node_modules/npm --strip-components=1 \
    && ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && rm /tmp/npm.tgz

# Typst, the PDF engine of pandoc (ADR-0084): its own release, which Debian
# does not package, checked against the release's SHA-256.
ARG TARGETARCH
ARG TYPST_VERSION=0.15.1
ARG TYPST_SHA256_AMD64=a6d077d0a95eed5a2eba715b2dae06be954f624ccbf85758a03f389ded33118c
ARG TYPST_SHA256_ARM64=5aa8d74a3d906e60ea12a66ac2f37f8eef1b14cbad7182a745e393a10c23dcee
RUN case "${TARGETARCH:-amd64}" in \
        amd64) target=x86_64 sum="${TYPST_SHA256_AMD64}" ;; \
        arm64) target=aarch64 sum="${TYPST_SHA256_ARM64}" ;; \
        *) echo "no Typst for ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && curl -fsSL "https://github.com/typst/typst/releases/download/v${TYPST_VERSION}/typst-${target}-unknown-linux-musl.tar.xz" \
        -o /tmp/typst.tar.xz \
    && echo "${sum}  /tmp/typst.tar.xz" | sha256sum -c - \
    && tar -xJf /tmp/typst.tar.xz -C /usr/local/bin --strip-components=1 "typst-${target}-unknown-linux-musl/typst" \
    && rm /tmp/typst.tar.xz
# Pandoc's Typst template names no font unless asked, which Typst refuses: by
# default, Typst's own Libertinus Serif, then the image's fonts. The build
# fails if the template no longer has the line.
RUN template=/usr/share/pandoc/data/templates/template.typst \
    && grep -q '^  font: (),$' "$template" \
    && sed -i 's/^  font: (),$/  font: ("Libertinus Serif", "DejaVu Sans", "Noto Sans"),/' "$template"

# The browser of the sandbox (SBX-026, ADR-0138): Lightpanda, one release of
# its own, checked against the release's SHA-256; it runs pages' JavaScript.
# It sends no telemetry, and starts only when a browser tool or the page
# reader needs it.
ARG LIGHTPANDA_RELEASE=1.0.5
ARG LIGHTPANDA_SHA256_AMD64=0ec21fa4867ab9e82b35285ff4ab0e7336c6c1d89f26fe991f27d73c8a678bd7
ARG LIGHTPANDA_SHA256_ARM64=7527391c479f323eb9111b834b012d91a89057528c28ef027741b21739b12299
RUN case "${TARGETARCH:-amd64}" in \
        amd64) target=x86_64 sum="${LIGHTPANDA_SHA256_AMD64}" ;; \
        arm64) target=aarch64 sum="${LIGHTPANDA_SHA256_ARM64}" ;; \
        *) echo "no Lightpanda for ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && curl -fsSL "https://github.com/lightpanda-io/browser/releases/download/${LIGHTPANDA_RELEASE}/lightpanda-${target}-linux" \
        -o /usr/local/bin/lightpanda \
    && echo "${sum}  /usr/local/bin/lightpanda" | sha256sum -c - \
    && chmod 0755 /usr/local/bin/lightpanda
ENV LIGHTPANDA_DISABLE_TELEMETRY=true

# The Python of the agent's work, first on the PATH: office files, Markdown
# for the model, tables and charts, pinned by hash and from wheels only.
COPY deploy/images/sandbox/tools-requirements.txt /opt/tools-requirements.txt
RUN python3 -m venv /opt/tools \
    && /opt/tools/bin/pip install --no-cache-dir --require-hashes --only-binary :all: \
        -r /opt/tools-requirements.txt \
    && rm /opt/tools-requirements.txt \
    && find /opt/tools/lib -depth -type d -name tests -exec rm -rf {} +
ENV PATH=/opt/tools/bin:$PATH

# The page reader of read_page (AGT-021, ADR-0075), with its dependencies
# pinned by hash, in an environment of its own.
COPY deploy/images/sandbox/reader-requirements.txt /opt/reader-requirements.txt
RUN python3 -m venv /opt/reader \
    && /opt/reader/bin/pip install --no-cache-dir --require-hashes --only-binary :all: \
        -r /opt/reader-requirements.txt \
    && rm /opt/reader-requirements.txt
COPY --chmod=0755 deploy/images/sandbox/sibillo-read-page /usr/local/bin/sibillo-read-page
# The client of the browser tools, which starts the browser when none answers (AGT-039, ADR-0138).
COPY --chmod=0755 deploy/images/sandbox/sibillo-browser /usr/local/bin/sibillo-browser

# The disk helper's tools (ADR-0098): the driver makes, checks and grows
# workspaces' disks with them, in a privileged container of its own that runs
# no user content. A sandbox has no block device to use them on.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends e2fsprogs \
    && rm -rf /var/lib/apt/lists/*

# Commands start in the scratch folder; only /workspace persists (ADR-0076); skills are mounted at /skills
# (ADR-0096).
RUN mkdir -p /scratch /workspace /skills
WORKDIR /scratch
CMD ["sleep", "infinity"]
