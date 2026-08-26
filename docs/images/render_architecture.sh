#!/usr/bin/env bash
# ==============================================================================
# Script: render_architecture.sh
# Description: Reproducibly renders the Institutional Risk Agent Fleet architecture
#              diagram from Mermaid source (architecture.mmd) to high-resolution PNG.
# Requirements:
#   - Node.js (v18+) & npx
#   - Uses @mermaid-js/mermaid-cli (e.g. v11.16.0+)
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MMD_SRC="${SCRIPT_DIR}/architecture.mmd"
CONFIG_FILE="${SCRIPT_DIR}/mermaid-config.json"
PNG_OUT="${SCRIPT_DIR}/institutional-risk-agent-fleet-architecture.png"

# Verify prerequisites
if ! command -v npx &>/dev/null; then
    echo "Error: 'npx' is not installed or not in PATH. Please install Node.js (v18+)." >&2
    exit 1
fi

if [[ ! -f "${MMD_SRC}" ]]; then
    echo "Error: Mermaid source not found at '${MMD_SRC}'" >&2
    exit 1
fi

if [[ ! -f "${CONFIG_FILE}" ]]; then
    echo "Error: Configuration file not found at '${CONFIG_FILE}'" >&2
    exit 1
fi

echo "Rendering architecture diagram..."
echo "  Source: ${MMD_SRC}"
echo "  Config: ${CONFIG_FILE}"
echo "  Output: ${PNG_OUT}"

npx --yes @mermaid-js/mermaid-cli@11.16.0 \
    -i "${MMD_SRC}" \
    -o "${PNG_OUT}" \
    -c "${CONFIG_FILE}" \
    -s 2 \
    -b "#ffffff"

echo "Successfully rendered architecture diagram:"
ls -lh "${PNG_OUT}"
