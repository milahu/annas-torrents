{
  pkgs ? import <nixpkgs> { }
}:

pkgs.mkShell {
  buildInputs = with pkgs; [
    pixz
    ratarmount
    # nur.repos.milahu.ratarmount
    (python3.withPackages (pp: with pp; [
      packaging
      aiohttp
      torf
    ]))
  ];
}
