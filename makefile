.PHONY: build push run-migrations deploy-api release db-proxy set-config

ENV ?= staging

ifeq ($(ENV),staging)
PROJECT_ID := chatcare-co
ACCOUNT := supatest-staging-deploy@chatcare-co.iam.gserviceaccount.com
KEY_FILE := staging-deploy-svc-acc.json
AGENT_IMAGE := asia-south1-docker.pkg.dev/$(PROJECT_ID)/browser-use-agent/image
else ifeq ($(ENV),prod)
PROJECT_ID := supatest-ai
ACCOUNT := prod-deploy@supatest-ai.iam.gserviceaccount.com
KEY_FILE := prod-deploy-svc-acc.json
AGENT_IMAGE := asia-southeast1-docker.pkg.dev/$(PROJECT_ID)/browser-use-agent/image
else
$(error Invalid ENV value. Must be 'staging' or 'prod')
endif

REGION := asia-southeast1
AGENT_SERVICE_NAME := browser-use-agent

set-config:
	gcloud auth activate-service-account $(ACCOUNT) --key-file=$(KEY_FILE)
	gcloud auth configure-docker asia-south1-docker.pkg.dev
	gcloud auth configure-docker asia-southeast1-docker.pkg.dev
	gcloud config set project $(PROJECT_ID)
	gcloud config set account $(ACCOUNT)

build:
	docker build -f Dockerfile -t $(AGENT_IMAGE) --platform linux/amd64 .

push:
	docker push $(AGENT_IMAGE)


deploy-agent: set-config
	gcloud run deploy $(AGENT_SERVICE_NAME) \
		--image $(AGENT_IMAGE) \
		--region $(REGION)

release-agent: set-config build push deploy-agent