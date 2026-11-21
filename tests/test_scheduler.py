from app import create_app
from app.config import TestConfig
from app import scheduler as sched_mod


class SchedConfig(TestConfig):
    TESTING = False
    SCHEDULER_ENABLED = True


def test_schedule_definition():
    app = create_app(TestConfig)
    ids = {job_id: trig for job_id, trig in sched_mod.build_schedule(app)}
    assert set(ids) == {"rss", "rss_pre_briefing", "weather", "briefing", "ibge", "cepea"}
    assert str(ids["briefing"].fields[5]) == "6"  # hour


def test_disabled_in_testing():
    assert sched_mod.init_scheduler(create_app(TestConfig)) is None


def test_starts_once_and_lock_blocks_second_process(tmp_path, monkeypatch):
    app = create_app(SchedConfig)
    app.instance_path = str(tmp_path)
    monkeypatch.setattr(sched_mod, "_scheduler", None)
    s = sched_mod.init_scheduler(app)
    try:
        assert s is not None and len(s.get_jobs()) == 6
        assert sched_mod.init_scheduler(app) is s           # idempotente no mesmo processo
        monkeypatch.setattr(sched_mod, "_scheduler", None)  # simula outro worker
        assert sched_mod._acquire_lock(str(tmp_path)) is False
    finally:
        s.shutdown(wait=False)
        if sched_mod._lock_handle:
            sched_mod._lock_handle.close()
            sched_mod._lock_handle = None
