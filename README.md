## aiotractive

![Continuous Integration](https://github.com/zhulik/aiotractive/workflows/Continuous%20Integration/badge.svg?branch=main)

**Unofficial** Asynchronous Python client for the [Tractive](https://tractive.com) REST API.

**This project and it's author are not affilated with Tractive GmbH**

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
await trackers.details() # Includes device capabilities, battery status(not level), charging state and so on

await tracker.hw_info() # Includes battery level, firmware version, model and so on

# Retrieve current location 
await tracker.pos_report() # Includes coordinates, latitude, speed and so on
# Retrieve hardware info

# Control the buzzer
await set_buzzer_active(True) # or False

# Control the LED
await set_led_active(True) # or False

# Control the live tracking
await set_live_tracking_active(True) # or False
```

#### Trackable objects (usually pets)
```python
objects = await client.trackable_objects()

object = objects[0]

# Retrieve details
await object.details() # Includes pet's name, pet's tracker id and so on
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

## Contribution
You know;)
