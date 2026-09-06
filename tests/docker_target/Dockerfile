FROM debian:bookworm-slim

# Passwordless sudo for the unprivileged `agent` user only.
# docker exec runs as this user; sudo -n must succeed without a TTY or prompt.
RUN apt-get update \
    && apt-get install -y --no-install-recommends sudo \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash agent \
    && printf '%s\n' \
        'Defaults:agent !requiretty' \
        'Defaults:agent !lecture' \
        'agent ALL=(ALL) NOPASSWD:ALL' \
        > /etc/sudoers.d/agent \
    && chmod 0440 /etc/sudoers.d/agent

USER agent
WORKDIR /home/agent
