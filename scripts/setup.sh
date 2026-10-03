#!/bin/zsh
set -euo pipefail
PROJECT_DIR="${0:A:h:h}"
cd "$PROJECT_DIR"
if ! command -v uv >/dev/null; then
  print '请先安装 uv：https://docs.astral.sh/uv/getting-started/installation/'
  exit 1
fi
if [[ ! -x .venv/bin/python ]]; then uv venv --python 3.12 .venv; fi
uv pip install --python .venv/bin/python -e '.[test]'
print '运行环境已准备完成。执行 scripts/build.sh 构建 Mac 应用。'
