#!/usr/bin/env bash
# Install the ai-agent systemd unit for this checkout.
# Usage: sudo deploy/systemd/install.sh
# Optional: AI_AGENT_SERVICE_USER=ai (default). The user is created if missing.

set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "${script_dir}/../.." && pwd)
venv="${root}/.venv"
exec_start="${venv}/bin/ai-agent"
template="${script_dir}/ai-agent.service.in"
dest=/etc/systemd/system/ai-agent.service
service_user="${AI_AGENT_SERVICE_USER:-ai}"
catalog_root=/var/lib/ai-agent/catalog

if [[ ! -x "${exec_start}" ]]; then
  echo "Missing ${exec_start}." >&2
  echo "From ${root}: python3 -m venv .venv && . .venv/bin/activate && pip install -e ." >&2
  exit 1
fi

if ! id -u "${service_user}" >/dev/null 2>&1; then
  shell_path=/usr/sbin/nologin
  if [[ ! -x "${shell_path}" ]]; then
    shell_path=/bin/false
  fi
  useradd \
    --system \
    --create-home \
    --home-dir /var/lib/ai-agent \
    --shell "${shell_path}" \
    "${service_user}"
  echo "Created system user ${service_user} (home /var/lib/ai-agent, no login shell)."
fi

service_group=$(id -gn "${service_user}")
install -d -o "${service_user}" -g "${service_group}" -m 2770 /var/lib/ai-agent
install -d -o "${service_user}" -g "${service_group}" -m 0750 /tmp/ai-agent

can_run_exec() {
  runuser -u "${service_user}" -- test -x "${exec_start}"
}

# Typical failure: checkout under ~/… while the login home directory is 750 (drwxr-x---).
# Others cannot traverse; grant the service user execute-only ACL on blocking parents.
ensure_traversal_to_checkout() {
  local dir="${root}"
  local fixed=false
  while [[ "${dir}" != "/" ]]; do
    if ! runuser -u "${service_user}" -- test -x "${dir}" 2>/dev/null; then
      if [[ "${AI_AGENT_SKIP_ACL:-}" == 1 ]]; then
        return 1
      fi
      if ! command -v setfacl >/dev/null 2>&1; then
        echo "error: ${service_user} cannot traverse ${dir}." >&2
        echo "Install ACL support: sudo apt install acl" >&2
        echo "Re-run this script, or manually:" >&2
        echo "  sudo setfacl -m u:${service_user}:--x ${dir}" >&2
        echo "Repeat for each parent up to / that ${service_user} cannot enter." >&2
        echo "Or move the checkout to /opt/ai-agent and install from there." >&2
        return 1
      fi
      setfacl -m "u:${service_user}:--x" "${dir}"
      echo "Granted ${service_user} traverse (ACL) on ${dir}"
      fixed=true
    fi
    dir=$(dirname "${dir}")
  done
  if [[ "${fixed}" == true ]]; then
    echo "Traverse ACLs applied so ${service_user} can reach the checkout."
  fi
  return 0
}

if ! can_run_exec; then
  if ! ensure_traversal_to_checkout || ! can_run_exec; then
    echo "error: ${service_user} cannot execute ${exec_start}." >&2
    echo "Every parent of ${root} must be traversable by ${service_user}, and the virtualenv must be readable." >&2
    echo "For a home-directory checkout, the usual fix is:" >&2
    echo "  sudo apt install acl" >&2
    echo "  sudo setfacl -m u:${service_user}:--x \"\$(dirname \"\$(dirname \"${root}\")\")\"" >&2
    echo "  sudo deploy/systemd/install.sh" >&2
    exit 1
  fi
fi

if [[ ! -f "${root}/.env" ]]; then
  echo "warning: ${root}/.env does not exist. Copy .env.example and edit it before starting." >&2
