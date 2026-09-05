FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
# build-essential is needed only to compile py-evm's C deps; drop it afterwards.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && pip install --no-cache-dir -r requirements-dev.txt \
 && apt-get purge -y build-essential && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

COPY app ./app
COPY contracts/artifacts ./contracts/artifacts
COPY tests ./tests
COPY pyproject.toml ./

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
