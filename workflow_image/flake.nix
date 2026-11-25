{
  description = "Tool closures for ai-agent workflow containers";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.11";

  outputs = { self, nixpkgs }:
    let
      lib = nixpkgs.lib;
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f:
        lib.genAttrs systems (system: f (import nixpkgs { inherit system; }));
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
      # One attribute per workflow directory. The attribute name is the
      # directory name, which is also the Docker build argument.
      packages = forAllSystems (pkgs:
        let
          textkit = pyLib pkgs "textkit" "0.1.0" ./nix/textkit;
          wordnotes = pyLib pkgs "wordnotes" "0.1.0" ./nix/wordnotes;
          toolArgs = { inherit pkgs textkit wordnotes; };
          workflowNames = lib.filter
            (name:
              builtins.pathExists (./workflows + "/${name}/workflow.lock.json"))
            (lib.attrNames (builtins.readDir ./workflows));
          closureFor = name:
            let
              lock = builtins.fromJSON
                (builtins.readFile (./workflows + "/${name}/workflow.lock.json"));
              paths = map
                (tool:
                  import (./workflows + "/${name}/tools/${tool.attr}") toolArgs)
                lock.tools;
            in
            pkgs.buildEnv {
              name = "workflow-${name}";
              paths = paths;
            };
        in
        lib.listToAttrs (map
          (name: {
            inherit name;
            value = closureFor name;
          })
          workflowNames)
      );
    };
}
