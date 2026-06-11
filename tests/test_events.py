import asyncio
import json

from jarvis.events import EventBus


def test_emit_fans_out_to_all_subscribers():
    async def scenario():
        bus = EventBus()
        bus.attach_loop(asyncio.get_running_loop())
        q1, q2 = bus.subscribe(), bus.subscribe()
        bus.emit("transcript", text="שלום", lang="he")
        await asyncio.sleep(0)  # let call_soon_threadsafe callbacks run
        m1, m2 = json.loads(q1.get_nowait()), json.loads(q2.get_nowait())
        assert m1 == {"type": "transcript", "text": "שלום", "lang": "he"}
        assert m2 == m1

    asyncio.run(scenario())


def test_set_state_tracks_and_emits():
    async def scenario():
        bus = EventBus()
        bus.attach_loop(asyncio.get_running_loop())
        q = bus.subscribe()
        bus.set_state("listening")
        await asyncio.sleep(0)
        assert bus.state == "listening"
        assert json.loads(q.get_nowait()) == {"type": "state", "state": "listening"}

    asyncio.run(scenario())


def test_emit_without_loop_is_noop():
    bus = EventBus()
    bus.emit("state", state="idle")  # must not raise


def test_unsubscribe_stops_delivery():
    async def scenario():
        bus = EventBus()
        bus.attach_loop(asyncio.get_running_loop())
        q = bus.subscribe()
        bus.unsubscribe(q)
        bus.emit("state", state="idle")
        await asyncio.sleep(0)
        assert q.empty()

    asyncio.run(scenario())
