#!/bin/bash
# OCCRP Demo — run Emet locally with Ollama, no cloud APIs.
#
# Prerequisites:
#   docker compose -f docker-compose.yml -f docker-compose.field.yml up -d
#   (wait for ollama-setup to pull models — ~10 minutes first time)
#
# This script runs three demo investigations showing different capabilities.
# Uses the field deployment (Qwen3 14B + 8B, fits in 24GB RAM).

set -e
EMET="docker compose -f docker-compose.yml -f docker-compose.field.yml exec engine python -m emet.cli"

echo "============================================"
echo "  EMET — Investigative Intelligence Demo"
echo "  Cameras point UP."
echo "============================================"
echo

echo "--- Demo 1: Corporate Ownership Trace ---"
echo "Goal: Trace the ownership structure of a shell company network"
echo
$EMET investigate \
    "Trace the ownership structure of Meridian Holdings Ltd. Look for connections to offshore jurisdictions, nominee directors, and sanctioned entities." \
    --llm ollama \
    --max-turns 8 \
    --save investigations/demo_ownership.json
echo

echo "--- Demo 2: Sanctions Screening ---"
echo "Goal: Screen a list of entities against global sanctions databases"
echo
$EMET investigate \
    "Screen Viktor Renko, Elena Marchetti, Zenith Capital Partners, and Nova Offshore LLC against OpenSanctions. Check for PEP status, sanctions hits, and adverse media." \
    --llm ollama \
    --max-turns 6 \
    --save investigations/demo_sanctions.json
echo

echo "--- Demo 3: Financial Flow Analysis ---"
echo "Goal: Follow money through corporate and blockchain layers"
echo
$EMET investigate \
    "Investigate financial connections between Konrad Brauer (Luxembourg) and any entities flagged in the ICIJ Offshore Leaks database. Check for circular ownership patterns." \
    --llm ollama \
    --max-turns 8 \
    --save investigations/demo_financial.json
echo

echo "============================================"
echo "  Demo complete. Reports in ./investigations/"
echo "  Safety audit logs in each session directory."
echo "============================================"
