# Run from the repo root: make -C aws <target>
SHELL := /bin/bash
ROOT  := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)

.PHONY: help validate build-lambda build-agentcore push deploy-lambda deploy-agentcore streamlit portal invoke-local clean

help:
	@echo "validate         validate aws/template.yaml with CloudFormation"
	@echo "build-lambda     docker build the Lambda image locally (arm64)"
	@echo "build-agentcore  docker build the AgentCore image locally (arm64)"
	@echo "push             build and push both images to ECR"
	@echo "deploy-lambda    deploy the stack (Lane A + AgentCore role)"
	@echo "deploy-agentcore create/update the AgentCore Runtime (Lane B)"
	@echo "portal           run the patient-portal demo on :8501 (Lane C, drag PDFs in)"
	@echo "streamlit        run the minimal scenario picker on :8501 (Lane C)"
	@echo "invoke-local     run service.handle for case_001 without AWS"
	@echo "clean            delete runtime, bucket contents, stack, ECR repos"

validate:
	aws cloudformation validate-template --template-body file://$(ROOT)/aws/template.yaml >/dev/null && echo "template OK"

build-lambda:
	docker buildx build --platform linux/arm64 -f $(ROOT)/aws/lambda/Dockerfile -t carerelay-lambda:local --load $(ROOT)

build-agentcore:
	docker buildx build --platform linux/arm64 -f $(ROOT)/aws/agentcore/Dockerfile -t carerelay-agentcore:local --load $(ROOT)

push:
	$(ROOT)/aws/scripts/build_push.sh all

deploy-lambda:
	$(ROOT)/aws/scripts/deploy_lambda.sh

deploy-agentcore:
	$(ROOT)/aws/scripts/deploy_agentcore.sh

streamlit:
	cd $(ROOT) && .venv/bin/python -m streamlit run aws/streamlit/app.py --server.port 8501

portal:
	cd $(ROOT) && .venv/bin/python -m streamlit run aws/streamlit/portal.py --server.port 8501

invoke-local:
	$(ROOT)/aws/scripts/invoke.sh local case_001

clean:
	$(ROOT)/aws/scripts/cleanup.sh
