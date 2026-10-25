{
  description = "MCP server for VIT VTOP (vtopcc.vit.ac.in) - login, academics, leave, etc.";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      forAllSystems = nixpkgs.lib.genAttrs [ "x86_64-linux" "aarch64-linux" ];

      pythonPackages = ps: [
        ps.mcp
        ps.playwright
        ps.beautifulsoup4
        ps.pytesseract
        ps.pillow
      ];

      chromiumDetectScript = ''
        if [ -z "''${VTOP_MCP_CHROMIUM_PATH:-}" ]; then
          for bin in chromium chromium-browser google-chrome-stable google-chrome; do
            path="$(command -v "$bin" 2>/dev/null || true)"
            if [ -n "$path" ]; then
              export VTOP_MCP_CHROMIUM_PATH="$path"
              break
            fi
          done
        fi
      '';
    in
    {
      devShells = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          pythonEnv = pkgs.python3.withPackages pythonPackages;
        in
        {
          default = pkgs.mkShell {
            packages = [
              pythonEnv
              pkgs.tesseract
            ];

            shellHook = ''
              export VTOP_MCP_ROOT="$PWD"
              # Reuse whatever Chromium is already on PATH (e.g. the system/home-manager
              # one) instead of having Playwright fetch its own pinned copy -- that pulls
              # in a multi-GB multimedia dependency closure (ffmpeg/gstreamer/pipewire)
              # that's redundant if Chromium is already installed. Override with your own
              # path via VTOP_MCP_CHROMIUM_PATH if needed.
              ${chromiumDetectScript}

              if [ -n "''${VTOP_MCP_CHROMIUM_PATH:-}" ]; then
                echo "vtop-mcp dev shell ready (using Chromium at $VTOP_MCP_CHROMIUM_PATH). Run: python -m vtop_mcp"
              else
                echo "vtop-mcp dev shell ready, but no Chromium found on PATH."
                echo "Install one (e.g. 'nix profile install nixpkgs#chromium') or set VTOP_MCP_CHROMIUM_PATH,"
                echo "or add pkgs.playwright-driver.browsers back to flake.nix to let Playwright fetch its own."
              fi

              if [ ! -f "$VTOP_MCP_ROOT/config.toml" ]; then
                echo "No config.toml found -- copy config.example.toml to config.toml and fill in your VTOP username/password."
              fi
            '';
          };
        });

      apps = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          pythonEnv = pkgs.python3.withPackages pythonPackages;
          runner = pkgs.writeShellApplication {
            name = "vtop-mcp";
            runtimeInputs = [ pythonEnv pkgs.tesseract ];
            text = ''
              ${chromiumDetectScript}
              exec python -m vtop_mcp "$@"
            '';
          };
        in
        {
          default = {
            type = "app";
            program = "${runner}/bin/vtop-mcp";
          };
        });
    };
}