elif ! runuser -u "${service_user}" -- test -r "${root}/.env"; then
  echo "warning: ${service_user} cannot read ${root}/.env." >&2
  if getent group "${service_group}" >/dev/null; then
    chgrp "${service_group}" "${root}/.env"
    chmod 640 "${root}/.env"
    if runuser -u "${service_user}" -- test -r "${root}/.env"; then
      echo "Adjusted ${root}/.env to group ${service_group} (mode 640)."
    else
      echo "  sudo chgrp ${service_group} ${root}/.env && sudo chmod 640 ${root}/.env" >&2
    fi
  else
    echo "  sudo chgrp ${service_group} ${root}/.env && sudo chmod 640 ${root}/.env" >&2
  fi
fi

# Shared by the service account and the admin group. StateDirectory creates it.
shared_db="/var/lib/ai-agent/conversations.db"
shared_db_url="sqlite:///${shared_db}"
if [[ -f "${shared_db}" ]]; then
  chown "${service_user}:${service_group}" "${shared_db}"
  chmod 660 "${shared_db}"
fi
if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "${service_user}" ]]; then
  if usermod -aG "${service_group}" "${SUDO_USER}" 2>/dev/null; then
    echo "Added ${SUDO_USER} to group ${service_group} (for ai-agent config access on ${shared_db})."
    echo "Log out and back in, or run: newgrp ${service_group}"
  fi
fi
if [[ -f "${root}/.env" ]]; then
  python3 - "${root}/.env" "${shared_db_url}" "${catalog_root}" <<'PY'
import re
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
shared_url = sys.argv[2]
catalog = sys.argv[3]
text = env_path.read_text()
changed = False
if not re.search(r"^CONVERSATION_DATABASE=\S", text, re.MULTILINE):
    if re.search(r"^CONVERSATION_DATABASE=\s*$", text, re.MULTILINE):
        text = re.sub(
            r"^CONVERSATION_DATABASE=\s*$",
            f"CONVERSATION_DATABASE={shared_url}",
            text,
            count=1,
            flags=re.MULTILINE,
        )
    else:
        if not text.endswith("\n"):
            text += "\n"
        text += (
            "\n# Shared by systemd (user ai) and admin CLI — do not use per-login paths.\n"
            f"CONVERSATION_DATABASE={shared_url}\n"
        )
    changed = True
    print(f"Set CONVERSATION_DATABASE in {env_path} to the shared deployment database.")
if not re.search(r"^WORKFLOW_CATALOG_ROOT=\S", text, re.MULTILINE):
    if not text.endswith("\n"):
        text += "\n"
    text += f"WORKFLOW_CATALOG_ROOT={catalog}\n"
    changed = True
    print(f"Set WORKFLOW_CATALOG_ROOT in {env_path} to {catalog}.")
if changed:
    env_path.write_text(text)
PY
  chgrp "${service_group}" "${root}/.env" 2>/dev/null || true
  chmod 640 "${root}/.env" 2>/dev/null || true
else
  echo "warning: add to .env when created: CONVERSATION_DATABASE=${shared_db_url}" >&2
  echo "warning: add to .env when created: WORKFLOW_CATALOG_ROOT=${catalog_root}" >&2
fi

python3 - \
  "${template}" \
  "${dest}" \
  "${service_user}" \
  "${service_group}" \
  "${root}" \
  "${exec_start}" \
  "${venv}/bin" <<'PY'
import sys
from pathlib import Path

(
    template,
    dest,
    user,
    group,
    root,
    exec_start,
    venv_bin,
) = sys.argv[1:]


def escape(value: str) -> str:
    return value.replace("%", "%%")


path = (
    f"{escape(venv_bin)}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
)
text = Path(template).read_text()
replacements = {
    "@SERVICE_USER@": escape(user),
    "@SERVICE_GROUP@": escape(group),
    "@WORKING_DIRECTORY@": escape(root),
    "@EXEC_START@": escape(exec_start),
    "@PATH@": path,
}
for key, value in replacements.items():
    if key not in text:
        raise SystemExit(f"template is missing {key}")
    text = text.replace(key, value)
