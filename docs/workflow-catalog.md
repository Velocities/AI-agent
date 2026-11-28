# Workflow catalog

Tools and libraries are defined outside workflows. A workflow pins the versions it uses. The image build installs each pinned library version once and every tool in that image references that copy. `1.0.0` is the current line for every tool and library that ships today: edit those directories in place until a change is ready to freeze, then add the next version directory and move a workflow's pin.

## Layout

The catalog root contains definitions only. The Dockerfile and `flake.nix` stay with the engine, in `workflow_image/` of this repository.

```text
catalog/
  tools/fetch-pages/1.0.0/          tool.yaml, default.nix, source
  tools/count-lines/1.0.0/
  tools/count-words/1.0.0/
  libraries/textkit/1.0.0/
  libraries/wordnotes/1.0.0/
  workflows/product-ideas/          workflow.yaml, workflow.lock.json
  workflows/text-lab/
```

Development uses `workflow_image/` in this checkout as the catalog, which is why the engine files sit beside the definitions there. An installed server uses `/var/lib/ai-agent/catalog` and does not read the checkout for definitions.

A workflow names tools:

```yaml
tools:
  - name: fetch-pages
    version: 1.0.0
```

A tool names the libraries it links in its own `tool.yaml`. `fetch-pages` names none. `count-words` names `textkit` and `wordnotes`. The workflow lock names tools only. The image build reads each tool definition and installs those libraries. One image cannot install two versions of the same library name, because the Nix function argument is the library name.

Standard-library modules such as Python's `json` are not catalog entries. They are part of the interpreter. A tool that needs them pins the interpreter by using the one `pkgs.python3` the image build provides.

## One install, shared by reference

The staged build has one nixpkgs pin and one evaluation. The flake builds each library version once, then passes that derivation into every tool that pins it. Nix stores the result at one path. A second tool that receives the same derivation gets another reference, not a second copy.

`count-lines` and `count-words` both pin `textkit` `1.0.0`, so the image contains one `textkit`. Each tool still has its own small environment wrapper when its library sets differ. Those wrappers are symlink farms. The interpreter and `textkit` paths inside them are the shared ones. `fetch-pages` uses `pkgs.python3` directly, which is the same interpreter the wrappers reference, so `import json` in any of these tools loads the module from that one interpreter.

A second workflow image contains its own copy of those store paths. The host Nix cache still builds a given derivation once.

The Docker context for a build is a staged directory, `<catalog>/.build/<workflow>-<fingerprint>/`, containing the engine Dockerfile, the engine flake, that workflow's lock, the tools it names, and the libraries those tools declare. The image tag changes when those inputs change. The prompt and session parameters are not part of the hash. While `1.0.0` is still being edited, the next image build of a workflow that pins it follows the new bytes. A container that is already running keeps the image it started with.

## Install

`deploy/systemd/install.sh` creates `/var/lib/ai-agent/catalog` and `.build` under it, group-writable by the `ai` group so the API user can stage builds and the broker user can read them. The installer writes `WORKFLOW_CATALOG_ROOT=/var/lib/ai-agent/catalog` into `.env` when that line is missing. The API reads `.env`. The broker unit gets the same path as `--workflow-image-root`. `ai-agent catalog pull` from the checkout uses the `.env` value, so it updates the installed catalog.

On an empty catalog the installer clones `WORKFLOW_CATALOG_URL` when that variable is set and `git` is available. Otherwise it copies `tools/`, `libraries/`, and `workflows/` from this checkout. A catalog that already has workflows is left alone.

## Pull

`ai-agent catalog pull` fetches the catalog git repository. The catalog directory must be its own git checkout. The command refuses a directory that is the agent repository.

Without `--force`:

- A version or workflow that is not on disk yet is installed by the fetch.
- Tracked files update when the local checkout can fast-forward.
- Modified tracked files are left in place. The command lists them and exits non-zero.
- Untracked files, including a workflow or tool that exists only on this machine, stay either way.
- Nothing is rebuilt and no container is restarted.

`ai-agent catalog pull --force` replaces tracked files with the upstream catalog even when they have local edits or the branch is not a fast-forward. Untracked files stay. Use this while several people are still changing directories named `1.0.0` and you need the latest bytes to test. When a line is finished, add a new version directory and point the workflows that should move at that version. Pulling will not change a workflow that remains pinned to the old directory.

`--force` discards uncommitted edits and local commits on tracked files. It does not delete untracked work.
