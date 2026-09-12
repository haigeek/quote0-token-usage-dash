#!/usr/bin/env bash
#
# Build the linux/amd64 image and push it to a container registry.
#
#   ./build.sh              # build linux/amd64 and push :latest
#   ./build.sh --tag v1.2   # build and push with an extra tag
#   ./build.sh --no-push    # build into the local Docker only
#
# The registry below is a placeholder. Set your own either by editing this
# line or by exporting REGISTRY when invoking the script:
#
#   REGISTRY=registry.example.com/team/my-image ./build.sh
#
# Run `docker login <your-registry>` first.
#
set -euo pipefail

REGISTRY="${REGISTRY:-registry.example.com/your-namespace/your-image}"
TAG="latest"
PLATFORM="linux/amd64"
PUSH=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag)      TAG="$2"; shift 2 ;;
    --platform) PLATFORM="$2"; shift 2 ;;
    --registry) REGISTRY="$2"; shift 2 ;;
    --no-push)  PUSH=0; shift ;;
    -h|--help)  sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

cd "$(dirname "$0")"

if [[ "$REGISTRY" == *"example.com"* && "$PUSH" == "1" ]]; then
  echo "Error: REGISTRY is still the placeholder ($REGISTRY)." >&2
  echo "Set your own with --registry, the REGISTRY env var, or by editing build.sh." >&2
  exit 1
fi

IMAGE="$REGISTRY:$TAG"
echo "==> Building $IMAGE ($PLATFORM)"

# --provenance=false --sbom=false with oci-mediatypes=false: some registries
# (e.g. Aliyun ACR) reject the OCI manifest list and attestation descriptors
# BuildKit emits by default ("unknown manifest class for
# application/vnd.oci.empty.v1+json"). Docker media types push cleanly.
docker buildx build \
  --platform "$PLATFORM" \
  --provenance=false \
  --sbom=false \
  -t "$IMAGE" \
  $(if [[ "$PUSH" == "1" ]]; then
      echo "--output type=image,name=$IMAGE,push=true,oci-mediatypes=false"
    else
      echo "--load"
    fi) \
  .

echo
if [[ "$PUSH" == "1" ]]; then
  echo "Pushed: $IMAGE"
else
  echo "Built locally as: $IMAGE"
fi
