#!/usr/bin/env python3
"""
Sync devices from VAS to Ruth AI database.

This script fetches all devices from VAS and creates corresponding
entries in the Ruth AI devices table.
"""
import asyncio
import sys
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.integrations.vas import VASClient
from app.models import Device


async def main():
    """Sync devices from VAS to Ruth AI."""
    settings = get_settings()

    print("=" * 60)
    print("Ruth AI Device Sync")
    print("=" * 60)
    print(f"VAS URL: {settings.vas_base_url}")
    print()

    # Initialize VAS client
    print("Initializing VAS client...")
    vas_client = VASClient(
        base_url=settings.vas_base_url,
        client_id=settings.vas_client_id,
        client_secret=settings.vas_client_secret,
    )
    await vas_client.connect()
    print("✓ Connected to VAS")
    print()

    # Get devices from VAS
    print("Fetching devices from VAS...")
    vas_devices = await vas_client.get_devices()
    print(f"✓ Found {len(vas_devices)} devices in VAS:")
    for d in vas_devices:
        print(f"  • {d.name} (ID: {d.id}, Status: {'active' if d.is_active else 'inactive'})")
    print()

    # Connect to database
    print("Connecting to database...")
    engine = create_async_engine(str(settings.database_url), echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    print("✓ Connected to database")
    print()

    # Sync devices
    print("Syncing devices to Ruth AI database...")
    async with async_session() as session:
        for vas_device in vas_devices:
            # Check if device already exists
            from sqlalchemy import select
            result = await session.execute(
                select(Device).where(Device.vas_device_id == vas_device.id)
            )
            existing = result.scalar_one_or_none()

            if existing:
                print(f"  ↻ Updating: {vas_device.name}")
                existing.name = vas_device.name
                existing.is_active = vas_device.is_active
                existing.last_synced_at = datetime.now(timezone.utc)
                existing.updated_at = datetime.now(timezone.utc)
            else:
                print(f"  + Adding: {vas_device.name}")
                device = Device(
                    id=uuid4(),
                    vas_device_id=vas_device.id,
                    name=vas_device.name,
                    description=f"Camera synced from VAS",
                    location=vas_device.location or "Unknown",
                    is_active=vas_device.is_active,
                    last_synced_at=datetime.now(timezone.utc),
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(device)

        await session.commit()

    print()
    print("=" * 60)
    print(f"✓ Successfully synced {len(vas_devices)} devices!")
    print("=" * 60)

    await vas_client.close()
    await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nSync cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
