"""One-time import from legacy global execution_targets.yaml."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from ai_agent.deployment.access import AccessStatus
from ai_agent.deployment.access_store import DeploymentAccessStore
from ai_agent.execution_targets.repository import UserExecutionTargetRepository
from ai_agent.execution_targets.secure_key_store import OSSecureKeyStore
from ai_agent.execution_targets.store import (
    DockerTargetRecord,
    RESERVED_LOCAL_NAME,
    SshTargetRecord,
    execution_target_dir,
    load_targets_file,
    TargetConfigError,
)


def import_legacy_yaml(
    path: Path,
    *,
    user_id: str,
    repo: UserExecutionTargetRepository,
    access_store: DeploymentAccessStore,
    key_store: OSSecureKeyStore | None = None,
) -> int:
    """Copy legacy YAML targets into one user's SQLite records."""
    document = load_targets_file(path)
    record = access_store.get(user_id)
    if record is None or record.status != AccessStatus.APPROVED:
        raise TargetConfigError("User must be approved before importing targets.")
    linux = record.linux_username.strip()
    if not linux:
        raise TargetConfigError("User must have --run-as linux_username set.")
    store = key_store or OSSecureKeyStore()
    imported = 0
    for name, spec in document.execution_targets.items():
        if name == RESERVED_LOCAL_NAME:
            continue
        if isinstance(spec, SshTargetRecord):
            target_id = str(uuid.uuid4())
            store.initialize_target(linux, target_id)
            legacy_dir = execution_target_dir(name)
            _copy_ssh_material(legacy_dir, store, linux, target_id, spec)
            repo.add_ssh(
                user_id,
                name=name,
                host=spec.host,
                user=spec.user,
                port=spec.port,
                description=spec.description,
                target_id=target_id,
            )
            imported += 1
        elif isinstance(spec, DockerTargetRecord):
            repo.add_docker(
                user_id,
                name=name,
                container=spec.container,
                description=spec.description,
                docker_bin=spec.docker_bin,
                user=spec.user,
            )
            imported += 1
    return imported


def _copy_ssh_material(
    legacy_dir: Path,
    store: OSSecureKeyStore,
    linux_username: str,
    target_id: str,
    spec: SshTargetRecord,
) -> None:
    dest_root = store.get_known_hosts_path(linux_username, target_id).parent
    for candidate in (spec.identity_file, legacy_dir / "id_ed25519"):
        if candidate and candidate.is_file():
            shutil.copy2(candidate, dest_root / "id_ed25519")
            break
    pub_src = spec.identity_file.parent / "id_ed25519.pub" if spec.identity_file else None
    if pub_src and pub_src.is_file():
        shutil.copy2(pub_src, dest_root / "id_ed25519.pub")
    known_src = spec.known_hosts or legacy_dir / "known_hosts"
    if known_src.is_file():
        shutil.copy2(known_src, dest_root / "known_hosts")
