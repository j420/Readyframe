#!/bin/sh
set -eu
kubectl rollout undo deployment/claims-agent
