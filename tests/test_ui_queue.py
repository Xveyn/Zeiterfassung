from src.ui_queue import UiQueue


def test_vor_start_abgelegtes_wird_beim_drain_ausgefuehrt():
    q = UiQueue()
    out = []
    q.put(lambda: out.append(1))
    q.put(lambda: out.append(2))
    assert out == []
    q.drain()
    assert out == [1, 2]


def test_drain_ist_leer_ein_noop():
    UiQueue().drain()


def test_fehler_im_callback_stoppt_die_uebrigen_nicht():
    q = UiQueue()
    out = []
    q.put(lambda: 1 / 0)
    q.put(lambda: out.append("ok"))
    q.drain()
    assert out == ["ok"]


def test_start_plant_poll_neu_ein():
    q = UiQueue()
    scheduled = []
    out = []
    q.put(lambda: out.append(1))
    q.start(lambda ms, fn: scheduled.append((ms, fn)))
    assert out == [1]
    assert len(scheduled) == 1
    q.put(lambda: out.append(2))
    scheduled[0][1]()
    assert out == [1, 2]
    assert len(scheduled) == 2


def test_stop_beendet_den_poll():
    q = UiQueue()
    scheduled = []
    q.start(lambda ms, fn: scheduled.append(fn))
    q.stop()
    scheduled[0]()
    assert len(scheduled) == 1


def test_poll_endet_still_wenn_scheduler_wirft():
    q = UiQueue()
    calls = []

    def sched(ms, fn):
        calls.append(fn)
        if len(calls) > 1:
            raise RuntimeError("destroyed")

    q.start(sched)
    calls[0]()  # Neu-Einplanen wirft: Poll endet still
    assert len(calls) == 2
