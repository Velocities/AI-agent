{ pkgs, textkit, ... }:
let
  py = pkgs.python3.withPackages (_ps: [ textkit ]);
in
pkgs.writeScriptBin "count-lines" ''
  #!${py}/bin/python3
  ${builtins.readFile ./count_lines.py}
''
