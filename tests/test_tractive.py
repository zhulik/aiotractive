"""Tests for the Tractive client status handling."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aiotractive import PetStatus, TrackerStatus, Tractive
from aiotractive.exceptions import TractiveError, UnauthorizedError

from .conftest import load_fixture

TRACKER_ID = "tracker_abc123"
OTHER_TRACKER_ID = "tracker_def456"
PET_ID = "pet_id_123"

BASE_STATUS = TrackerStatus(
    battery_level=50,
    tracker_state="operational",
    battery_charging=False,
    power_saving=False,
    power_saving_zone=None,
    latitude=10.0,
    longitude=20.0,
    accuracy=5,
    sensor_used="KNOWN_WIFI",
    buzzer=False,
    led=True,
    live_tracking=False,
)

FULL_EVENT: dict[str, Any] = {
    "message": "tracker_status",
    "tracker_id": TRACKER_ID,
    "tracker_state": "NOT_REPORTING",
    "tracker_state_reason": "POWER_SAVING",
    "charging_state": "CHARGING",
    "hardware": {"time": 1, "battery_level": 80, "power_saving_zone_id": "zone"},
    "position": {
        "time": 1,
        "latlong": [1.5, 2.5],
        "accuracy": 10,
        "sensor_used": "GPS",
    },
    "buzzer_control": {"active": True},
    "led_control": {"active": False},
    "live_tracking": {"active": True},
}

HEALTH_OVERVIEW: dict[str, Any] = {
    "petId": PET_ID,
    "sleep": {"minutesDaySleep": 100, "minutesNightSleep": 300, "minutesCalm": 122},
    "activity": {"minutesGoal": 200, "minutesActive": 150},
}

FULL_PET_STATUS = PetStatus(
    daily_goal=200,
    minutes_active=150,
    minutes_day_sleep=100,
    minutes_night_sleep=300,
    minutes_rest=122,
)


@pytest.fixture
def client() -> Tractive:
    """Create a Tractive client with a known tracker status."""
    tractive = Tractive(
        "test@example.com", "password", session=MagicMock(), fetch_delay=0
    )
    tractive.status.trackers[TRACKER_ID] = dataclasses.replace(BASE_STATUS)
    return tractive


def mock_channel(*generators: AsyncGenerator[dict[str, Any]]) -> MagicMock:
    """Return a Channel class mock whose instances listen with the generators."""
    channel_cls = MagicMock()
    channel_cls.side_effect = [
        MagicMock(listen=MagicMock(return_value=gen)) for gen in generators
    ]
    return channel_cls


async def events_then_raise(
    events: list[dict[str, Any]], error: Exception
) -> AsyncGenerator[dict[str, Any]]:
    """Yield the events, then raise the error."""
    for event in events:
        yield event
    raise error


async def wait_forever() -> AsyncGenerator[dict[str, Any]]:
    """Never yield anything."""
    await asyncio.Event().wait()
    yield {}


@pytest.mark.parametrize(
    ("event", "changes"),
    [
        (
            FULL_EVENT,
            {
                "battery_level": 80,
                "tracker_state": "not_reporting",
                "battery_charging": True,
                "power_saving": True,
                "power_saving_zone": True,
                "latitude": 1.5,
                "longitude": 2.5,
                "accuracy": 10,
                "sensor_used": "GPS",
                "buzzer": True,
                "led": False,
                "live_tracking": True,
            },
        ),
        ({"tracker_id": TRACKER_ID}, {}),
        ({"message": "tracker_status"}, {}),
    ],
)
def test_update_status_tracker(
    client: Tractive, event: dict[str, Any], changes: dict[str, Any]
) -> None:
    """Test that tracker events update only the fields they carry."""
    client._update_status(event)

    assert client.status.trackers[TRACKER_ID] == dataclasses.replace(
        BASE_STATUS, **changes
    )


def test_update_status_clears_charging_and_power_saving(client: Tractive) -> None:
    """Test that non-matching charging state and reason set the flags to False."""
    client.status.trackers[TRACKER_ID] = dataclasses.replace(
        BASE_STATUS, battery_charging=True, power_saving=True
    )

    client._update_status(
        {
            "tracker_id": TRACKER_ID,
            "hardware": {"time": 1},
            "charging_state": "NOT_CHARGING",
            "tracker_state_reason": "OUT_OF_BATTERY",
            "tracker_state": "NOT_REPORTING",
        }
    )

    assert client.status.trackers[TRACKER_ID] == dataclasses.replace(
        BASE_STATUS, tracker_state="not_reporting"
    )


def test_update_status_new_tracker(client: Tractive) -> None:
    """Test that an event for an unknown tracker creates its status."""
    client._update_status({**FULL_EVENT, "tracker_id": OTHER_TRACKER_ID})

    assert client.status.trackers[OTHER_TRACKER_ID].battery_level == 80


def test_update_status_dedup_per_tracker(client: Tractive) -> None:
    """Test that the same timestamps on different trackers are both applied."""
    client._update_status(FULL_EVENT)
    client._update_status({**FULL_EVENT, "tracker_id": OTHER_TRACKER_ID})

    assert client.status.trackers[TRACKER_ID].battery_level == 80
    assert client.status.trackers[OTHER_TRACKER_ID].battery_level == 80
    assert client.status.trackers[OTHER_TRACKER_ID].latitude == 1.5


def test_update_status_dedup_same_tracker(client: Tractive) -> None:
    """Test that repeated timestamps are ignored, switches still applied."""
    client._update_status(FULL_EVENT)
    client._update_status(
        {
            **FULL_EVENT,
            "hardware": {"time": 1, "battery_level": 10},
            "position": {"time": 1, "latlong": [7, 8]},
            "buzzer_control": {"active": False},
        }
    )

    status = client.status.trackers[TRACKER_ID]
    assert status.battery_level == 80
    assert status.latitude == 1.5
    assert status.buzzer is False


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ({"message": "health_overview", **HEALTH_OVERVIEW}, FULL_PET_STATUS),
        ({"message": "health_overview", "content": HEALTH_OVERVIEW}, FULL_PET_STATUS),
        (
            {
                "message": "health_overview",
                "content": {"petId": PET_ID, "activity": HEALTH_OVERVIEW["activity"]},
            },
            PetStatus(daily_goal=200, minutes_active=150),
        ),
        (
            {"message": "health_overview", "petId": PET_ID, "sleep": None},
            PetStatus(),
        ),
    ],
)
def test_update_status_health_overview(
    client: Tractive, event: dict[str, Any], expected: PetStatus
) -> None:
    """Test that health overview events update the pet status."""
    client.status.pets[PET_ID] = dataclasses.replace(FULL_PET_STATUS)

    client._update_status(event)

    assert client.status.pets[PET_ID] == expected


@pytest.mark.parametrize(
    "event",
    [
        {"message": "health_overview", "sleep": HEALTH_OVERVIEW["sleep"]},
        {"message": "health_overview", "content": {"activity": {}}},
    ],
)
def test_update_status_health_overview_without_pet_id(
    client: Tractive, event: dict[str, Any]
) -> None:
    """Test that a health overview without petId is ignored."""
    client._update_status(event)

    assert client.status.pets == {}


@pytest.mark.parametrize(
    "malformed",
    [
        {"tracker_id": TRACKER_ID, "hardware": "oops"},
        {"tracker_id": TRACKER_ID, "led_control": 5},
    ],
)
async def test_listen_skips_malformed_event(
    client: Tractive, malformed: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """Test that a malformed event is skipped and later events still notify."""
    listener = MagicMock()
    client.subscribe_updates(listener)
    error = UnauthorizedError("bye")
    channel_cls = mock_channel(events_then_raise([malformed, FULL_EVENT], error))

    with (
        patch("aiotractive.tractive.Channel", channel_cls),
        caplog.at_level(logging.DEBUG, logger="aiotractive.tractive"),
    ):
        await client.listen()

    assert [c.args for c in listener.call_args_list] == [(None,), (error,)]
    assert client.status.trackers[TRACKER_ID].battery_level == 80
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert TRACKER_ID not in warnings[0].getMessage()
    debugs = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert any(TRACKER_ID in r.getMessage() for r in debugs)


async def test_listen_listener_error_is_logged(
    client: Tractive, caplog: pytest.LogCaptureFixture
) -> None:
    """Test that a raising listener is logged and not treated as a channel error."""
    listener = MagicMock(side_effect=[RuntimeError("listener bug"), None, None])
    client.subscribe_updates(listener)
    error = UnauthorizedError("bye")
    channel_cls = mock_channel(events_then_raise([FULL_EVENT, FULL_EVENT], error))

    with (
        patch("aiotractive.tractive.Channel", channel_cls),
        patch("aiotractive.tractive.asyncio.sleep", AsyncMock()) as sleep,
    ):
        await client.listen()

    assert [c.args for c in listener.call_args_list] == [(None,), (None,), (error,)]
    assert channel_cls.call_count == 1
    sleep.assert_not_called()
    assert any(
        r.levelno == logging.ERROR and "listener" in r.getMessage()
        for r in caplog.records
    )


async def test_listen_reconnects_after_error(client: Tractive) -> None:
    """Test that a transient error is reported, dedup reset and reconnected."""
    listener = MagicMock()
    client.subscribe_updates(listener)
    transient = TractiveError("boom")
    terminal = UnauthorizedError("bye")
    second = {**FULL_EVENT, "hardware": {"time": 1, "battery_level": 30}}
    channel_cls = mock_channel(
        events_then_raise([FULL_EVENT], transient),
        events_then_raise([second], terminal),
    )

    with (
        patch("aiotractive.tractive.Channel", channel_cls),
        patch("aiotractive.tractive.asyncio.sleep", new_callable=AsyncMock) as sleep,
    ):
        await client.listen()

    sleep.assert_awaited_once_with(10)
    assert channel_cls.call_count == 2
    assert [c.args for c in listener.call_args_list] == [
        (None,),
        (transient,),
        (None,),
        (terminal,),
    ]
    assert client.status.trackers[TRACKER_ID].battery_level == 30


async def test_listen_reconnects_after_unexpected_error(client: Tractive) -> None:
    """Test that an unexpected error is reported and reconnected."""
    listener = MagicMock()
    client.subscribe_updates(listener)
    unexpected = RuntimeError("boom")
    terminal = UnauthorizedError("bye")
    channel_cls = mock_channel(
        events_then_raise([], unexpected), events_then_raise([], terminal)
    )

    with (
        patch("aiotractive.tractive.Channel", channel_cls),
        patch("aiotractive.tractive.asyncio.sleep", new_callable=AsyncMock),
    ):
        await client.listen()

    assert [c.args for c in listener.call_args_list] == [(unexpected,), (terminal,)]


async def test_listen_on_connected_notifies(client: Tractive) -> None:
    """Test that the channel connect callback notifies the listener."""
    listener = MagicMock()
    client.subscribe_updates(listener)
    channel_cls = mock_channel(events_then_raise([], UnauthorizedError("bye")))

    with patch("aiotractive.tractive.Channel", channel_cls):
        await client.listen()
    listener.reset_mock()
    channel_cls.call_args.kwargs["on_connected"]()

    listener.assert_called_once_with(None)


async def test_listen_cancel(client: Tractive) -> None:
    """Test that cancelling listen propagates CancelledError."""
    with patch("aiotractive.tractive.Channel", mock_channel(wait_forever())):
        task = asyncio.create_task(client.listen())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_start_stop_listener(client: Tractive) -> None:
    """Test that the listener starts once and stops cleanly."""
    await client.async_stop_listener()

    with patch("aiotractive.tractive.Channel", mock_channel(wait_forever())):
        await client.async_start_listener()
        task = client._background_task
        await client.async_start_listener()
        assert client._background_task is task
        await asyncio.sleep(0)

        await client.async_stop_listener()

    assert client._background_task is None
    assert task is not None
    assert task.cancelled()


async def test_start_listener_restarts_finished_task(client: Tractive) -> None:
    """Test that a listener that already ended is replaced by a new one."""
    channel_cls = mock_channel(
        events_then_raise([], UnauthorizedError("bye")), wait_forever()
    )

    with patch("aiotractive.tractive.Channel", channel_cls):
        await client.async_start_listener()
        finished = client._background_task
        assert finished is not None
        await finished

        await client.async_start_listener()
        assert client._background_task is not finished
        await asyncio.sleep(0)
        await client.async_stop_listener()

    assert channel_cls.call_count == 2


async def test_close_stops_listener(client: Tractive) -> None:
    """Test that close stops a running listener and closes the API."""
    client._api.close = AsyncMock()

    with patch("aiotractive.tractive.Channel", mock_channel(wait_forever())):
        await client.async_start_listener()
        task = client._background_task
        await asyncio.sleep(0)
        await client.close()

    assert client._background_task is None
    assert task is not None
    assert task.cancelled()
    client._api.close.assert_awaited_once()


def test_tracker_bound_to_status(client: Tractive) -> None:
    """Test that tracker() returns a Tracker bound to the live status."""
    tracker = client.tracker(TRACKER_ID)

    assert tracker._status is client.status.trackers[TRACKER_ID]


def mock_request(responses: dict[str, Any]) -> AsyncMock:
    """Return an API request mock that answers by URL."""

    async def request(url: str, **_kwargs: Any) -> Any:  # noqa: ANN401
        return responses[url]

    return AsyncMock(side_effect=request)


def trackable_object_mock(data: dict[str, Any]) -> MagicMock:
    """Return a trackable object mock whose details return the data."""
    return MagicMock(details=AsyncMock(return_value=data))


async def test_fetch_trackables(client: Tractive) -> None:
    """Test that only pets with an owned tracker become trackables."""
    pet = load_fixture("trackable_object")
    other_pet = {**pet, "_id": "pet_2", "device_id": "device_2"}
    client.trackable_objects = AsyncMock(
        return_value=[
            trackable_object_mock({"_id": "no_tracker", "device_id": None}),
            trackable_object_mock({**pet, "details": None}),
            trackable_object_mock(pet),
            trackable_object_mock(other_pet),
        ]
    )
    client._api.request = mock_request(
        {
            "tracker/device_id_123": load_fixture("tracker_details"),
            "tracker/device_2": {"_id": "device_2"},
        }
    )
    client._fetch_delay = 2.0

    with patch("aiotractive.tractive.asyncio.sleep", new_callable=AsyncMock) as sleep:
        trackables = await client.async_fetch_trackables()

    assert [(t.pet_id, t.tracker_id, t.name) for t in trackables] == [
        (PET_ID, "device_id_123", "Test Pet"),
        ("pet_2", "device_2", "Test Pet"),
    ]
    assert trackables[0].tracker_details == load_fixture("tracker_details")
    assert sleep.await_count == 3
    assert client._trackables is trackables


async def test_fetch_trackables_incomplete_tracker(client: Tractive) -> None:
    """Test that a tracker without an id raises TractiveError."""
    client.trackable_objects = AsyncMock(
        return_value=[trackable_object_mock(load_fixture("trackable_object"))]
    )
    client._api.request = mock_request({"tracker/device_id_123": {}})

    with pytest.raises(TractiveError, match="device_id_123"):
        await client.async_fetch_trackables()


@pytest.mark.parametrize(
    ("health", "expected_pets"),
    [
        (load_fixture("health_overview"), {PET_ID: FULL_PET_STATUS}),
        ({}, {}),
    ],
)
async def test_fetch_status(
    client: Tractive, health: dict[str, Any], expected_pets: dict[str, PetStatus]
) -> None:
    """Test that the REST refresh fills the status and keeps switch states."""
    client._api.user_id = AsyncMock(return_value="user_1")
    client._api.request = mock_request(
        {
            "user/user_1/trackable_objects": [{"_id": PET_ID, "_type": "pet"}],
            "trackable_object/pet_id_123": load_fixture("trackable_object"),
            "tracker/device_id_123": load_fixture("tracker_details"),
            "device_hw_report/device_id_123/": load_fixture("tracker_hw_info"),
            "device_pos_report/device_id_123": load_fixture("tracker_pos_report"),
            "pet/pet_id_123/health/overview": health,
        }
    )
    client._update_status(
        {"tracker_id": "device_id_123", "buzzer_control": {"active": True}}
    )

    status = await client.async_fetch_status()

    assert status is client.status
    assert status.trackers["device_id_123"] == TrackerStatus(
        battery_level=96,
        tracker_state="operational",
        battery_charging=False,
        power_saving=True,
        power_saving_zone=True,
        latitude=33.222222,
        longitude=44.555555,
        accuracy=30,
        sensor_used="KNOWN_WIFI",
        buzzer=True,
        led=None,
        live_tracking=None,
    )
    assert status.pets == expected_pets


def fetch_status_responses() -> dict[str, Any]:
    """Return REST responses for one pet with one tracker."""
    return {
        "user/user_1/trackable_objects": [{"_id": PET_ID, "_type": "pet"}],
        "trackable_object/pet_id_123": load_fixture("trackable_object"),
        "tracker/device_id_123": load_fixture("tracker_details"),
        "device_hw_report/device_id_123/": load_fixture("tracker_hw_info"),
        "device_pos_report/device_id_123": load_fixture("tracker_pos_report"),
        "pet/pet_id_123/health/overview": {},
    }


async def test_fetch_status_uses_fresh_details(client: Tractive) -> None:
    """Test that each refresh uses fresh tracker details, not the cached ones."""
    client._api.user_id = AsyncMock(return_value="user_1")
    responses = fetch_status_responses()
    client._api.request = mock_request(responses)
    await client.async_fetch_status()
    client._update_status(
        {
            "tracker_id": "device_id_123",
            "hardware": {"time": 99},
            "charging_state": "CHARGING",
            "tracker_state": "NOT_REPORTING",
        }
    )
    fresh = {
        **load_fixture("tracker_details"),
        "charging_state": "CHARGING",
        "state": "NOT_REPORTING",
    }
    responses["tracker/device_id_123"] = fresh

    status = await client.async_fetch_status()

    assert status.trackers["device_id_123"].battery_charging is True
    assert status.trackers["device_id_123"].tracker_state == "not_reporting"
    assert client._trackables is not None
    assert client._trackables[0].tracker_details == fresh


async def test_fetch_status_reuses_trackables(client: Tractive) -> None:
    """Test that a second refresh does not fetch the trackable objects again."""
    client._api.user_id = AsyncMock(return_value="user_1")
    client._api.request = mock_request(fetch_status_responses())

    await client.async_fetch_status()
    await client.async_fetch_status()

    urls = [c.args[0] for c in client._api.request.await_args_list]
    assert urls.count("user/user_1/trackable_objects") == 1
    assert urls.count("tracker/device_id_123") == 3


async def test_fetch_status_delay_after_implicit_fetch(client: Tractive) -> None:
    """Test the delay after an implicit trackables fetch and between trackables."""
    client._api.user_id = AsyncMock(return_value="user_1")
    client._api.request = mock_request(fetch_status_responses())
    client._fetch_delay = 2.0

    with patch("aiotractive.tractive.asyncio.sleep", new_callable=AsyncMock) as sleep:
        await client.async_fetch_status()
        sleep.assert_awaited_once_with(2.0)
        client._trackables = [*(client._trackables or []), *(client._trackables or [])]
        await client.async_fetch_status()

    assert sleep.await_count == 2
