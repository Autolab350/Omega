#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OMEGA_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

WORK_ROOT="${MAT_STACK_ROOT:-}"
if [ -z "${WORK_ROOT}" ] && [ -f "${OMEGA_ROOT}/.mat-stack-root" ]; then
  WORK_ROOT="$(cat "${OMEGA_ROOT}/.mat-stack-root")"
fi
if [ -d /agent/repos/QSConnect/.git ] || [ -d /agent/repos/QSResearch/.git ]; then
  WORK_ROOT="/agent/repos"
fi
[ -n "${WORK_ROOT}" ] || exit 0

pipi() {
  local py="/usr/bin/python3"
  if ! "${py}" -c "import sys" >/dev/null 2>&1; then
    py="$(command -v python3)"
  fi
  if [ -n "${VIRTUAL_ENV:-}" ]; then
    unset VIRTUAL_ENV
  fi
  "${py}" -m pip install --user "$@"
}

editable_points_at() {
  local pkg="$1" expected="$2"
  local url
  url="$(python3 -m pip show "$pkg" 2>/dev/null | awk -F': ' '/^Editable project location:/{print $2}')"
  [ -n "${url}" ] && [ "${url}" = "${expected}" ]
}

fix_if_needed() {
  local pkg="$1" path="$2"
  [ -d "${path}" ] || return 0
  if editable_points_at "${pkg}" "${path}"; then
    echo "[fix-editables] ${pkg}: ok (${path})"
    return 0
  fi
  echo "[fix-editables] ${pkg}: rebinding -> ${path}"
  pipi -e "${path}"
}

echo "[fix-editables] work root: ${WORK_ROOT}"

[ -f "${WORK_ROOT}/QSConnect/pyproject.toml" ] && fix_if_needed marketdata "${WORK_ROOT}/QSConnect"
[ -f "${WORK_ROOT}/QSResearch/pyproject.toml" ] && fix_if_needed strategy "${WORK_ROOT}/QSResearch"
[ -f "${WORK_ROOT}/Omega/pyproject.toml" ] && fix_if_needed omega "${WORK_ROOT}/Omega"
[ -f "${WORK_ROOT}/QSWorkflow/pyproject.toml" ] && fix_if_needed qs "${WORK_ROOT}/QSWorkflow"

echo "${WORK_ROOT}" > "${OMEGA_ROOT}/.mat-stack-root" 2>/dev/null || true
echo "[fix-editables] done"
