#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python3 tools/validate_v4.py
python3 tools/validate_data.py
python3 -m unittest discover -s tests -p 'test_*.py'

for source in \
  tools/play_v4/game.js \
  tools/play_v4/space-environment.js \
  tools/play_v4/components/ship-hex-token.js \
  demo/main.js \
  demo/board3d.js \
  demo/components/ship-hex-token.js \
  browser-demo/dist/main.js \
  browser-demo/dist/board3d.js \
  browser-demo/dist/components/ship-hex-token.js; do
  node --check "$source"
done

cargo test --release --manifest-path rust/game_core/Cargo.toml
godot --headless --path . --script res://tools/run_tests.gd
