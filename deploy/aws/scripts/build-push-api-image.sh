#!/usr/bin/env sh
set -eu

AWS_REGION="${AWS_REGION:?Set AWS_REGION before running this script.}"
PROJECT_NAME="${PROJECT_NAME:-tailwag-memory}"
ENVIRONMENT_NAME="${ENVIRONMENT_NAME:-dev}"
ECR_REPOSITORY="${ECR_REPOSITORY:-${PROJECT_NAME}-${ENVIRONMENT_NAME}-api}"

if [ -z "${AWS_ACCOUNT_ID:-}" ]; then
  AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
fi

if [ -z "${IMAGE_TAG:-}" ]; then
  IMAGE_TAG="$(git rev-parse --short HEAD 2>/dev/null || printf local)"
fi

REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
IMAGE_URI="${TAILWAG_API_IMAGE_URI:-${REGISTRY}/${ECR_REPOSITORY}:${IMAGE_TAG}}"

if ! aws ecr describe-repositories --region "$AWS_REGION" --repository-names "$ECR_REPOSITORY" >/dev/null 2>&1; then
  aws ecr create-repository --region "$AWS_REGION" --repository-name "$ECR_REPOSITORY" >/dev/null
fi

aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY"

docker build -t "$IMAGE_URI" .
docker push "$IMAGE_URI"

printf '%s\n' "$IMAGE_URI"
