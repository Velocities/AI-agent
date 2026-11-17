# Workflow sandbox

One generic image build, one container per workflow session. Tools are Nix
packages. Personalization is a file the host writes at start, not a Docker
layer.

## Layout

```text
flake.nix                          shared package set
nix/textkit/                       library both example tools import
nix/wordnotes/                     library only count-words imports
workflows/<name>/workflow.yaml     name, version, prompt, parameters, tools
workflows/<name>/workflow.lock.json
workflows/<name>/tools/<tool>/tool.yaml
workflows/<name>/tools/<tool>/default.nix
Dockerfile                         reads WORKFLOW and builds that closure
```

`workflow.yaml` is the authoring file. `workflow.lock.json` is what Nix
reads: tool name, version, Nix attribute, and entrypoint. It does not
include `parameters` or `initial_prompt`. The agent checks the lock against
the YAML and refuses to build when they differ.

A tool's `default.nix` is the package. It receives the shared libraries
(`textkit`, `wordnotes`) and returns one executable. Tools do not import
each other.

## Example: text-lab

`count-lines` and `count-words` both use `textkit`, so that store path is
built once. `count-words` also uses `wordnotes`, so its Python environment
is a different store path.

Build the closure on the host when Nix is installed. Later workflow builds
reuse the same `textkit` store path:

```bash
cd sandbox
nix --extra-experimental-features 'nix-command flakes' build .#packages.x86_64-linux.text-lab
```

Build the image. Docker skips this layer when the workflow sources and the
`WORKFLOW` argument are unchanged. If the tag is already present, skip the
build and start a container:

```bash
docker build --build-arg WORKFLOW=text-lab --build-arg NIX_SYSTEM=x86_64-linux \
  -t ai-agent-workflow:text-lab sandbox
```

The agent tags images as `ai-agent-workflow:<name>-<fingerprint>`. The
fingerprint covers the lock, the Nix expressions, and the shared libraries.
It ignores session parameters.

Run a container. Replace the sleep directory with a path under the workflow
sleep root, not a home directory. The daemon needs a user namespace named
`default` (`userns-remap` in `/etc/docker/daemon.json`) so root inside the
container is an ordinary uid on the host.

```bash
mkdir -p /var/lib/ai-agent/workflow-sleep/demo
docker run -d --name text-lab-demo \
  --userns=default \
  --security-opt no-new-privileges \
  --cap-drop SYS_ADMIN \
  --pids-limit 256 \
  --network bridge \
  --mount type=bind,source=/var/lib/ai-agent/workflow-sleep/demo,target=/work,rw \
  ai-agent-workflow:text-lab \
  sleep infinity

docker exec -i text-lab-demo count-lines <<'EOF'
{"text":"one\ntwo"}
EOF

docker exec -i text-lab-demo count-words <<'EOF'
{"text":"one two three"}
EOF
```

Expect `{"lines": 2}` and `{"words": 3, "notable": 1}`.

Session parameters are applied by writing `/work/session.json` after the
container starts, for example `{"label": "north-office"}`. That write does
not rebuild the image.

From the agent, bind a session and pass it to `build_agent`. The model then
sees only the `sandbox` target and `run_tool` for `count-lines` and
`count-words`:

```python
from pathlib import Path
from ai_agent.agent.factory import build_agent
from ai_agent.workflows.session import bind_workflow

session = bind_workflow(
    Path("sandbox"),
    "text-lab",
    linux_username="alice",
    container_name="text-lab-demo",
    sleep_dir=Path("/var/lib/ai-agent/workflow-sleep/demo"),
    parameters={"label": "north-office"},
)
agent = build_agent(workflow_session=session)
```

`bind_workflow` checks the container spec and does not start Docker. Start
the container with `session.spec.run_argv()` before the model runs commands.