Path(dest).write_text(text)
PY

install_docker_broker() {
  local broker_user=ai-docker
  local broker_home=/var/lib/ai-docker
  local broker_template="${script_dir}/ai-agent-docker.service.in"
  local broker_dest=/etc/systemd/system/ai-agent-docker.service
  local broker_bin="${venv}/bin/ai-agent-docker-broker"
  if [[ ! -x "${broker_bin}" ]]; then
    echo "warning: ${broker_bin} is missing, so the Docker broker was not installed." >&2
    echo "From ${root}: pip install -e .   then re-run this installer." >&2
    return 0
  fi
  if ! id -u "${broker_user}" >/dev/null 2>&1; then
    local broker_shell=/usr/sbin/nologin
    if [[ ! -x "${broker_shell}" ]]; then
      broker_shell=/bin/false
    fi
    useradd \
      --system \
      --home-dir "${broker_home}" \
      --create-home \
      --shell "${broker_shell}" \
      "${broker_user}"
    echo "Created system user ${broker_user}. It is the only account that should open the Docker socket."
  else
    usermod -d "${broker_home}" "${broker_user}" || true
    if [[ "$(getent passwd "${broker_user}" | cut -d: -f6)" != "${broker_home}" ]]; then
      echo "warning: set ${broker_user} home to ${broker_home}:" >&2
      echo "  sudo usermod -d ${broker_home} ${broker_user}" >&2
    fi
  fi
  install -d -o "${broker_user}" -g "${broker_user}" -m 0750 "${broker_home}"
  install -d -o "${broker_user}" -g "${broker_user}" -m 0750 "${broker_home}/.docker"
  usermod -aG "${service_group}" "${broker_user}"
  local dir="${root}"
  while [[ "${dir}" != "/" ]]; do
    if ! runuser -u "${broker_user}" -- test -x "${dir}" 2>/dev/null; then
      if command -v setfacl >/dev/null 2>&1; then
        setfacl -m "u:${broker_user}:--x" "${dir}" || true
      fi
    fi
    dir=$(dirname "${dir}")
  done
  install -d -o "${broker_user}" -g "${service_group}" -m 2770 /var/lib/ai-agent/workflow-sleep
  if ! runuser -u "${broker_user}" -- test -x "${catalog_root}" 2>/dev/null; then
    echo "warning: ${broker_user} cannot read ${catalog_root}." >&2
    echo "Workflow image builds stage a context under that catalog." >&2
  fi
  if ! runuser -u "${service_user}" -- test -r "${root}/workflow_image/Dockerfile" 2>/dev/null; then
    echo "warning: ${service_user} cannot read ${root}/workflow_image/Dockerfile." >&2
    echo "The API copies that file into each staged workflow build." >&2
  fi
  python3 - \
    "${broker_template}" \
    "${broker_dest}" \
    "${broker_user}" \
    "${service_group}" \
    "${service_user}" \
    "${root}" \
    "${broker_bin}" \
    "${catalog_root}" <<'PY'
import sys
from pathlib import Path

template, dest, user, group, api_user, root, broker_bin, catalog_root = sys.argv[1:]

def escape(value: str) -> str:
    return value.replace("%", "%%")

text = Path(template).read_text()
replacements = {
    "@BROKER_USER@": escape(user),
    "@SERVICE_GROUP@": escape(group),
    "@SERVICE_USER@": escape(api_user),
    "@WORKING_DIRECTORY@": escape(root),
    "@BROKER_BIN@": escape(broker_bin),
    "@CATALOG_ROOT@": escape(catalog_root),
}
for key, value in replacements.items():
    if key not in text:
        raise SystemExit(f"broker template is missing {key}")
    text = text.replace(key, value)
Path(dest).write_text(text)
PY
  install -d /etc/systemd/system/ai-agent.service.d
  cat > /etc/systemd/system/ai-agent.service.d/docker-broker.conf <<EOF
[Unit]
After=ai-agent-docker.service
Wants=ai-agent-docker.service

[Service]
Environment=AI_AGENT_DOCKER_BROKER=/run/ai-agent/docker.sock
EOF
  configure_docker_userns
  systemctl daemon-reload
  if ! systemctl enable --now ai-agent-docker.service; then
    echo "warning: the Docker broker did not start. Workflows stay unavailable until it does." >&2
  else
    echo "Docker broker is enabled. The API user ${service_user} is not in the docker group."
  fi
}

