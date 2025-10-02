import { useEffect, useRef, useState, useCallback } from 'react';

export interface UseWebSocketOptions {
  url: string;
  reconnectInterval?: number;
  reconnectAttempts?: number;
  onOpen?: (event: Event) => void;
  onClose?: (event: CloseEvent) => void;
  onError?: (event: Event) => void;
  onMessage?: (data: any) => void;
  shouldReconnect?: boolean;
}

export interface UseWebSocketReturn {
  connected: boolean;
  lastMessage: string | null;
  sendMessage: (message: string | object) => void;
  disconnect: () => void;
  reconnect: () => void;
}

export const useWebSocket = ({
  url,
  reconnectInterval = 3000,
  reconnectAttempts = 5,
  onOpen,
  onClose,
  onError,
  onMessage,
  shouldReconnect = true,
}: UseWebSocketOptions): UseWebSocketReturn => {
  const [connected, setConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectCountRef = useRef(0);
  const shouldReconnectRef = useRef(shouldReconnect);
  const unmountedRef = useRef(false);

  // Update shouldReconnect ref when prop changes
  useEffect(() => {
    shouldReconnectRef.current = shouldReconnect;
  }, [shouldReconnect]);

  const clearReconnectTimeout = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    if (unmountedRef.current) return;

    // Close existing connection if any
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    try {
      console.log(`[WebSocket] Connecting to ${url}...`);
      const ws = new WebSocket(url);

      ws.onopen = (event) => {
        if (unmountedRef.current) {
          ws.close();
          return;
        }

        console.log('[WebSocket] Connected');
        setConnected(true);
        reconnectCountRef.current = 0;
        clearReconnectTimeout();

        if (onOpen) {
          onOpen(event);
        }
      };

      ws.onmessage = (event) => {
        if (unmountedRef.current) return;

        try {
          const data = event.data;
          setLastMessage(data);

          if (onMessage) {
            try {
              const parsedData = JSON.parse(data);
              onMessage(parsedData);
            } catch {
              onMessage(data);
            }
          }
        } catch (error) {
          console.error('[WebSocket] Error processing message:', error);
        }
      };

      ws.onerror = (event) => {
        console.error('[WebSocket] Error:', event);

        if (onError) {
          onError(event);
        }
      };

      ws.onclose = (event) => {
        if (unmountedRef.current) return;

        console.log(
          `[WebSocket] Disconnected (code: ${event.code}, reason: ${event.reason || 'none'})`
        );
        setConnected(false);

        if (onClose) {
          onClose(event);
        }

        // Attempt to reconnect if enabled and not exceeded attempts
        if (
          shouldReconnectRef.current &&
          reconnectCountRef.current < reconnectAttempts
        ) {
          reconnectCountRef.current++;
          console.log(
            `[WebSocket] Reconnecting in ${reconnectInterval}ms (attempt ${reconnectCountRef.current}/${reconnectAttempts})...`
          );

          clearReconnectTimeout();
          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, reconnectInterval);
        } else if (reconnectCountRef.current >= reconnectAttempts) {
          console.log('[WebSocket] Max reconnection attempts reached');
        }
      };

      wsRef.current = ws;
    } catch (error) {
      console.error('[WebSocket] Connection error:', error);
      setConnected(false);

      // Attempt to reconnect on connection error
      if (
        shouldReconnectRef.current &&
        reconnectCountRef.current < reconnectAttempts
      ) {
        reconnectCountRef.current++;
        clearReconnectTimeout();
        reconnectTimeoutRef.current = setTimeout(() => {
          connect();
        }, reconnectInterval);
      }
    }
  }, [
    url,
    reconnectInterval,
    reconnectAttempts,
    onOpen,
    onClose,
    onError,
    onMessage,
    clearReconnectTimeout,
  ]);

  const disconnect = useCallback(() => {
    console.log('[WebSocket] Manually disconnecting...');
    shouldReconnectRef.current = false;
    clearReconnectTimeout();

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    setConnected(false);
  }, [clearReconnectTimeout]);

  const reconnect = useCallback(() => {
    console.log('[WebSocket] Manually reconnecting...');
    shouldReconnectRef.current = true;
    reconnectCountRef.current = 0;
    clearReconnectTimeout();

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    connect();
  }, [connect, clearReconnectTimeout]);

  const sendMessage = useCallback((message: string | object) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      const data = typeof message === 'string' ? message : JSON.stringify(message);
      wsRef.current.send(data);
    } else {
      console.warn('[WebSocket] Cannot send message: WebSocket is not connected');
    }
  }, []);

  // Initial connection
  useEffect(() => {
    unmountedRef.current = false;
    connect();

    return () => {
      unmountedRef.current = true;
      shouldReconnectRef.current = false;
      clearReconnectTimeout();

      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect, clearReconnectTimeout]);

  return {
    connected,
    lastMessage,
    sendMessage,
    disconnect,
    reconnect,
  };
};
