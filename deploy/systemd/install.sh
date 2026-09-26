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
install -d -o "${service_user}" -g "${service_group}" -m 0750 /var/lib/ai-agent
install -d -o "${service_user}" -g "${service_group}" -m 0750 /tmp/ai-agent

home_dir=$(getent passwd "${service_user}" | cut -d: -f6)
protect_home=true
if [[ "${home_dir}" == /home/* || "${home_dir}" == /root/* ]]; then
  # Conversation storage defaults to this user's home.
  protect_home=false
elif [[ "${root}" == /home/* || "${root}" == /root/* ]]; then
  # The checkout must be readable. Writes stay in the service home and /tmp.
  protect_home=read-only
fi

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

python3 - \
  "${template}" \
  "${dest}" \
  "${service_user}" \
  "${service_group}" \
  "${root}" \
  "${exec_start}" \
  "${venv}/bin" \
  "${protect_home}" <<'PY'
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
    protect_home,
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
    "@PROTECT_HOME@": protect_home,
}
for key, value in replacements.items():
    if key not in text:
        raise SystemExit(f"template is missing {key}")
    text = text.replace(key, value)
Path(dest).write_text(text)
PY

systemctl daemon-reload

cat <<EOF

Installed ${dest}
Service user: ${service_user}
Working directory: ${root}
ProtectHome=${protect_home}

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

If an engine is already listening at LLM_UPSTREAM, this service attaches to it
and does not stop it on shutdown. Leave that engine's own unit enabled only
when you want that.
EOF