configure_docker_userns() {
  local pending=/var/lib/ai-agent/docker-userns.pending
  if docker info --format '{{range .SecurityOptions}}{{.}} {{end}}' 2>/dev/null | grep -q userns; then
    rm -f "${pending}"
    echo "Docker user namespaces are already enabled."
    return 0
  fi
  local running=0
  if docker ps -q >/dev/null 2>&1; then
    running=$(docker ps -q | wc -l | tr -d ' ')
  fi
  if [[ "${running}" != "0" ]]; then
    install -d -o "${service_user}" -g "${service_group}" -m 2770 /var/lib/ai-agent
    echo "userns-remap is not enabled. Other containers were running, so dockerd was left alone." > "${pending}"
    echo "warning: workflow containers need Docker userns-remap. Other containers are running," >&2
    echo "so this installer did not restart dockerd. Stop those containers and re-run the installer." >&2
    return 0
  fi
  if ! grep -q '^dockremap:' /etc/subuid 2>/dev/null; then
    echo 'dockremap:100000:65536' >> /etc/subuid
  fi
  if ! grep -q '^dockremap:' /etc/subgid 2>/dev/null; then
    echo 'dockremap:100000:65536' >> /etc/subgid
  fi
  if ! python3 - <<'PY'
import json
from pathlib import Path

path = Path("/etc/docker/daemon.json")
data = {}
if path.exists() and path.read_text().strip():
    data = json.loads(path.read_text())
current = data.get("userns-remap")
if current not in (None, "default"):
    raise SystemExit(f"leave-userns:{current}")
data["userns-remap"] = "default"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(data, indent=2) + "\n")
PY
  then
    echo "warning: left Docker's userns-remap setting unchanged." >&2
    return 0
  fi
  if ! systemctl restart docker; then
    python3 - <<'PY'
import json
from pathlib import Path
path = Path("/etc/docker/daemon.json")
data = json.loads(path.read_text())
data.pop("userns-remap", None)
path.write_text(json.dumps(data, indent=2) + "\n")
PY
    systemctl restart docker || true
    echo "userns-remap could not be enabled; dockerd was restored." > "${pending}"
    echo "warning: could not enable userns-remap. Workflow containers will not start until it is on." >&2
    return 0
  fi
  rm -f "${pending}"
  echo "Enabled Docker userns-remap so root inside a workflow container is not root on the host."
}

