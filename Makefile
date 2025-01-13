SRC_DIR = .
DOCKER_REGISTRY=harbor.lamodatech.ru/apps/qa/tools
APP_NAME=k8s-deployments-cleaner

VERSION ?= $(shell git describe --tags || git rev-parse --short HEAD)
GIT_SHA = $(shell git rev-parse HEAD)
GIT_UPSTREAM = $(shell git remote | grep upstream || echo "origin")

DOCKERFILE=Dockerfile
export TAG=$(DOCKER_REGISTRY)/${APP_NAME}:$(VERSION)
TAG_LATEST=$(DOCKER_REGISTRY)/${APP_NAME}:latest


@build:
	docker build \
	    --platform=linux/amd64 \
		--build-arg VERSION=${VERSION} \
		--build-arg GIT_SHA=$(GIT_SHA) \
		--tag ${TAG} \
		--file ${DOCKERFILE} \
		.

@push:
	docker tag ${TAG} ${TAG_LATEST}
	docker push ${TAG}
	docker push $(TAG_LATEST)
