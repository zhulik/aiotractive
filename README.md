## aiotractive
[![Continuous Integration](https://img.shields.io/github/actions/workflow/status/zhulik/aiotractive/ci.yml?branch=main&label=Continuous%20Integration&logo=github&style=popout)](https://github.com/zhulik/aiotractive/actions/workflows/ci.yml?query=branch%3Amain)

**Unofficial** Asynchronous Python client for the [Tractive](https://tractive.com) REST API.

**This project and its author are not affiliated with Tractive GmbH**

This project is a result of reverse engineering of the Tractive web app.

Inspired by [home_assistant_tractive](https://github.com/Danielhiversen/home_assistant_tractive).

Initially some code was borrowed from home_assistant_tractive, but in the end all of it was replaced with my own implementations.

The package is in active development. **Not all features available in the Tractive web app are implemented.**

Important notes:

- In order to use Tractive devices and their service you need to have an active subscription.
- Tractive may change their API at any point of time and this project will be broken. Please, report any issues.

## Installation

`pip install aiotractive`

## Usage

```python
import asyncio

from aiotractive import Tractive


async def main():
    async with Tractive("email", "password") as client:
        # interact with the client here
        pass


if __name__ == "__main__":
    asyncio.run(main())
```


### Tractive

Tractive is the entrypoint class, it acts as an async context manager and provides access to API endpoints.

#### Authentication

```python
client.authenticate()

# {'user_id': 'user_id', 'client_id': 'client_id', 'expires_at': 1626821491, 'access_token': 'long access token'}
```

#### Trackers

```python
trackers = await client.trackers()
tracker = trackers[0]

# Or

tracker = client.tracker("TRACKER_ID")

# Retrieve details
# Includes device capabilities, battery status (not level), charging state and so on
await tracker.details()

await tracker.hw_info()  # Includes battery level, firmware version, model and so on

# Retrieve current location
await tracker.pos_report()  # Includes coordinates, latitude, speed and so on

# Retrieve history positions
now = datetime.timestamp(datetime.now())
time_from = now - 3600 * LAST_HOURS
time_to = now
fmt = "json_segments"
await tracker.positions(time_from, time_to, fmt)

# Control the buzzer
await tracker.set_buzzer_active(True)  # or False

# Control the LED
await tracker.set_led_active(True)  # or False

# Control the live tracking
await tracker.set_live_tracking_active(True)  # or False
```

#### Trackable objects (usually pets)
```python
objects = await client.trackable_objects()
obj = objects[0]

# Or get a specific trackable object by ID
obj = client.trackable_object("TRACKABLE_ID")

# Retrieve details
await obj.details()  # Includes pet's name, pet's tracker id and so on

# Retrieve health overview (activity, sleep, rest, and health metrics)
await obj.health_overview()
```

#### Events

```python
async for event in client.events():
    pp(event)
```

After connecting you will immediately receive one `tracker_status` event per owned tracker.
The first event always includes full current status of the tracker including current position, battery level, states of the buzzer,
the LED and the live tracking.

All following events will have the same name, but only include one of these: either a position, battery info, or a buzzer/LED/live
status.

#### Status and push updates

The client can keep a typed, merged status of every tracker and pet, filled from REST and kept
current by the event channel.

```python
async with Tractive("email", "password", fetch_delay=2.0) as client:
    trackables = await client.async_fetch_trackables()  # pets with an owned tracker
    for trackable in trackables:
        print(trackable.name, trackable.pet_id, trackable.tracker_id)

    # Refresh via REST, returns client.status
    status = await client.async_fetch_status()
    tracker_status = status.trackers[trackables[0].tracker_id]
    print(tracker_status.battery_level, tracker_status.latitude)

    def on_update(error: Exception | None) -> None:
        if error is None:
            print("status changed or channel (re)connected", client.status)
        else:
            print("channel error", error)

    client.subscribe_updates(on_update)
    listener = asyncio.create_task(client.listen())
    ...
    listener.cancel()
```

- `async_fetch_trackables()` returns a list of `Trackable` (`pet_id`, `tracker_id`, `pet_details`,
  `tracker_details`, `name`, `weight` in grams) and caches it. Pets without a tracker and shared
  trackers (no details) are skipped; a tracker without an `_id` raises `TractiveError`.
- `async_fetch_status()` refreshes every trackable via REST (fetching trackables first if
  needed) and returns `client.status`. Values are merged, so switch states received from events
  are kept.
- `client.status` is a `TractiveStatus` with `trackers: dict[str, TrackerStatus]` and
  `pets: dict[str, PetStatus]`, keyed by tracker ID and pet ID.
  - `TrackerStatus`: `battery_level`, `tracker_state`, `battery_charging`, `power_saving`,
    `power_saving_zone`, `latitude`, `longitude`, `accuracy`, `sensor_used`, `buzzer`, `led`,
    `live_tracking`.
  - `PetStatus`: `daily_goal`, `minutes_active`, `minutes_day_sleep`, `minutes_night_sleep`,
    `minutes_rest`.
  - Unknown values are `None`. Switch states (`buzzer`, `led`, `live_tracking`) are only
    available from events.
- `subscribe_updates(listener)` registers a callback. It is called with `None` when the status
  changed or the channel (re)connected, and with an exception on a channel error: a
  `TractiveError` is transient and the channel reconnects automatically after 10 seconds, an
  `UnauthorizedError` is terminal and stops listening.
- `listen()` consumes events and updates `client.status` until cancelled. Run it as a task and
  cancel it to stop, or use `await client.async_start_listener()` /
  `await client.async_stop_listener()`, which do that for you (`close()` stops it too).
- `fetch_delay` (default `2.0` seconds) is the pause between the REST requests of consecutive
  trackables, to avoid HTTP 429 (too many requests) responses.
- Trackers returned by `client.tracker()` and `client.trackers()` are bound to `client.status`:
  when a `set_buzzer_active`, `set_led_active` or `set_live_tracking_active` command is
  accepted, the switch state is updated optimistically before the confirming event arrives.

## Exceptions

The library raises the following exceptions:

- `TractiveError` - Base exception class
- `UnauthorizedError` - When authentication fails or token is invalid
- `ForbiddenError` - When access to a resource is denied (403), e.g. the health overview of a pet whose tracker subscription is inactive. Authentication and the event channel report 403 as `UnauthorizedError`
- `BadRequestError` - When the server rejects the request (400)
- `NotFoundError` - When the requested resource is not found (404)
- `DisconnectedError` - When the event channel disconnects

## Type Hints

This library is fully typed and includes a `py.typed` marker for [PEP 561](https://peps.python.org/pep-0561/) compliance. Type checkers like `mypy` will recognize the inline type hints.

## Creating a development environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pipenv
pipenv install --dev
prek install
```

## Contribution
You know;)
