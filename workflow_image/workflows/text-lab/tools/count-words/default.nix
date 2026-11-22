{ pkgs, textkit, wordnotes, ... }:
let
  py = pkgs.python3.withPackages (_ps: [ textkit wordnotes ]);
in
pkgs.writeScriptBin "count-words" ''
  #!${py}/bin/python3
  ${builtins.readFile ./count_words.py}
''
