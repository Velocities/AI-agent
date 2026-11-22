# Workflow image definitions

This directory (`workflow_image/`) is the Docker build context for workflow
containers: the shared `Dockerfile`, Nix flake, and per-workflow manifests.
It is not the same thing as the SSH key sandbox under `.ai-agent/ssh/`.

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
cd workflow_image
nix --extra-experimental-features 'nix-command flakes' build .#packages.x86_64-linux.text-lab
```

Build the image with BuildKit. On Ubuntu the package is `docker-buildx`
(`sudo apt install docker-buildx`), which also installs Docker. The systemd
installer installs that package when the plugin is missing. Docker skips this
layer when the workflow sources and the `WORKFLOW` argument are unchanged.
If the tag is already present, skip the build and start a container:

```bash
docker buildx build --load --build-arg WORKFLOW=text-lab --build-arg NIX_SYSTEM=x86_64-linux \
  -t ai-agent-workflow:text-lab workflow_image
```

The agent tags images as `ai-agent-workflow:<name>-<fingerprint>`. The
fingerprint covers the lock, the Nix expressions, the shared libraries, and
the Dockerfile.
It ignores session parameters. Preparation behaves like a Makefile rule: if
that tag is already in the local engine (`docker image inspect`), the build
is skipped; otherwise the broker builds once and later sessions reuse the
same image. Each conversation still gets its own container instance. The chat
can take a message only after the container is ready.

Run a container. Replace the sleep directory with a path under the workflow
sleep root, not a home directory. The daemon must run with
`"userns-remap": "default"` in `/etc/docker/daemon.json` so root inside the
container is an ordinary uid on the host. That is a daemon setting, not a
`docker run` flag; the installer turns it on. Because container root is that
remapped uid, the sleep directory has to be mode `0777` (its parent stays
`2770`, so other host users still cannot reach it).

```bash
mkdir -p -m 0777 /var/lib/ai-agent/workflow-sleep/demo
docker run -d --name text-lab-demo \
  --security-opt no-new-privileges \
  --cap-drop SYS_ADMIN \
  --pids-limit 256 \
  --network bridge \
  --mount type=bind,source=/var/lib/ai-agent/workflow-sleep/demo,target=/work \
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

## Host policy vs the container

`default_policy.yaml` and command approval apply to **host** execution targets
(`local`, SSH remotes, and similar). They do **not** gate what runs inside a
workflow container.

Inside each workflow container, confinement is:

- one container per chat, with `/work` as the writable tree
- `docker exec` planning and a broker whitelist on the host
- manifest tools (`run_tool`) whose entrypoints come from the lock file, not
  from free-form model argv

The model may use `run_command`, `run_commands`, and `run_tool` against the
`workflow` target without host confirmation prompts. That is intentional: risk
is isolated to the container user namespace and network namespace Docker
gives the workflow image, not to the `ai` API user's host shell.

Copying artifacts from `/work` onto the host is still a separate promotion step
with its own confirmation.

From the agent, bind a session and pass it to `build_agent`. The model then
sees only the `workflow` target and `run_tool` for `count-lines` and
`count-words`:

```python
from pathlib import Path
from ai_agent.agent.factory import build_agent
from ai_agent.workflows.session import bind_workflow

session = bind_workflow(
    Path("workflow_image"),
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

## Example: product-ideas

`fetch-pages` is a separate tool with its own Python. It does not use
`textkit`. One call takes up to 16 public URLs and fetches them together
(8 at a time, at most 4 to one host). It returns a short `excerpt` per page
plus clipped `text` for the agent (`run_tool` forwards only parsed JSON, not
raw stdout). Reddit listing
JSON, Arctic Shift post JSON, Lobsters stories, and Hacker News search
JSON become titles and posts. A login wall is reported as a failed page.

The workflow asks the user five questions first: time, product shape,
audience, domain, and one constraint. Those answers are not image inputs.
Build it the same way, with a different workflow name:

```bash
cd workflow_image
nix --extra-experimental-features 'nix-command flakes' build .#packages.x86_64-linux.product-ideas
docker buildx build --load --build-arg WORKFLOW=product-ideas --build-arg NIX_SYSTEM=x86_64-linux \
  -t ai-agent-workflow:product-ideas workflow_image
```

From a client, start it with `/workflow product-ideas` or the Android
Workflow button. The model then uses `fetch-pages`, for example:

```bash
docker exec -i PRODUCT_CONTAINER fetch-pages <<'EOF'
{"urls":["https://hn.algolia.com/api/v1/search?query=inventory&tags=comment&hitsPerPage=5"]}
EOF
```

