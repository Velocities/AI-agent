{
  description = "One workflow closure. Library pins are read from each tool.";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.11";

  outputs = { self, nixpkgs }:
    let
      lib = nixpkgs.lib;
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f:
        lib.genAttrs systems (system: f (import nixpkgs { inherit system; }));
      # One nixpkgs evaluation for the image. pkgs.python3 is therefore one
      # derivation. Library packages and tool environments reference it;
      # they do not install a second interpreter. Python's json module lives
      # in that interpreter, so tools that import json share it too.
      pyLib = pkgs: name: version: src:
        pkgs.python3.pkgs.buildPythonPackage {
          pname = name;
          inherit version src;
          pyproject = false;
          dontBuild = true;
          installPhase = ''
            mkdir -p "$out/${pkgs.python3.sitePackages}"
            cp ${name}.py "$out/${pkgs.python3.sitePackages}/${name}.py"
          '';
        };
    in
    {
      packages = forAllSystems (pkgs:
        let
          lock = builtins.fromJSON (builtins.readFile ./workflow.lock.json);
          # Each tool.yaml owns its library pins. The stage writes libraries.json
          # from that file so Nix can read them without the workflow repeating them.
          toolLibraries = tool:
            builtins.fromJSON (builtins.readFile (
              ./tools + "/${tool.name}/${tool.version}/libraries.json"
            ));
          grouped = lib.groupBy (pin: pin.name) (
            lib.concatMap toolLibraries lock.tools
          );
          clashNames = lib.attrNames (lib.filterAttrs (_name: pins:
            lib.length (lib.unique (map (pin: pin.version) pins)) > 1
          ) grouped);
          # Keyed by library name. Every tool that pins this version receives
          # the same derivation, so the closure stores it once.
          built = lib.mapAttrs (name: pins:
            let pin = builtins.head pins; in
            pyLib pkgs name pin.version (./libraries + "/${name}/${pin.version}")
          ) grouped;
          paths = map (tool:
            let
              args = { inherit pkgs; } // lib.genAttrs
                (map (pin: pin.name) (toolLibraries tool))
                (name: built.${name});
            in
            import (./tools + "/${tool.name}/${tool.version}") args
          ) lock.tools;
        in
        if clashNames != [] then
          throw "Tools in this image request two versions of ${lib.concatStringsSep ", " clashNames}"
        else {
          ${lock.name} = pkgs.buildEnv {
            name = "workflow-${lock.name}";
            paths = paths;
          };
        }
      );
    };
}
