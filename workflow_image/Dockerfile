# syntax=docker/dockerfile:1

# Generic workflow image.
#
# Builds the Nix closure named by WORKFLOW and packs it into one container.
# Session parameters (a family name, a label, and anything else the user
# fills in) are not build inputs. The host writes those into /work when it
# starts a container from this image.
#
#   docker buildx build --load --build-arg WORKFLOW=text-lab -t ai-agent-workflow:text-lab .
#
# The same file builds any workflow that has a workflow.lock.json and a
# default.nix per tool. Unchanged tools stay in the Nix store of this build
# stage; Docker reuses the build layer when the copied sources and WORKFLOW
# argument are unchanged. Do not mount a fresh empty directory over
# /nix/store here: that hides the Nix this image needs in order to build.

# Hub publishes patch tags (2.24.15), not bare 2.24.
FROM nixos/nix:2.24.15 AS build

ARG WORKFLOW=text-lab
ARG NIX_SYSTEM=x86_64-linux

WORKDIR /src
COPY flake.nix ./
COPY nix ./nix
COPY workflows ./workflows

RUN --mount=type=cache,target=/root/.cache/nix \
    nix --extra-experimental-features 'nix-command flakes' \
      build "/src#packages.${NIX_SYSTEM}.${WORKFLOW}" --out-link /tmp/closure \
    && mkdir -p /export/nix/store \
    && cp -a $(nix-store -qR /tmp/closure) /export/nix/store/ \
    && cp -a /tmp/closure /export/workflow

FROM debian:bookworm-slim

# Tools built by Nix use their own OpenSSL, which does not look in
# /etc/ssl/certs unless SSL_CERT_FILE points there.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /work && chmod 1777 /work
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

COPY --from=build /export/nix/store /nix/store
COPY --from=build /export/workflow /opt/workflow

ENV PATH="/opt/workflow/bin:${PATH}"
WORKDIR /work

# The process stays up. The host runs tools with docker exec.
# Root here is root inside the container only. The host starts this image
# with a user namespace so that uid is not root on the host.
CMD ["sleep", "infinity"]
