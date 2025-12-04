# GitHub Copilot Instructions - aiotractive

## Project Overview

This workspace contains **two distinct projects**:
1. **aiotractive**: An async Python client library for Tractive GPS pet trackers (`/aiotractive/`)
2. **Home Assistant Core**: A complete fork used for integration development (`/core/`)

When working on code, determine which project you're in and apply the appropriate conventions.

## aiotractive Library (`/aiotractive/`)

### Architecture

**Client Layers** (thin wrappers, minimal logic):
- `Tractive` - Main entry point, async context manager, orchestrates API calls
- `API` - Low-level HTTP client with auth, retries (exponential backoff: `4^attempt + random(0,3)`), rate limiting (429 handling)
- `Tracker` / `TrackableObject` - Domain objects wrapping API endpoints
- `Channel` - WebSocket-style event streaming with keep-alive monitoring

**Key Patterns**:
- User credentials cached until 1 hour before expiry (`expires_at - time.time() < 3600`)
- All operations return raw API responses (dicts/lists) - no domain models
- Session management: Accepts external `aiohttp.ClientSession` or creates/manages own
- DataObject base class stores `_id` and `_type` from Tractive API responses
- **Multi-API support**: Two base URLs - `graph.tractive.com/3/` (main) and `aps-api.tractive.com/api/1/` (health/activity)

### Development Workflow

**Linting & Formatting** (run before commits):
```bash
pipenv run make         # Runs: black, isort, pylint, flake8
pipenv run make format  # Auto-fixes: black + isort
```

**Key Standards**:
- Line length: 120 characters (`pyproject.toml` + `.pylintrc`)
- Python 3.10+ (check `Pipfile` for target version)
- Use `black` for formatting, `isort` for import sorting
- No tests currently in repo - manual testing via usage examples

**CI Pipeline** (`.github/workflows/ci.yml`):
- Runs linters on every push/PR
- Auto-publishes to PyPI on tagged releases (requires `secrets.pypi_token`)

### Error Handling Conventions

**Exception Hierarchy** (`exceptions.py`):
```python
TractiveError              # Base - wrap all unknown errors
├── UnauthorizedError     # 401/403 responses
├── NotFoundError         # 404 responses  
└── DisconnectedError     # Channel keep-alive timeout
```

**Wrapping Pattern** (`api.py:request()`):
- All `ClientResponseError` converted to custom exceptions
- Broad `except Exception` → `TractiveError` for resilience
- Rate limit (429): Auto-retry with exponential backoff up to `retry_count` attempts

### API Client Patterns

**Authentication** (`API.authenticate()`):
- Lazy auth: Only authenticates on first request
- Token refresh: Auto-refreshes 1 hour before expiry
- Headers: `x-tractive-client` (client_id), `x-tractive-user` (user_id), `authorization` (Bearer token)

**Retry Logic** (`API.raw_request()`):
- Only retries on 429 (rate limit)
- Default: 3 attempts with `4^attempt + random(0,3)` second delays
- Logs retry attempts at INFO level

**Channel Events** (`Channel.listen()`):
- Long-polling HTTP connection to `channel.tractive.com`
- Keep-alive monitoring: Disconnects if no message for 60 seconds
- Ignores: `handshake`, `keep-alive` messages
- Yields only `event` messages to caller
- Background tasks: `_listen()` reads stream, `_check_connection()` monitors keep-alives

**Multi-API Pattern** (Issue #39):
- Main API: `graph.tractive.com/3/` - Use `api.request()` for trackers, trackable objects, positions
- APS API: `aps-api.tractive.com/api/1/` - Use `api.aps_request()` for health/activity data
- Same authentication headers work for both APIs
- Health overview (`TrackableObject.health_overview()`) replaced deprecated `wellness_overview` channel event
- Must be explicitly fetched via HTTP (not auto-published on channel open like old API)

### Common Tasks

**Adding New Tracker Commands**:
1. Add method to `Tracker` class following pattern:
   ```python
   async def set_feature_active(self, active):
       action = self.ACTIONS[active]  # "on" or "off"
       return await self._api.request(f"tracker/{self._id}/command/feature/{action}")
   ```
2. Update README.md usage examples

**Adding New API Endpoints**:
1. For tracker-related: Add method to `Tracker` class
2. For pet-related: Add method to `TrackableObject` class  
3. For user-level: Add method to `Tractive` class
4. Choose the right API method:
   - `await self._api.request(url)` - For graph.tractive.com endpoints (default)
   - `await self._api.aps_request(url)` - For aps-api.tractive.com endpoints (health/activity)
5. Example health endpoint: `await self._api.aps_request(f"pet/{self._id}/health/overview")`

**Session Management**:
- Constructor accepts `session` param for external session sharing
- Sets `_close_session = False` when using external session
- Only calls `session.close()` if library created the session

## Home Assistant Core (`/core/`)

See the comprehensive `.github/copilot-instructions.md` in `/core/` for detailed guidance.

**Quick Integration Development**:
1. Integration code: `core/homeassistant/components/{domain}/`
2. Tests: `core/tests/components/{domain}/`
3. Run tests: `pytest ./tests/components/{domain} --cov=homeassistant.components.{domain} --cov-report term-missing`
4. Validate: `python -m script.hassfest --integration-path homeassistant/components/{domain}`

**Key HA Patterns for Tractive Integration**:
- Use `DataUpdateCoordinator` for polling tracker data
- Store `Tractive` client in `ConfigEntry.runtime_data`
- Handle `UnauthorizedError` → raise `ConfigEntryAuthFailed` for reauth flow
- Map tracker/pet IDs to unique device identifiers
- Use `Channel.listen()` for real-time event updates (battery, location, status changes)
- Fetch `health_overview()` on startup for initial activity/sleep data (not auto-published like deprecated `wellness_overview`)
- Support both `wellness_overview` (deprecated) and `health_overview` events during transition period

## Context Switching

**You're in aiotractive if**: Path contains `/aiotractive/aiotractive/` or working on library code
**You're in Home Assistant if**: Path contains `/core/homeassistant/` or working on integration code

Apply the appropriate standards for each project - they have different conventions!
