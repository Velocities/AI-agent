{ pkgs, ... }:
pkgs.writeScriptBin "fetch-pages" ''
  #!${pkgs.python3}/bin/python3
  ${builtins.readFile ./fetch_pages.py}
''
