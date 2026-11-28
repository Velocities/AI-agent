"""Scaffold a new catalog tool at version 1.0.0."""

from __future__ import annotations

import re
from pathlib import Path

STARTER_VERSION = "1.0.0"
_TOOL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")
_MODULE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class CreateToolError(ValueError):
    """The tool directory was not created."""


def python_module_name(tool_name: str) -> str:
    """File name for the tool program. Hyphens in the tool name become underscores."""
    module = tool_name.replace("-", "_").replace(".", "_")
    if not _MODULE_NAME.fullmatch(module):
        raise CreateToolError(
            f"Tool name {tool_name!r} cannot become a Python file name. "
            "Start with a letter. Use letters, digits, dots, hyphens, or underscores."
        )
    return module


def create_tool(catalog: Path, name: str) -> Path:
    """Create tools/<name>/1.0.0. Refuse a name that already has a directory."""
    tool_name = name.strip()
    if not _TOOL_NAME.fullmatch(tool_name):
        raise CreateToolError(
            f"Tool name {name!r} is not valid. "
            "Start with a letter. Use letters, digits, dots, hyphens, or underscores."
        )
    module = python_module_name(tool_name)
    destination = catalog / "tools" / tool_name
    if destination.exists():
        raise CreateToolError(f"A tool named {tool_name} already exists at {destination}.")
    version_dir = destination / STARTER_VERSION
    version_dir.mkdir(parents=True)
    (version_dir / "tool.yaml").write_text(_tool_yaml(tool_name), encoding="utf-8")
    (version_dir / "default.nix").write_text(
        _default_nix(tool_name, module),
        encoding="utf-8",
    )
    (version_dir / f"{module}.py").write_text(_program(tool_name), encoding="utf-8")
    return version_dir


def _tool_yaml(tool_name: str) -> str:
    return f"""# Tool definition. Workflows pin this tool by name and version.
# They do not list the libraries below. The image build reads this file.
apiVersion: ai-agent.tool/v1
name: {tool_name}
# Latest line of this tool. The directory name and this field must match.
# Workflows that should run this code pin version {STARTER_VERSION}.
# When you freeze this line, add tools/{tool_name}/<new-version>/ and leave this directory as it is.
version: {STARTER_VERSION}
description: Replace this sentence with what the tool does.
# Libraries this tool links, from the catalog libraries/ directory.
# Leave this list out until you need one. Then uncomment and name each library:
# libraries:
#   - name: textkit
#     version: 1.0.0
nix:
  # Executable name inside the image. Keep this equal to the tool name.
  attr: {tool_name}
entrypoint: {tool_name}
interface:
  # The model sends one JSON object on stdin and the tool writes one JSON object to stdout.
  stdin: json
  stdout: json
  # Fields the model is allowed to send. Add properties here, and list the required ones.
  input:
    type: object
    required: [text]
    properties:
      text:
        type: string
  # Fields the tool must write. The agent rejects output that does not match.
  output:
    type: object
    required: [result]
    properties:
      result:
        type: string
"""


def _default_nix(tool_name: str, module: str) -> str:
    return f"""# Nix package for {tool_name}.
# The image build calls this file with pkgs and every library named in tool.yaml.
#
# This starter has no libraries, so the only argument is pkgs. The interpreter
# is the one pkgs.python3 shared by every tool in the image. Python's json
# module is already inside that interpreter. Do not run pip install or apt install here.
#
# This is where you add Nix package requirements when tool.yaml lists a library.
# Add the library name to the arguments and to withPackages, for example textkit:
#
#   {{ pkgs, textkit, ... }}:
#   let
#     py = pkgs.python3.withPackages (_ps: [ textkit ]);
#   in
#   pkgs.writeScriptBin "{tool_name}" ''
#     #!${{py}}/bin/python3
#     ${{builtins.readFile ./{module}.py}}
#   ''
{{ pkgs, ... }}:
pkgs.writeScriptBin "{tool_name}" ''
  #!${{pkgs.python3}}/bin/python3
  ${{builtins.readFile ./{module}.py}}
''
"""


def _program(tool_name: str) -> str:
    return f'''"""{tool_name} reads one JSON object from stdin and writes one JSON object to stdout.

The input fields are the input schema in tool.yaml. The output fields must
match the output schema in tool.yaml. Replace the body of main with the tool.
"""

import json
import sys


def main() -> None:
    data = json.load(sys.stdin)
    # Starter input field from tool.yaml. Change this when you change the schema.
    text = data["text"]
    if not isinstance(text, str):
        raise SystemExit("text must be a string")
    json.dump({{"result": text}}, sys.stdout)
    sys.stdout.write("\\n")


if __name__ == "__main__":
    main()
'''