install_workflow_catalog() {
  install -d -o "${service_user}" -g "${service_group}" -m 2770 /var/lib/ai-agent
  install -d -o "${service_user}" -g "${service_group}" -m 2770 "${catalog_root}"
  install -d -o "${service_user}" -g "${service_group}" -m 2770 "${catalog_root}/.build"
  if [[ -d "${catalog_root}/workflows" ]] && [[ -n "$(ls -A "${catalog_root}/workflows" 2>/dev/null || true)" ]]; then
    echo "Workflow catalog already present at ${catalog_root}."
    return 0
  fi
  local url=""
  if [[ -f "${root}/.env" ]]; then
    url=$(python3 - "${root}/.env" <<'PY'
import sys
from pathlib import Path
url = ""
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        continue
    key, value = stripped.split("=", 1)
    if key.strip() == "WORKFLOW_CATALOG_URL":
        url = value.strip().strip('"').strip("'")
print(url)
PY
)
  fi
  if [[ -n "${url}" ]] && command -v git >/dev/null 2>&1; then
    local tmp
    tmp=$(mktemp -d)
    if git clone "${url}" "${tmp}/catalog"; then
      local name
      for name in tools libraries workflows; do
        if [[ -d "${tmp}/catalog/${name}" ]]; then
          rm -rf "${catalog_root}/${name}"
          cp -a "${tmp}/catalog/${name}" "${catalog_root}/${name}"
        fi
      done
      if [[ -d "${tmp}/catalog/.git" ]]; then
        rm -rf "${catalog_root}/.git"
        cp -a "${tmp}/catalog/.git" "${catalog_root}/.git"
      fi
      rm -rf "${tmp}"
      chown -R "${service_user}:${service_group}" "${catalog_root}"
      echo "Cloned the workflow catalog into ${catalog_root}."
      return 0
    fi
    rm -rf "${tmp}"
    echo "warning: could not clone the workflow catalog. Seeding it from this checkout." >&2
  fi
  local name
  for name in tools libraries workflows; do
    if [[ ! -d "${root}/workflow_image/${name}" ]]; then
      echo "warning: ${root}/workflow_image/${name} is missing." >&2
      continue
    fi
    rm -rf "${catalog_root}/${name}"
    cp -a "${root}/workflow_image/${name}" "${catalog_root}/${name}"
  done
  chown -R "${service_user}:${service_group}" "${catalog_root}"
  echo "Seeded the workflow catalog at ${catalog_root} from this checkout."
}

install_workflow_catalog

# Workflow images are built with BuildKit. docker-buildx depends on docker.io,
# so this also installs the engine when the machine does not have it yet.
if ! command -v docker >/dev/null 2>&1 || ! docker buildx version >/dev/null 2>&1; then
  echo "Installing docker-buildx. Workflow image builds use BuildKit."
  if ! apt-get update || ! apt-get install -y docker-buildx; then
    echo "warning: docker-buildx was not installed. Workflow image builds need it." >&2
    echo "Install it with: sudo apt install docker-buildx" >&2
    echo "Then re-run this installer." >&2
  fi
fi

if command -v docker >/dev/null 2>&1 && getent group docker >/dev/null 2>&1; then
  install_docker_broker
else
  rm -f /etc/systemd/system/ai-agent.service.d/docker-broker.conf
  systemctl disable --now ai-agent-docker.service >/dev/null 2>&1 || true
  echo "Docker is not installed. The API still starts. Workflows and Docker targets stay unavailable until Docker is installed and this installer is run again."
fi

systemctl daemon-reload

cat <<EOF

Installed ${dest}
Service user: ${service_user}
Working directory: ${root}
Workflow catalog: ${catalog_root}
Pull catalog updates with: ai-agent catalog pull
Force a 1.0.0 line you are still testing with: ai-agent catalog pull --force
Local commands run as each approved user's UID/GID (setpriv).
The unit does not remount the filesystem.
Workflow image builds use BuildKit. The installer installs the docker-buildx
package when that plugin is missing. The package depends on Docker.
Docker is reached through ai-agent-docker.service.
The API user is not added to the docker group.

The unit is not started and not enabled.

Enable and start (typical first time):
  sudo systemctl daemon-reload
  sudo systemctl enable --now ai-agent

Or start once without enabling boot:
  sudo systemctl start ai-agent

Status and logs:
  sudo systemctl status ai-agent
  sudo journalctl -u ai-agent

If this machine uses an NVIDIA GPU, add the service user to the device groups:
  sudo usermod -aG render,video ${service_user}

Database: set CONVERSATION_DATABASE=${shared_db_url} in .env (installer adds this if missing).
Restart after .env changes: sudo systemctl restart ai-agent
Approve users: ai-agent config access list  (same .env / path as the service)

If an engine is already listening at LLM_UPSTREAM, this service attaches to it
and does not stop it on shutdown. Leave that engine's own unit enabled only
when you want that.
EOF
