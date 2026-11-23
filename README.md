# Module 12 Calculator API

A FastAPI calculator with user authentication, PostgreSQL storage, Docker support, and automated tests.

## Docker Hub

The published Docker image is available at:

**https://hub.docker.com/r/choreazam/601_module12**

## Run with Docker Compose

Docker Compose starts the API, PostgreSQL, and pgAdmin.

```bash
docker compose up --build
```

Open:

- Application: http://localhost:8000
- API documentation: http://localhost:8000/docs
- pgAdmin: http://localhost:5050

Default database connection:

- Host: `db`
- Database: `fastapi_db`
- Test database: `fastapi_test_db`
- Username: `postgres`
- Password: `postgres`

Stop the containers:

```bash
docker compose down
```

Remove the database volume as well:

```bash
docker compose down -v
```

## Run Locally

Requirements:

- Python 3.11+
- PostgreSQL

Create a virtual environment and install dependencies:

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Create a PostgreSQL database for local testing, then set the database URL:

```bash
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/fastapi_test_db
```

Start the API:

```bash
uvicorn app.main:app --reload
```

Open http://localhost:8000/docs.

## Run Tests Locally

Install Playwright's Chromium browser:

```bash
playwright install chromium
```

With PostgreSQL running and `DATABASE_URL` set, run all tests:

```bash
pytest
```

Run a test group:

```bash
pytest tests/unit/
pytest tests/integration/
pytest tests/e2e/
```

Keep the test database tables after a test run:

```bash
pytest --preserve-db
```

## Docker Image

Pull and run the image from Docker Hub:

```bash
docker pull choreazam/601_module12:latest
```

The compose setup is the recommended way to run the published image because it supplies PostgreSQL.

## Reflection

Development and deployment experiences, challenges, and lessons learned are documented in [REFLECTION.md](REFLECTION.md).
