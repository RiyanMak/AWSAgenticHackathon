# Lane A: Lambda container image. Build from the repo root:
#   docker build --platform linux/arm64 -f aws/lambda/Dockerfile -t carerelay-lambda .
FROM public.ecr.aws/lambda/python:3.12

# Package source and bundled synthetic data (scenarios are read from /var/task/data)
COPY pyproject.toml README.md ${LAMBDA_TASK_ROOT}/
COPY src ${LAMBDA_TASK_ROOT}/src
COPY data/cases ${LAMBDA_TASK_ROOT}/data/cases
COPY data/output ${LAMBDA_TASK_ROOT}/data/output
COPY data/network ${LAMBDA_TASK_ROOT}/data/network
COPY data/network.py ${LAMBDA_TASK_ROOT}/data/network.py
COPY data/reference ${LAMBDA_TASK_ROOT}/data/reference

RUN pip install --no-cache-dir "${LAMBDA_TASK_ROOT}" boto3

COPY aws/lambda/handler.py ${LAMBDA_TASK_ROOT}/handler.py

ENV CARERELAY_DATA_DIR=/var/task/data
CMD ["handler.handle"]
