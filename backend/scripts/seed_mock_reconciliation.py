import asyncio
import os
import sys
from datetime import datetime, timezone

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from lib.prisma_client import db
from services.reconciliation_service import _save_status
from lib.admin_constants import STATUS_DISCREPANCY_DETECTED, STATUS_RECONCILED


async def seed():
    print("Connecting to database...")
    await db.connect()
    
    now = datetime.now(timezone.utc)
    
    mock_status_blob = {
        "status": STATUS_DISCREPANCY_DETECTED,
        "computed_at": now.isoformat(),
        "tolerance_pct": 1.0,
        "pending": False,
        "retry_count": 0,
        "message": "Mock seed applied for US-207 testing.",
        "providers": {
            "stripe": {
                "provider": "stripe",
                "internal_count": 500,
                "internal_revenue": 5000.0,
                "provider_count": 470,
                "provider_revenue": 4700.0,
                "variance_pct": 6.383, # (300 / 4700) * 100
                "status": STATUS_DISCREPANCY_DETECTED,
                "grace_applied_count": 0,
                "mismatched_items": [
                    {
                        "user_id": "usr_test_refund_123",
                        "delta": 25.0,
                        "transaction_id": "txn_mock_9999",
                        "renewal_at": None,
                    }
                ]
            },
            "apple": {
                "provider": "apple",
                "internal_count": 100,
                "internal_revenue": 1000.0,
                "provider_count": 100,
                "provider_revenue": 1000.0,
                "variance_pct": 0.0,
                "status": STATUS_RECONCILED,
                "grace_applied_count": 2,
                "mismatched_items": []
            },
            "google": {
                "provider": "google",
                "internal_count": 250,
                "internal_revenue": 2500.0,
                "provider_count": 250,
                "provider_revenue": 2500.0,
                "variance_pct": 0.0,
                "status": STATUS_RECONCILED,
                "grace_applied_count": 0,
                "mismatched_items": []
            }
        }
    }
    
    print("Seeding reconciliation mock data...")
    await _save_status(mock_status_blob)
    print("Mock data seeded successfully!")
    print("You can now refresh the analytics page to see the Discrepancy Detected badge and test the Targeted Re-sync flow.")
    
    await db.disconnect()

if __name__ == "__main__":
    asyncio.run(seed())
