import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from apscheduler.jobstores.memory import MemoryJobStore
from core.scheduler import EnterpriseScheduler

@pytest.fixture
def mock_bot():
    return MagicMock()

@pytest.fixture
def mock_job_store():
    # APScheduler checks isinstance(store, BaseJobStore). 
    # Return a real MemoryJobStore instead of a MagicMock to pass validation.
    with patch('core.scheduler.SQLAlchemyJobStore', return_value=MemoryJobStore()) as mock_store:
        yield mock_store

@pytest.mark.asyncio
async def test_enterprise_scheduler_initialization(mock_bot, mock_job_store):
    scheduler = EnterpriseScheduler(mock_bot)
    
    # Verify jobs were added during init
    jobs = scheduler.scheduler.get_jobs()
    job_ids = [job.id for job in jobs]
    
    assert "morning_schedule" in job_ids
    assert "weekly_summary" in job_ids
    assert "audit_classes" in job_ids
    assert "personal_reminders_processor" in job_ids

@pytest.mark.asyncio
async def test_scheduler_audit_upcoming_classes(mock_bot, mock_job_store):
    scheduler = EnterpriseScheduler(mock_bot)
    
    classes_today = [
        {"id": 1, "time_start": "08:00", "subject": "Math", "group_type": "Lecture", "room": "101"}
    ]
    
    with patch("core.database.get_schedule_for_day", AsyncMock(return_value=classes_today)), \
         patch("core.scheduler._now") as mock_now, \
         patch.object(scheduler.scheduler, "add_job") as mock_add_job:
             
        from datetime import datetime, timedelta
        # Mock time so that 08:00 is exactly in 15 minutes (meaning audit happens at 07:45)
        # We need notification time (07:45) to be within the next 6 minutes of "now".
        # Let's say now is 07:44.
        mock_now.return_value = datetime.strptime("2026-03-03 07:44:00", "%Y-%m-%d %H:%M:%S")
        
        await scheduler._audit_and_schedule_classes()
        
        # Verify add_job was called to schedule the EXACT 15 min reminder
        mock_add_job.assert_called_once()
        args, kwargs = mock_add_job.call_args
        assert kwargs["id"] == "class_reminder_1_08:00_1"
        assert kwargs["jobstore"] == "transient"
