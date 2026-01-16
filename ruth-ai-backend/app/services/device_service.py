"""Device Management Service.

Responsible for:
- Discovering and syncing devices from VAS
- Persisting devices in local database
- VAS device IDs are authoritative (local DB is a cache)

This service is the single source of truth for which cameras are known.

Usage:
    device_service = DeviceService(vas_client, db)

    # Sync all devices from VAS
    devices = await device_service.sync_devices_from_vas()

    # Get a specific device
    device = await device_service.get_device_by_id(device_id)

    # Ensure device exists (sync if needed)
    device = await device_service.ensure_device_exists(vas_device_id)
"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.integrations.vas import (
    VASClient,
    VASConnectionError,
    VASError,
    VASNotFoundError,
)
from app.integrations.vas import Device as VASDevice
from app.models import Device

from .exceptions import (
    DeviceInactiveError,
    DeviceNotFoundError,
    DeviceSyncError,
)

logger = get_logger(__name__)


class DeviceService:
    """Service for device management and VAS synchronization.

    This service:
    - Discovers devices from VAS and caches them locally
    - Treats VAS as the source of truth for device metadata
    - NEVER deletes devices (only marks inactive)
    - Provides idempotent sync operations
    """

    def __init__(
        self,
        vas_client: VASClient,
        db: AsyncSession,
    ) -> None:
        """Initialize device service.

        Args:
            vas_client: VAS API client (dependency injected)
            db: Database session (dependency injected)
        """
        self._vas = vas_client
        self._db = db

    # -------------------------------------------------------------------------
    # Device Discovery & Sync
    # -------------------------------------------------------------------------

    async def sync_devices_from_vas(self) -> list[Device]:
        """Discover and sync all devices from VAS.

        This operation is idempotent:
        - Creates local records for new VAS devices
        - Updates metadata for existing devices
        - NEVER deletes devices (only marks inactive if not found)

        Returns:
            List of all synced devices

        Raises:
            DeviceSyncError: If VAS communication fails
        """
        logger.info("Starting device sync from VAS")

        try:
            vas_devices = await self._vas.get_devices()
        except VASConnectionError as e:
            raise DeviceSyncError("Cannot connect to VAS", cause=e) from e
        except VASError as e:
            raise DeviceSyncError(f"VAS error during device sync: {e}", cause=e) from e

        logger.info("Fetched devices from VAS", count=len(vas_devices))

        # Track VAS device IDs for inactive detection
        vas_device_ids = {d.id for d in vas_devices}

        # Sync each VAS device to local DB
        synced_devices: list[Device] = []
        for vas_device in vas_devices:
            device = await self._sync_single_device(vas_device)
            synced_devices.append(device)

        # Mark devices not in VAS as inactive (but don't delete)
        await self._mark_missing_devices_inactive(vas_device_ids)

        logger.info(
            "Device sync completed",
            synced=len(synced_devices),
            vas_total=len(vas_devices),
        )

        return synced_devices

    async def _sync_single_device(self, vas_device: VASDevice) -> Device:
        """Sync a single VAS device to local database.

        Creates new device if not exists, updates if exists.

        Args:
            vas_device: Device data from VAS

        Returns:
            Local device record
        """
        # Check if device already exists locally
        stmt = select(Device).where(Device.vas_device_id == vas_device.id)
        result = await self._db.execute(stmt)
        device = result.scalar_one_or_none()

        now = datetime.now(timezone.utc)

        if device is None:
            # Create new device
            device = Device(
                vas_device_id=vas_device.id,
                name=vas_device.name,
                description=vas_device.description,
                location=vas_device.location,
                is_active=vas_device.is_active,
                last_synced_at=now,
            )
            self._db.add(device)
            logger.info(
                "Created new device",
                vas_device_id=vas_device.id,
                name=vas_device.name,
            )
        else:
            # Update existing device
            device.name = vas_device.name
            device.description = vas_device.description
            device.location = vas_device.location
            device.is_active = vas_device.is_active
            device.last_synced_at = now
            logger.debug(
                "Updated device",
                device_id=str(device.id),
                vas_device_id=vas_device.id,
            )

        await self._db.flush()
        return device

    async def _mark_missing_devices_inactive(
        self,
        active_vas_ids: set[str],
    ) -> None:
        """Mark devices not in VAS as inactive.

        Args:
            active_vas_ids: Set of VAS device IDs that are currently active
        """
        # Get all local devices
        stmt = select(Device).where(Device.is_active.is_(True))
        result = await self._db.execute(stmt)
        local_devices = result.scalars().all()

        for device in local_devices:
            if device.vas_device_id not in active_vas_ids:
                device.is_active = False
                logger.warning(
                    "Device no longer in VAS, marking inactive",
                    device_id=str(device.id),
                    vas_device_id=device.vas_device_id,
                )

    # -------------------------------------------------------------------------
    # Device Retrieval
    # -------------------------------------------------------------------------

    async def get_device_by_id(
        self,
        device_id: UUID,
        *,
        require_active: bool = False,
    ) -> Device:
        """Get device by internal ID.

        Args:
            device_id: Local device UUID
            require_active: If True, raise error if device is inactive

        Returns:
            Device record

        Raises:
            DeviceNotFoundError: Device does not exist
            DeviceInactiveError: Device exists but is inactive (if require_active)
        """
        stmt = select(Device).where(Device.id == device_id)
        result = await self._db.execute(stmt)
        device = result.scalar_one_or_none()

        if device is None:
            raise DeviceNotFoundError(device_id)

        if require_active and not device.is_active:
            raise DeviceInactiveError(device_id)

        return device

    async def get_device_by_vas_id(
        self,
        vas_device_id: str,
        *,
        require_active: bool = False,
    ) -> Device:
        """Get device by VAS device ID.

        Args:
            vas_device_id: VAS-assigned device identifier
            require_active: If True, raise error if device is inactive

        Returns:
            Device record

        Raises:
            DeviceNotFoundError: Device does not exist
            DeviceInactiveError: Device exists but is inactive (if require_active)
        """
        stmt = select(Device).where(Device.vas_device_id == vas_device_id)
        result = await self._db.execute(stmt)
        device = result.scalar_one_or_none()

        if device is None:
            raise DeviceNotFoundError(vas_device_id, vas_device_id=vas_device_id)

        if require_active and not device.is_active:
            raise DeviceInactiveError(device.id)

        return device

    async def ensure_device_exists(
        self,
        vas_device_id: str,
    ) -> Device:
        """Ensure a device exists locally, syncing from VAS if needed.

        This is idempotent - safe to call multiple times.

        Args:
            vas_device_id: VAS-assigned device identifier

        Returns:
            Device record (created or existing)

        Raises:
            DeviceNotFoundError: Device not found in VAS
            DeviceSyncError: VAS communication failed
        """
        # Check if already exists locally
        try:
            return await self.get_device_by_vas_id(vas_device_id)
        except DeviceNotFoundError:
            pass

        # Not found locally, fetch from VAS
        logger.info(
            "Device not found locally, fetching from VAS",
            vas_device_id=vas_device_id,
        )

        try:
            vas_device = await self._vas.get_device(vas_device_id)
        except VASNotFoundError as e:
            raise DeviceNotFoundError(
                vas_device_id,
                vas_device_id=vas_device_id,
            ) from e
        except VASError as e:
            raise DeviceSyncError(
                f"Failed to fetch device from VAS: {vas_device_id}",
                cause=e,
            ) from e

        # Create local record
        device = await self._sync_single_device(vas_device)
        await self._db.flush()

        return device

    async def list_devices(
        self,
        *,
        active_only: bool = True,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Device]:
        """List devices with optional filtering.

        Args:
            active_only: Only return active devices
            skip: Pagination offset
            limit: Maximum results

        Returns:
            List of devices
        """
        stmt = select(Device).offset(skip).limit(limit).order_by(Device.name)

        if active_only:
            stmt = stmt.where(Device.is_active.is_(True))

        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def count_devices(self, *, active_only: bool = True) -> int:
        """Count devices.

        Args:
            active_only: Only count active devices

        Returns:
            Device count
        """
        from sqlalchemy import func

        stmt = select(func.count()).select_from(Device)
        if active_only:
            stmt = stmt.where(Device.is_active.is_(True))

        result = await self._db.execute(stmt)
        return result.scalar_one()

    # -------------------------------------------------------------------------
    # Device Status
    # -------------------------------------------------------------------------

    async def refresh_device_status(self, device_id: UUID) -> Device:
        """Refresh device status from VAS.

        Args:
            device_id: Local device UUID

        Returns:
            Updated device record
        """
        device = await self.get_device_by_id(device_id)

        try:
            vas_device = await self._vas.get_device(device.vas_device_id)
        except VASNotFoundError:
            # Device removed from VAS
            device.is_active = False
            logger.warning(
                "Device no longer exists in VAS",
                device_id=str(device_id),
                vas_device_id=device.vas_device_id,
            )
            return device
        except VASError as e:
            logger.error(
                "Failed to refresh device status",
                device_id=str(device_id),
                error=str(e),
            )
            raise DeviceSyncError(
                f"Failed to refresh device {device_id}",
                cause=e,
            ) from e

        # Update local record
        device.name = vas_device.name
        device.description = vas_device.description
        device.location = vas_device.location
        device.is_active = vas_device.is_active
        device.last_synced_at = datetime.now(timezone.utc)

        return device
