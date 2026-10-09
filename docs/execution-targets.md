# Execution targets (design)

This document describes how **named command execution** works today, how it will
change for multi-user deployments, and what we will build before **v2**. It is
the standalone reference for operators and contributors. Implementation follows
this doc; it is not a task list for automated refactors.

**Related:** [Local in-process chat (v2)](local-in-process-chat.md) for the
simple single-machine CLI path.

---

## Table of contents

1. [Problem and goals](#problem-and-goals)
2. [Two classes of target](#two-classes-of-target)
3. [Ownership and isolation](#ownership-and-isolation)
4. [Who configures what](#who-configures-what)
5. [Runtime: API turns](#runtime-api-turns)
6. [Defaults](#defaults)
7. [Storage: SQLite + SecureKeyStore](#storage-sqlite--securekeystore)
8. [Configuration CLI and user identity](#configuration-cli-and-user-identity)
9. [Chat clients vs server (no tight coupling)](#chat-clients-vs-server-no-tight-coupling)
10. [Legacy YAML (temporary)](#legacy-yaml-temporary)
11. [Migration from global YAML](#migration-from-global-yaml)
12. [Future: shared namespace and per-user defaults](#future-shared-namespace-and-per-user-defaults)

---

## Problem and goals

The agent runs **structured commands** (`CommandExpr` JSON), not shell strings.
Each tool call may specify a **target name**. The model must not supply hostnames,
SSH keys, or container IDs — only names from an allow-list we control.

On a shared `ai-agent serve` deployment, **many Supabase users** can be approved.
Each has their own **Linux account** for commands on the agent host (`local`).
Remote SSH and Docker targets must **not** be global: one user's `prod-web` must
not expose another user's hosts or keys.

Goals:

- **Server-local** execution always uses the approved **`linux_username`** for
  that Supabase `user_id`.
- **SSH/Docker** targets are **per `user_id`**, stored in the deployment SQLite
  DB with secrets on disk via **`SecureKeyStore`**.
- **Chat clients** (terminal `ai-agent` after login, Android) never load target
  config; the server resolves targets per turn from the authenticated session.

---

## Two classes of target

| Class | Name | Visible to | Meaning |
|-------|------|------------|---------|
| **Server local** | `local` (fixed name) | Every approved user with a linked Linux account | Commands on the **agent machine** only, via that user's `run_as_linux_user` and scratch under `AGENT_SCRATCH_DIR/<linux_user>/`. |
| **User targets** | Any other valid name | **Only** the owning Supabase `user_id` | SSH or Docker definitions plus key material owned by that user. |

Users without `linux_username` remain blocked at the access gate
(`access_incomplete`); they do not get a working agent.

Target kinds for user targets (unchanged conceptually):

| Type | Meaning |
|------|---------|
| `ssh` | Remote host; agent runs `ssh` from the agent host as the user's Linux account, using keys from `SecureKeyStore`. |
| `docker` | `docker exec` into a specifically configured container on the agent host, subject to the user's execution identity and the server's Docker authorization rules. The model supplies only the configured target name; it does not supply an arbitrary container ID or Docker command. |


---

## Ownership and isolation

- **Primary key:** Supabase **`user_id`** (JWT `sub`), same as
  `deployment_access.user_id`. Linux username is **execution identity on the
  box**, not the ownership key for target rows.
- **Name collisions across users are allowed:** Alice's `web-01` and Bob's
  `web-01` are different records.
- **Shared fleet namespace** (one target visible to many users) is a possible
  later extension (`owner_kind=shared` or similar). **v2 ships per-user only** so
  we can add shared targets later without breaking schema.

At turn time:

1. Authenticate JWT and pass deployment access gate.
2. Load target set for **`user_id`** only (plus synthetic `local`).
3. Build `ExecutionTargetRouter`, tool schema, and system prompt from that set
   only.
4. Unknown name → error (no cross-user leakage).

### Docker target access and isolation

Docker targets are user-owned execution-target records, but a Docker target must not become an unrestricted mechanism for selecting arbitrary containers on the agent host.

A Docker target resolves from the user's configured target name to a server-side record containing the specific container to which that target is bound. The model does **not** provide or select arbitrary container IDs, container names, images, mounts, or other Docker configuration at execution time.

For example, the model may request:

```json
{
  "target": "dev-container",
  "command": "pytest"
}
```

The server resolves `dev-container` to the authenticated user's configured target:

```text
user_id + "dev-container"
        ↓
execution_target
        ↓
type = docker
container = <server-configured container>
        ↓
Docker executor
```

The executor must not interpret model-supplied target data as an arbitrary Docker resource selector. Container identity comes exclusively from the trusted execution-target configuration.

Docker execution also runs through the same server-side execution-identity controls as other command execution. In particular, the Docker executor must use the configured execution mechanism rather than allowing the model to construct arbitrary `docker exec` invocations.

Deployments should account for the fact that Docker access can confer substantially greater host privileges than an ordinary process. In particular, membership in the host's Docker group or equivalent unrestricted Docker access may allow a process to obtain privileges beyond the intended application-level isolation boundary.

Therefore:

* A user's Docker target grants access only to the specifically configured target; it does not grant the model a general-purpose Docker API.
* Container selection is configuration data, not model-controlled tool input.
* Docker commands are constructed by the executor from validated target configuration and structured command data.
* The deployment's Linux-account and Docker-permission configuration determines the actual OS-level authority available to the executor.
* If stronger isolation is required, the deployment should use containers, VMs, or another execution boundary designed to prevent Docker access from becoming equivalent to host access.

Shared Docker targets are not part of the initial per-user model. If shared targets are introduced later, their ownership and authorization rules should be explicit rather than relying on a global Docker namespace.


---

## Who configures what

| Actor | Action | Mechanism |
|-------|--------|-----------|
| **Administrator** | Allow/deny deployment access; link user to Linux account | `ai-agent config access approve <user_id> --run-as <linux_user>` (and related access commands). |
| **Administrator** | Grant or revoke host-monitoring access | `ai-agent config monitoring grant <user_id>` / `revoke` / `list`. Separate from deployment access; see the README section "Monitoring admins". |
| **End user** | Add/list/trust SSH or Docker targets **for themselves** | Server-side configuration using **`user_id` from the authenticated session** (see below). |
| **Administrator (on behalf of another user)** | Same target commands, explicit subject | Same commands with **`user_id` required**; admin passes the subject user's id when managing their targets. |
| **Chat clients** (`ai-agent` after login, Android) | Chat only | **No** target configuration in the client. Server enforces scope on each `/turns` request. |

Administrators approve **who** may use the server and **which local OS account**
runs `local` commands. They do not publish a global list of SSH hosts every user
inherits unless we add shared targets in a later release.

---

## Runtime: API turns

Today each HTTP turn builds a fresh agent via `build_api_agent_factory`, which
already sets `run_as_linux_user` and per-user scratch. The planned change is
**where the router gets its target list**:

```text
JWT sub (user_id)
    → UserExecutionTargetRepository.load(user_id)   # SQLite + SecureKeyStore
    → ExecutionTargetRouter (always includes local)
    → AgentLoop + prompt listing only those names
```

Only **`ai-agent serve`** (and future in-process chat wired like serve) runs this
path. Nothing in `clients/cli/` or Android loads execution targets.

---

## Defaults

**v2 behavior:**

- When the model **omits** `target`, resolution uses **`local`** for every user.
- **Remove global default configuration:** no `AGENT_DEFAULT_TARGET` in `.env`,
  no YAML `default_target` as authority, no env override in `load_router`.

At the code location where the router default is chosen, leave a **non-urgent**
note for humans (not a `TODO:`), for example:

```python
# Per-user default target names may be stored in SQLite later. Until then,
# omitting target always resolves to local.
DEFAULT_TARGET_NAME = RESERVED_LOCAL_NAME  # "local"
```

**Per-user defaults** (e.g. user prefers `home-lab` over `local`) are a future
feature; schema can add `default_target_name` on the user profile or target
table when needed.

---

## Storage: SQLite + SecureKeyStore

### SQLite (metadata)

Store in the **same deployment database** as conversations and
`deployment_access` (path from `CONVERSATION_DATABASE` / service layout).

Suggested tables (illustrative, not migration code):

- `execution_target(user_id, name, type, spec_json, created_at, updated_at)`
  — unique `(user_id, name)`.
- `spec_json` holds host, port, container, description, etc.
- **References only** for secrets, e.g. `identity_ref`, `known_hosts_ref`
  (opaque strings interpreted by `SecureKeyStore`).

Do **not** store private key bytes in SQLite unless a future store implementation
requires it.

**### SecureKeyStore (secrets and key material)**

`SecureKeyStore` abstracts **where and how credential/key material is stored and retrieved**. SQLite stores only opaque references to credentials; it does not need to know whether the underlying material is a local file, an OS-managed credential, a cloud secret, or another secure store.

The key store should **not** be responsible for deciding which Linux account a Supabase user may execute as. That authorization relationship belongs to `deployment_access` / the execution-identity layer. The caller resolves the approved `linux_username` first, then passes the resulting execution identity to the key store.

Likewise, the key store should expose **capabilities rather than assumptions about today's filesystem layout**. An implementation may use files, a secrets manager, an SSH agent, or another mechanism internally.

```python
from pathlib import Path
from typing import Protocol


class SecureKeyStore(Protocol):
    """Secure storage and retrieval of SSH key material."""

    def initialize_target(
        self,
        linux_username: str,
        target_id: str,
    ) -> None:
        """Create/provision storage needed for a target if missing."""

    def get_identity_private_path(
        self,
        linux_username: str,
        target_id: str,
    ) -> Path:
        """
        Return a path usable as an SSH IdentityFile.

        Implementations may materialize key material temporarily if their
        underlying store does not naturally expose a filesystem path.
        """

    def get_identity_public_key(
        self,
        linux_username: str,
        target_id: str,
    ) -> str:
        """Return the public SSH key suitable for authorized_keys."""

    def get_known_hosts_path(
        self,
        linux_username: str,
        target_id: str,
    ) -> Path:
        """Return a path suitable for SSH UserKnownHostsFile."""

    def generate_ed25519_key_pair(
        self,
        linux_username: str,
        target_id: str,
    ) -> str:
        """
        Generate key material and return the public key.

        The implementation controls where the private key is stored.
        """
```

The `target_id` used by the key store should be an **opaque, immutable target identifier**, not the user-facing target name. This prevents renaming a target from requiring credential paths to change and avoids treating arbitrary target names as filesystem path components.

**Default implementation: `OSSecureKeyStore`**

The initial implementation stores key material in the approved Linux user's home directory, using a private application-specific directory such as:

```text
~<linux_user>/.ai-agent/execution-targets/<target_id>/
    id_ed25519
    id_ed25519.pub
    known_hosts
```

The implementation must enforce filesystem permissions appropriate for private credential material:

* target directories: `0700`
* private keys: `0600`
* public keys: owner-readable/writable as appropriate
* `known_hosts`: owner-readable/writable as appropriate
* files and directories are owned by the approved Linux user's UID/GID
* the key-store implementation must reject or safely handle path traversal and must never allow a target identifier to escape its managed root directory

The private key must therefore be readable by the same Linux account used by `RunAsCommandExecutor` for that user's SSH commands, while remaining inaccessible to other ordinary users on the host.

`OSSecureKeyStore` resolves the Linux user's home directory from the already-approved execution identity; it does not independently decide which Linux account corresponds to a Supabase user.

**Future implementations**

Other deployments can provide alternative implementations without changing `SshExecutionTarget` or the execution-target database schema. For example:

```python
class AWSSecureKeyStore(SecureKeyStore):
    ...
```

An AWS-backed implementation might store opaque references such as secret names or ARNs in SQLite and retrieve key material from AWS Secrets Manager. A Vault-backed implementation could similarly retrieve credentials from HashiCorp Vault. Depending on the underlying provider, an implementation may materialize a short-lived private-key file or use an SSH-agent-style mechanism internally.

`SshExecutionTarget` should receive only the concrete credential material/interface it needs at build time. It must not need to know whether that material originated from the local filesystem, AWS, Vault, or another provider.

### Building a router (planned)

```python
def build_router_for_user(
    *,
    user_id: str,
    executor: CommandExecutor,
    target_repo: UserExecutionTargetRepository,
    key_store: SecureKeyStore,
) -> ExecutionTargetRouter:
    records = target_repo.list_for_user(user_id)
    targets = {"local": LocalExecutionTarget(executor)}
    for rec in records:
        if rec.type == "ssh":
            targets[rec.name] = ssh_target_from_record(rec, executor, key_store, user_id)
        elif rec.type == "docker":
            targets[rec.name] = docker_target_from_record(rec, executor)
    return ExecutionTargetRouter(targets, default_name=RESERVED_LOCAL_NAME)
```

---

## Configuration CLI and user identity

**Rule:** every execution-target mutation at the command layer must be scoped to
a **`user_id`**. There is no anonymous or “global” target edit.

**Where `user_id` comes from:**

| Context | Source |
|---------|--------|
| Operator ran `ai-agent login` on the server | Supabase session → **`sub`** for that login |
| Android (future target UI) | Same: authenticated session **`sub`** sent to a server API |
| Admin editing another user's targets | Explicit **`--user-id <uuid>`** (required when session subject differs from target owner) |

The command implementation should **require** that a subject `user_id` is
resolved before any add/list/trust operation — either from the active CLI
session or from `--user-id`. It must not infer owner from `getpass.getuser()` or
from the path of the git checkout.

Example UX (illustrative):

```bash
# After ai-agent login on the server; subject = your Supabase user id
ai-agent config execution-target list

# Admin maintaining targets for another approved user
ai-agent config execution-target add --user-id 11111111-1111-4111-8111-111111111111
```

HTTP APIs for target CRUD from mobile can mirror the same rule: JWT **`sub`**
is the default owner; admin-only routes would take an explicit owner id.

---

## Chat clients vs server (no tight coupling)

```text
  Laptop / phone                    Server (ai-agent serve)
 ┌──────────────────┐              ┌─────────────────────────────┐
 │ ai-agent (chat)  │  HTTPS/JWT   │ Per-turn: user_id → router  │
 │ Android app      │ ──────────►  │ SQLite + SecureKeyStore     │
 └──────────────────┘              └─────────────────────────────┘
        │                                      │
        │ no execution_targets.yaml            │ config execution-target
        │ no SSH keys for targets              │ (session user_id or --user-id)
        └──────────────────────────────────────┘
```

- **Default `ai-agent`** (no subcommand) uses the **remote chat client**
  (`clients/cli/ai_agent_cli/`) and talks to `/api/...` only.
- **`ai-agent config execution-target`** runs on the **server** package and
  mutates deployment data; it is not part of the chat client.
- Target policy changes belong in **server + docs**, not in Android/CLI chat
  modules.

---

## Legacy YAML (temporary)

**Current code** still uses a gitignored global file
(`execution_targets.yaml`, `AGENT_EXECUTION_TARGETS_FILE`) and helpers in
`ai_agent/execution_targets/store.py` and `ai_agent/cli/execution_target_cmd.py`.

That path is **legacy**. It will be **removed** after per-user SQLite +
`SecureKeyStore` is implemented and verified. Source files that implement YAML
are marked with comments pointing here — do not extend YAML for new features.

---

## Migration from global YAML

When legacy `execution_targets.yaml` exists on a server:

- **Do not** auto-attach it to all users.
- Provide a **one-time** admin command (e.g. import into a specific `user_id`)
  or manual re-entry.
- Until migration, document that multi-user deployments should not rely on the
  global file.

---

## Future: shared namespace and per-user defaults

- **Shared targets:** optional later `owner_kind` or separate table; admin-defined
  names visible to a group. Not in initial v2 per-user rollout.
- **Per-user default target name:** stored in SQLite; until then, omitting
  `target` means `local` only.

---

## Implementation checklist (for humans)

When implementation starts (not automated from this list):

1. Alembic migration for `execution_target` (or equivalent).
2. `SecureKeyStore` + `OSSecureKeyStore`.
3. `UserExecutionTargetRepository`; wire `build_agent` / API factory with
   `user_id`.
4. Rework `config execution-target` with required subject `user_id` from session
   or flag.
5. Remove `AGENT_DEFAULT_TARGET`, YAML default override, and global YAML path
   from production serve path.
6. Migration tool + docs update in README (link to this file).
7. Delete legacy YAML modules after soak period.
