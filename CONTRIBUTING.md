# Contributing to Popcorn Cube

## Prerequisites

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) package manager

### Installing uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Local Development Setup

1. **Clone the repo** (or your fork):

   ```bash
   git clone https://github.com/<your-username>/popcorn-cube.git
   cd popcorn-cube
   ```

2. **Copy the environment config**:

   ```bash
   cp config/settings/.env.example config/settings/.env
   ```

   Edit `config/settings/.env` to set a `SECRET_KEY` if desired. The defaults are fine for local development.

3. **Install dependencies**:

   ```bash
   uv sync
   ```

4. **Run database migrations**:

   ```bash
   uv run python manage.py migrate
   ```

5. **Start the development server**:

   ```bash
   uv run python manage.py runserver
   ```

   The app will be available at `http://localhost:8000`.

## Running Tests

```bash
uv run python manage.py test
```

## Submitting Changes

1. Create a feature branch from `main`.
2. Make your changes and add tests where appropriate.
3. Open a pull request against the upstream `main` branch.
