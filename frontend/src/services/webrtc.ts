import { Device as MediasoupDevice, types as mediasoupTypes } from 'mediasoup-client';
import * as api from './api';
import type { StreamStartResponse, ConsumeResponse } from '../types';

export interface WebRTCConnection {
  deviceId: string;
  streamId: string;
  consumerId: string;
  producerId: string;
  msDevice: MediasoupDevice;
  transport: mediasoupTypes.Transport;
  consumer: mediasoupTypes.Consumer;
  mediaStream: MediaStream;
}

function generateClientId(): string {
  return `ruth-portal-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

export async function connectToStream(
  deviceId: string,
  onConnectionStateChange?: (state: string) => void
): Promise<WebRTCConnection> {
  const clientId = generateClientId();
  console.log(`[WebRTC] Connecting to device ${deviceId} as client ${clientId}`);

  onConnectionStateChange?.('Starting stream...');
  let streamInfo: StreamStartResponse;
  try {
    streamInfo = await api.startStream(deviceId);
    console.log('[WebRTC] Stream started:', streamInfo);
    if (streamInfo.reconnect) {
      console.log('[WebRTC] Reconnecting to existing stream');
    }
  } catch (error) {
    console.error('[WebRTC] Failed to start stream:', error);
    throw new Error(`Failed to start stream: ${error}`);
  }

  const streamId = streamInfo.v2_stream_id;
  if (!streamId) {
    throw new Error('No stream ID returned from start-stream');
  }

  const producerId = streamInfo.producers?.video;
  if (!producerId) {
    throw new Error('No video producer ID returned from start-stream');
  }

  onConnectionStateChange?.('Waiting for stream to be live...');
  try {
    await api.waitForStreamLive(streamId);
    console.log('[WebRTC] Stream is LIVE');
  } catch (error) {
    console.error('[WebRTC] Stream failed to become live:', error);
    throw error;
  }

  onConnectionStateChange?.('Getting router capabilities...');
  const routerCaps = await api.getRouterCapabilities(streamId);
  console.log('[WebRTC] Router capabilities received');

  onConnectionStateChange?.('Initializing WebRTC device...');
  const msDevice = new MediasoupDevice();
  await msDevice.load({
    routerRtpCapabilities: routerCaps.rtp_capabilities as unknown as mediasoupTypes.RtpCapabilities,
  });
  console.log('[WebRTC] MediaSoup device loaded');

  onConnectionStateChange?.('Attaching consumer...');
  let consumeData: ConsumeResponse;
  try {
    consumeData = await api.attachConsumer(
      streamId,
      clientId,
      msDevice.rtpCapabilities as unknown as Record<string, unknown>
    );
    console.log('[WebRTC] Consumer attached:', consumeData.consumer_id);
  } catch (error) {
    console.error('[WebRTC] Failed to attach consumer:', error);
    throw error;
  }

  onConnectionStateChange?.('Creating transport...');
  const transport = msDevice.createRecvTransport({
    id: consumeData.transport.id,
    iceParameters: consumeData.transport.ice_parameters as unknown as mediasoupTypes.IceParameters,
    iceCandidates: consumeData.transport.ice_candidates as unknown as mediasoupTypes.IceCandidate[],
    dtlsParameters: consumeData.transport.dtls_parameters as unknown as mediasoupTypes.DtlsParameters,
  });

  transport.on('connect', async ({ dtlsParameters }, callback, errback) => {
    console.log('[WebRTC] Transport connect event - sending DTLS parameters');
    try {
      await api.connectConsumer(
        streamId,
        consumeData.consumer_id,
        dtlsParameters as unknown as Record<string, unknown>
      );
      console.log('[WebRTC] Transport connected successfully');
      callback();
    } catch (error) {
      console.error('[WebRTC] Transport connect failed:', error);
      errback(error as Error);
    }
  });

  transport.on('connectionstatechange', (state) => {
    console.log('[WebRTC] Transport connection state:', state);
    onConnectionStateChange?.(state);
  });

  onConnectionStateChange?.('Consuming video...');
  const consumer = await transport.consume({
    id: consumeData.consumer_id,
    producerId: producerId,
    kind: 'video',
    rtpParameters: consumeData.rtp_parameters as unknown as mediasoupTypes.RtpParameters,
  });

  console.log('[WebRTC] Consumer created, track:', consumer.track);
  await consumer.resume();
  console.log('[WebRTC] Consumer resumed');

  const mediaStream = new MediaStream([consumer.track]);
  onConnectionStateChange?.('connected');

  return {
    deviceId,
    streamId,
    consumerId: consumeData.consumer_id,
    producerId,
    msDevice,
    transport,
    consumer,
    mediaStream,
  };
}

export async function disconnectStream(
  connection: WebRTCConnection | null
): Promise<void> {
  if (!connection) {
    return;
  }

  console.log(`[WebRTC] Disconnecting from device ${connection.deviceId}`);

  try {
    if (connection.consumer && !connection.consumer.closed) {
      connection.consumer.close();
    }
    if (connection.transport && !connection.transport.closed) {
      connection.transport.close();
    }
    await api.detachConsumer(connection.streamId, connection.consumerId);
    console.log('[WebRTC] Consumer detached from server');
  } catch (error) {
    console.warn('[WebRTC] Error during disconnect:', error);
  }
}
