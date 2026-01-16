import { useEffect, useState } from 'react';
import type { Device } from '../types';
import { listDevices } from '../services/api';
import './DeviceList.css';

interface DeviceListProps {
  selectedDeviceId: string | null;
  onDeviceSelect: (device: Device) => void;
}

export function DeviceList({ selectedDeviceId, onDeviceSelect }: DeviceListProps) {
  const [devices, setDevices] = useState<Device[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadDevices();
  }, []);

  async function loadDevices() {
    setLoading(true);
    setError(null);

    try {
      const deviceList = await listDevices();
      setDevices(deviceList);
      console.log('[DeviceList] Loaded devices:', deviceList.length);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load devices';
      setError(message);
      console.error('[DeviceList] Error loading devices:', err);
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="device-list">
        <h2>Devices</h2>
        <div className="loading">Loading devices...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="device-list">
        <h2>Devices</h2>
        <div className="error">
          <p>{error}</p>
          <button onClick={loadDevices}>Retry</button>
        </div>
      </div>
    );
  }

  if (devices.length === 0) {
    return (
      <div className="device-list">
        <h2>Devices</h2>
        <div className="empty">No devices found</div>
        <button onClick={loadDevices} className="refresh-btn">
          Refresh
        </button>
      </div>
    );
  }

  return (
    <div className="device-list">
      <h2>Devices ({devices.length})</h2>
      <button onClick={loadDevices} className="refresh-btn">
        Refresh
      </button>
      <ul>
        {devices.map((device) => (
          <li
            key={device.id}
            className={`device-item ${selectedDeviceId === device.id ? 'selected' : ''} ${device.is_active ? 'active' : 'inactive'}`}
            onClick={() => onDeviceSelect(device)}
          >
            <div className="device-name">{device.name}</div>
            <div className="device-info">
              <span className="device-id">ID: {device.id.slice(0, 8)}...</span>
              {device.location && (
                <span className="device-location">{device.location}</span>
              )}
            </div>
            <div className={`device-status ${device.is_active ? 'active' : 'inactive'}`}>
              {device.is_active ? 'Active' : 'Inactive'}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
