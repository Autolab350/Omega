#!/usr/bin/env bash
# Bootstrap the MAT stack on every Cloud Agent startup.
#
# Stack layout (four homes):
#   $STACK_ROOT/Omega/        this repo
#   $STACK_ROOT/QSConnect/   market data (`marketdata` package)
#   $STACK_ROOT/QSResearch/   strategy (`strategy` package)
#   $STACK_ROOT/QSWorkflow/   `python -m qs` + STORE
set +e

ORG="Autolab350"
MAT_REPOS=(QSConnect QSResearch QSWorkflow)
GITHUB="https://github.com/${ORG}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OMEGA_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [ -n "${MAT_STACK_ROOT:-}" ]; then
  STACK_ROOT="${MAT_STACK_ROOT}"
elif [ -d /agent/repos ] && [ -w /agent/repos ]; then
  STACK_ROOT="/agent/repos"
else
  PARENT="$(dirname "${OMEGA_ROOT}")"
  if [ -n "${PARENT}" ] && [ "${PARENT}" != "/" ] && [ -w "${PARENT}" ]; then
    STACK_ROOT="${PARENT}"
  else
    STACK_ROOT="${HOME}/mat-stack"
  fi
fi
mkdir -p "${STACK_ROOT}"

if ! command -v python >/dev/null 2>&1; then
  mkdir -p "${HOME}/.local/bin"
  ln -sf "$(command -v python3)" "${HOME}/.local/bin/python"
  echo "[mat-setup] shim: python -> $(command -v python3)"
fi

WORK_ROOT="${STACK_ROOT}"
if [ -d /agent/repos/QSConnect/.git ] || [ -d /agent/repos/QSResearch/.git ] \
  || [ -d /agent/repos/QSWorkflow/.git ]; then
  WORK_ROOT="/agent/repos"
fi

echo "[mat-setup] stack root (clones): ${STACK_ROOT}"
echo "[mat-setup] work root (editables): ${WORK_ROOT}"
echo "[mat-setup] omega root: ${OMEGA_ROOT}"

clone_repo() {
  local name="$1"
  if [ -d "/agent/repos/${name}/.git" ]; then
    echo "[mat-setup] ${name}: using /agent/repos/${name}"
    return 0
  fi
  local dest="${STACK_ROOT}/${name}"
  if [ -d "${dest}/.git" ]; then
    echo "[mat-setup] ${name}: already present at ${dest}"
    return 0
  fi
  echo "[mat-setup] ${name}: cloning into ${dest}..."
  if git clone --depth 1 "${GITHUB}/${name}.git" "${dest}" 2>/dev/null; then
    return 0
  fi
  local origin
  origin="$(git -C "${OMEGA_ROOT}" remote get-url origin 2>/dev/null)"
  if [ -n "${origin}" ]; then
    local base="${origin%/*}"
    git clone --depth 1 "${base}/${name}.git" "${dest}" 2>/dev/null && return 0
  fi
  echo "[mat-setup] ${name}: FAILED to clone" >&2
  return 1
}

for repo in "${MAT_REPOS[@]}"; do
  clone_repo "${repo}"
done

for research_dir in "${WORK_ROOT}/QSResearch" "${STACK_ROOT}/QSResearch"; do
  if [ -f "${research_dir}/.gitmodules" ]; then
    echo "[mat-setup] QSResearch: git submodule update --init (${research_dir})"
    git -C "${research_dir}" submodule update --init --recursive || true
    break
  fi
done

if [ "${OMEGA_ROOT}" != "${STACK_ROOT}/Omega" ] && [ ! -e "${STACK_ROOT}/Omega" ]; then
  ln -sf "${OMEGA_ROOT}" "${STACK_ROOT}/Omega" 2>/dev/null || true
fi

pipi() {
  local py="/usr/bin/python3"
  if ! "${py}" -c "import sys" >/dev/null 2>&1; then
    py="$(command -v python3)"
  fi
  if [ -n "${VIRTUAL_ENV:-}" ]; then
    unset VIRTUAL_ENV
  fi
  "${py}" -m pip install --user "$@" || {
    echo "[mat-setup] pip install failed: $*" >&2
    return 1
  }
}

repo_path() {
  local root="$1" name="$2"
  if [ -d "${root}/${name}" ]; then
    echo "${root}/${name}"
    return 0
  fi
  return 1
}

install_from_root() {
  local root="$1" p
  if p="$(repo_path "${root}" QSConnect)" && [ -f "${p}/pyproject.toml" ]; then
    echo "[mat-setup] editable: marketdata <- ${p}"
    pipi -e "${p}[dev]"
  fi
  if p="$(repo_path "${root}" QSResearch)" && [ -f "${p}/pyproject.toml" ]; then
    echo "[mat-setup] editable: strategy <- ${p}"
    pipi -e "${p}[dev]"
  fi
  if p="$(repo_path "${root}" Omega)" && [ -f "${p}/pyproject.toml" ]; then
    echo "[mat-setup] editable: omega <- ${p}"
    pipi -e "${p}[dev]"
  fi
  if p="$(repo_path "${root}" QSWorkflow)" && [ -f "${p}/pyproject.toml" ]; then
    echo "[mat-setup] editable: qs <- ${p}"
    pipi -e "${p}"
  fi
}

echo "[mat-setup] installing Python dependencies..."
declare -A SEEN_ROOTS=()
INSTALL_ROOTS=("${WORK_ROOT}")
if [ "${OMEGA_ROOT}" != "${WORK_ROOT}/Omega" ]; then
  INSTALL_ROOTS+=("${OMEGA_ROOT}")
fi
if ! [ -d "${WORK_ROOT}/QSConnect" ] && ! [ -d "${WORK_ROOT}/QSResearch" ]; then
  INSTALL_ROOTS+=("${STACK_ROOT}" "$(dirname "${OMEGA_ROOT}")" /workspace)
fi
for ROOT in "${INSTALL_ROOTS[@]}"; do
  [ -d "${ROOT}" ] || continue
  ROOT="$(cd "${ROOT}" 2>/dev/null && pwd)" || continue
  [ -n "${SEEN_ROOTS[${ROOT}]:-}" ] && continue
  SEEN_ROOTS["${ROOT}"]=1
  install_from_root "${ROOT}"
done

echo "${WORK_ROOT}" > "${OMEGA_ROOT}/.mat-stack-root" 2>/dev/null || true

if [ -f "${SCRIPT_DIR}/fix-editables.sh" ] && [ "${WORK_ROOT}" = "/agent/repos" ]; then
  nohup bash -c '
    for _ in $(seq 1 180); do
      [ -f /tmp/cursor/async-install/install-user.status ] && break
      sleep 1
    done
    sleep 2
    bash "'"${SCRIPT_DIR}"'/fix-editables.sh"
  ' >> /tmp/mat-fix-editables.log 2>&1 &
fi

echo "[mat-setup] verifying toolchain..."
for bin in python; do
  command -v "${bin}" >/dev/null 2>&1 && echo "[mat-setup] ok: ${bin}"
done
if command -v python >/dev/null 2>&1 && python -m qs --help >/dev/null 2>&1; then
  echo "[mat-setup] ok: python -m qs"
else
  echo "[mat-setup] WARN: python -m qs not available (install QSWorkflow editable)" >&2
fi

echo "[mat-setup] done. Work root ${WORK_ROOT}:"
ls -1 "${WORK_ROOT}" 2>/dev/null | head -20
true
