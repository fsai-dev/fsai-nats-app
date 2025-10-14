"""
NATS JetStream wrapper providing a FastStream-like interface for easy message handling.
"""

import asyncio
import json
import signal
import sys
from typing import Any, Callable, Dict, List, Union

import nats
from loguru import logger
from nats.errors import TimeoutError



class ConsumerConfig:
    """Consumer configuration similar to FastStream ConsumerConfig"""
    
    def __init__(self, ack_wait: int = 30, max_deliver: int = 3):
        self.ack_wait = ack_wait
        self.max_deliver = max_deliver


class StreamConfig:
    """Stream configuration"""
    
    def __init__(self, name: str, declare: bool = False):
        self.name = name
        self.declare = declare


class PullSubConfig:
    """Pull subscription configuration"""
    
    def __init__(self, batch_size: int = 1, timeout: int = 5):
        self.batch_size = batch_size
        self.timeout = timeout


class NatsApp:
    """Main NATS application class providing FastStream-like interface"""
    
    def __init__(
        self,
        servers: Union[str, List[str]],
        graceful_timeout: int = 40,
        allow_reconnect: bool = True,
        reconnect_time_wait: int = 2,
        max_reconnect_attempts: int = 10000,
        ping_interval: int = 5,
        connect_timeout: float = 2.0,
        logger_instance=None,
        message_parser: Callable[[bytes], Any] = None
    ):
        self.servers = servers if isinstance(servers, list) else [servers]
        self.graceful_timeout = graceful_timeout
        self.allow_reconnect = allow_reconnect
        self.reconnect_time_wait = reconnect_time_wait
        self.max_reconnect_attempts = max_reconnect_attempts
        self.ping_interval = ping_interval
        self.connect_timeout = connect_timeout
        self.logger = logger_instance or logger
        self.message_parser = message_parser
        
        # Connection state
        self.nc = None
        self.js = None
        self.running = True
        self.processing_message = False
        self.shutdown_requested = False
        
        # Subscribers and publishers
        self.subscribers = []
        self.publishers = {}
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        self.logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.shutdown_requested = True
        self.running = False
    
    async def _disconnected_cb(self):
        """Handle disconnection from NATS server"""
        self.logger.error("🔌 Disconnected from NATS server")
        self.logger.debug("Connection state: DISCONNECTED")
    
    async def _error_cb(self, e):
        """Handle NATS errors"""
        self.logger.error(f"❌ NATS error: {e}")
        self.logger.debug(f"Error details: {type(e).__name__}: {str(e)}")
    
    async def _closed_cb(self):
        """Handle connection closure"""
        self.logger.error("🚪 Connection to NATS server is closed")
        self.logger.debug("Connection state: CLOSED")
    
    async def _reconnected_cb(self):
        """Handle reconnection to NATS server"""
        self.logger.info("🔄 Reconnected to NATS server")
        self.logger.debug("Connection state: RECONNECTED")
        
        # Log current server info
        if self.nc and hasattr(self.nc, '_current_server'):
            self.logger.debug(f"Connected to server: {self.nc._current_server}")
    
    def enable_debug_logging(self, enabled: bool = True):
        """Enable or disable debug logging"""
        if enabled:
            self.logger.info("🐛 Debug logging enabled")
        else:
            self.logger.info("🔇 Debug logging disabled")
        # Note: This would typically set logger level, but loguru handles this differently
        # Users can set LOGURU_LEVEL=DEBUG environment variable instead
    
    def get_subscription_stats(self) -> Dict[str, Any]:
        """Get statistics for all subscriptions"""
        stats = {
            'total_subscribers': len(self.subscribers),
            'connection_status': 'connected' if self.nc and not self.nc.is_closed else 'disconnected',
            'processing_message': self.processing_message,
            'shutdown_requested': self.shutdown_requested,
            'subscribers': []
        }
        
        for sub_info in self.subscribers:
            sub_stats = {
                'subject': sub_info['subject'],
                'stream': sub_info['stream'].name,
                'durable': sub_info['durable'],
                'handler': sub_info['func'].__name__,
                'messages_processed': sub_info.get('message_count', 0),
                'errors': sub_info.get('error_count', 0),
                'batch_size': sub_info['pull_sub'].batch_size,
                'timeout': sub_info['pull_sub'].timeout,
                'ack_wait': sub_info['config'].ack_wait,
                'max_deliver': sub_info['config'].max_deliver
            }
            stats['subscribers'].append(sub_stats)
        
        return stats
    
    def log_subscription_stats(self):
        """Log current subscription statistics"""
        stats = self.get_subscription_stats()
        
        self.logger.info("📊 Subscription Statistics:")
        self.logger.info(f"  - Total subscribers: {stats['total_subscribers']}")
        self.logger.info(f"  - Connection status: {stats['connection_status']}")
        self.logger.info(f"  - Currently processing: {stats['processing_message']}")
        
        for sub_stats in stats['subscribers']:
            self.logger.info(f"  📬 {sub_stats['subject']}:")
            self.logger.info(f"    - Handler: {sub_stats['handler']}")
            self.logger.info(f"    - Messages: {sub_stats['messages_processed']}")
            self.logger.info(f"    - Errors: {sub_stats['errors']}")
            self.logger.info(f"    - Config: batch={sub_stats['batch_size']}, timeout={sub_stats['timeout']}s")
    
    def subscriber(
        self,
        subject: str,
        stream: StreamConfig,
        durable: str,
        pull_sub: PullSubConfig = None,
        config: ConsumerConfig = None
    ):
        """Decorator for creating message subscribers"""
        if pull_sub is None:
            pull_sub = PullSubConfig()
        if config is None:
            config = ConsumerConfig()
        
        def decorator(func: Callable):
            subscriber_info = {
                'func': func,
                'subject': subject,
                'stream': stream,
                'durable': durable,
                'pull_sub': pull_sub,
                'config': config
            }
            self.subscribers.append(subscriber_info)
            return func
        
        return decorator
    
    def publisher(
        self,
        subject: str,
        stream: StreamConfig = None,
        timeout: int = 30
    ):
        """Create a publisher for a subject"""
        publisher_info = {
            'subject': subject,
            'stream': stream,
            'timeout': timeout
        }
        
        class Publisher:
            def __init__(self, app_instance, info):
                self.app = app_instance
                self.info = info
            
            async def publish(self, data: Union[Any, dict, str, bytes]):
                """Publish a message"""
                if isinstance(data, bytes):
                    message_data = data
                elif hasattr(data, 'model_dump'):
                    # Handle pydantic BaseModel instances (duck typing)
                    message_data = json.dumps(data.model_dump()).encode()
                elif isinstance(data, dict):
                    message_data = json.dumps(data).encode()
                elif isinstance(data, str):
                    message_data = data.encode()
                else:
                    message_data = str(data).encode()
                
                await self.app.js.publish(self.info['subject'], message_data)
        
        publisher = Publisher(self, publisher_info)
        self.publishers[subject] = publisher
        return publisher
    
    async def _handle_message(self, msg, sub_info):
        """Handle incoming messages with error handling and state tracking"""
        handler_func = sub_info['func']
        subject = sub_info['subject']
        data_str = None  # Initialize to avoid UnboundLocalError
        
        try:
            self.processing_message = True
            
            # Parse message data using configurable parser or default logic
            if self.message_parser:
                try:
                    # Use custom message parser
                    data = self.message_parser(msg.data)
                    self.logger.debug(f"[{subject}] Successfully parsed message using custom parser: {len(msg.data)} bytes")
                except Exception as parser_error:
                    # If custom parser fails, fall back to default logic
                    self.logger.debug(f"[{subject}] Custom parser failed ({parser_error}), trying default parsing")
                    data = self._default_message_parsing(msg.data, subject)
            else:
                # Use default parsing logic
                data = self._default_message_parsing(msg.data, subject)
            
            # Log message metadata
            self.logger.debug(f"[{subject}] Message metadata:")
            self.logger.debug(f"  - Subject: {msg.subject}")
            self.logger.debug(f"  - Reply: {msg.reply}")
            self.logger.debug(f"  - Headers: {getattr(msg, 'headers', 'None')}")
            
            # Call the handler function
            self.logger.debug(f"[{subject}] Calling handler: {handler_func.__name__}")
            await handler_func(data, msg)
            
            # Acknowledge the message if not already done
            if not msg._ackd:
                await msg.ack()
                self.logger.debug(f"[{subject}] Message acknowledged")
            else:
                self.logger.debug(f"[{subject}] Message was already acknowledged by handler")
            
            # Update success counter
            sub_info['message_count'] += 1
            
            self.logger.debug(f"[{subject}] Message processing completed successfully")
                
        except Exception as e:
            sub_info['error_count'] += 1
            self.logger.error(f"[{subject}] Error processing message (error #{sub_info['error_count']}): {e}")
            
            # Log message data appropriately based on type
            if data_str is not None:
                self.logger.debug(f"[{subject}] Message data that caused error: {data_str}")
            else:
                self.logger.debug(f"[{subject}] Error occurred with binary message of {len(msg.data)} bytes")
            
            # Negative acknowledge to trigger redelivery
            if not msg._ackd:
                await msg.nak()
                self.logger.debug(f"[{subject}] Message negatively acknowledged for redelivery")
            
            raise
        finally:
            self.processing_message = False
    
    def _default_message_parsing(self, message_data: bytes, subject: str) -> Any:
        """Default message parsing logic - tries UTF-8 -> JSON -> string -> bytes"""
        data_str = None
        
        try:
            # Try to decode as UTF-8 text
            data_str = message_data.decode('utf-8')
            
            self.logger.debug(f"[{subject}] Received text message: {data_str[:100]}{'...' if len(data_str) > 100 else ''}")
            
            # Try to parse as JSON, fallback to string
            try:
                data = json.loads(data_str)
                self.logger.debug(f"[{subject}] Successfully parsed JSON message")
                return data
            except json.JSONDecodeError:
                self.logger.debug(f"[{subject}] Message is not JSON, using as string")
                return data_str
                
        except UnicodeDecodeError:
            # Not UTF-8, pass as raw bytes
            self.logger.debug(f"[{subject}] Not UTF-8 text, using raw bytes: {len(message_data)} bytes")
            return message_data
    
    async def connect(self):
        """Connect to NATS and setup JetStream"""
        self.logger.info(f"🚀 Connecting to NATS servers: {self.servers}")
        self.logger.debug("Connection parameters:")
        self.logger.debug(f"  - Allow reconnect: {self.allow_reconnect}")
        self.logger.debug(f"  - Reconnect wait time: {self.reconnect_time_wait}s")
        self.logger.debug(f"  - Max reconnect attempts: {self.max_reconnect_attempts}")
        self.logger.debug(f"  - Ping interval: {self.ping_interval}s")
        self.logger.debug(f"  - Connect timeout: {self.connect_timeout}s")
        
        try:
            self.nc = await nats.connect(
                servers=self.servers,
                disconnected_cb=self._disconnected_cb,
                error_cb=self._error_cb,
                closed_cb=self._closed_cb,
                reconnected_cb=self._reconnected_cb,
                allow_reconnect=self.allow_reconnect,
                reconnect_time_wait=self.reconnect_time_wait,
                max_reconnect_attempts=self.max_reconnect_attempts,
                ping_interval=self.ping_interval,
                connect_timeout=self.connect_timeout
            )
            
            # Log connection success details
            self.logger.info("✅ Successfully connected to NATS server")
            if hasattr(self.nc, '_current_server'):
                self.logger.debug(f"Connected to: {self.nc._current_server}")
            if hasattr(self.nc, 'connected_url'):
                self.logger.debug(f"Connected URL: {self.nc.connected_url}")
            
            self.js = self.nc.jetstream()
            self.logger.info("✅ JetStream context created successfully")
            self.logger.debug("NATS connection and JetStream setup complete")
            
        except Exception as e:
            self.logger.error(f"❌ Failed to connect to NATS: {e}")
            self.logger.debug(f"Connection error details: {type(e).__name__}: {str(e)}")
            raise
    
    async def _setup_subscribers(self):
        """Setup all registered subscribers"""
        self.logger.info(f"Setting up {len(self.subscribers)} subscriber(s)...")
        
        for i, sub_info in enumerate(self.subscribers, 1):
            self.logger.info(
                f"[{i}/{len(self.subscribers)}] Creating pull subscription:"
            )
            self.logger.info(f"  - Stream: {sub_info['stream'].name}")
            self.logger.info(f"  - Subject: {sub_info['subject']}")
            self.logger.info(f"  - Durable: {sub_info['durable']}")
            self.logger.info(f"  - Batch Size: {sub_info['pull_sub'].batch_size}")
            self.logger.info(f"  - Timeout: {sub_info['pull_sub'].timeout}s")
            self.logger.info(f"  - Ack Wait: {sub_info['config'].ack_wait}s")
            self.logger.info(f"  - Max Deliver: {sub_info['config'].max_deliver}")
            self.logger.info(f"  - Handler: {sub_info['func'].__name__}")
            
            try:
                psub = await self.js.pull_subscribe(
                    subject=sub_info['subject'],
                    durable=sub_info['durable'],
                    stream=sub_info['stream'].name,
                    config=nats.js.api.ConsumerConfig(
                        ack_wait=sub_info['config'].ack_wait,
                        max_deliver=sub_info['config'].max_deliver
                    )
                )
                
                sub_info['subscription'] = psub
                sub_info['message_count'] = 0  # Track processed messages
                sub_info['error_count'] = 0    # Track errors
                
                self.logger.info(f"  ✅ Successfully created subscription for {sub_info['subject']}")
                
            except Exception as e:
                self.logger.error(f"  ❌ Failed to create subscription for {sub_info['subject']}: {e}")
                raise
        
        self.logger.info("All subscribers setup complete!")
    
    async def _process_messages(self):
        """Main message processing loop"""
        self.logger.info("Starting message processing loop...")
        self.logger.debug(f"Processing {len(self.subscribers)} subscriber(s) in round-robin fashion")
        
        loop_count = 0
        total_messages_processed = 0
        
        while self.running:
            try:
                if self.shutdown_requested:
                    self.logger.info("Shutdown requested, stopping message fetching...")
                    break
                
                loop_count += 1
                messages_this_loop = 0
                
                # Process messages for each subscriber
                for sub_idx, sub_info in enumerate(self.subscribers):
                    if self.shutdown_requested:
                        break
                    
                    try:
                        psub = sub_info['subscription']
                        subject = sub_info['subject']
                        
                        self.logger.debug(
                            f"[Loop {loop_count}] Fetching messages from {subject} "
                            f"(batch_size={sub_info['pull_sub'].batch_size}, "
                            f"timeout={sub_info['pull_sub'].timeout}s)"
                        )
                        
                        msgs = await psub.fetch(
                            batch=sub_info['pull_sub'].batch_size,
                            timeout=sub_info['pull_sub'].timeout
                        )
                        
                        if msgs:
                            self.logger.debug(f"[{subject}] Received {len(msgs)} message(s)")
                            
                            for msg_idx, msg in enumerate(msgs, 1):
                                if self.shutdown_requested:
                                    self.logger.info("Shutdown requested, stopping message processing...")
                                    break
                                
                                self.logger.debug(
                                    f"[{subject}] Processing message {msg_idx}/{len(msgs)} "
                                    f"(total processed: {sub_info['message_count']})"
                                )
                                
                                await self._handle_message(msg, sub_info)
                                messages_this_loop += 1
                                total_messages_processed += 1
                        else:
                            self.logger.debug(f"[{subject}] No messages available")
                            
                    except TimeoutError:
                        # No messages available for this subscriber
                        self.logger.debug(f"[{sub_info['subject']}] Fetch timeout - no messages available")
                        continue
                    except Exception as e:
                        sub_info['error_count'] += 1
                        self.logger.error(
                            f"[{sub_info['subject']}] Error in subscriber processing "
                            f"(error #{sub_info['error_count']}): {e}"
                        )
                        await asyncio.sleep(1)
                
                # Log periodic stats
                if loop_count % 100 == 0:  # Every 100 loops
                    self.logger.info(f"Processing stats after {loop_count} loops:")
                    for sub_info in self.subscribers:
                        self.logger.info(
                            f"  - {sub_info['subject']}: "
                            f"{sub_info['message_count']} messages, "
                            f"{sub_info['error_count']} errors"
                        )
                
                # Small delay to prevent tight loop when no messages
                if messages_this_loop == 0:
                    await asyncio.sleep(0.1)
                    
            except Exception as e:
                self.logger.error(f"Error in message processing loop: {e}")
                await asyncio.sleep(1)
        
        self.logger.info(f"Message processing loop ended. Total messages processed: {total_messages_processed}")
    
    async def _graceful_shutdown(self):
        """Handle graceful shutdown"""
        if self.shutdown_requested and self.processing_message:
            self.logger.info(f"Waiting up to {self.graceful_timeout} seconds for current message processing to complete...")
            
            timeout_start = asyncio.get_event_loop().time()
            while (
                self.processing_message and 
                (asyncio.get_event_loop().time() - timeout_start) < self.graceful_timeout
            ):
                await asyncio.sleep(0.1)
            
            if self.processing_message:
                self.logger.warning(f"Timeout reached ({self.graceful_timeout}s), forcing shutdown...")
            else:
                self.logger.info("Current message processing completed, proceeding with shutdown")
    
    async def run(self):
        """Run the NATS application"""
        try:
            await self.connect()
            await self._setup_subscribers()
            await self._process_messages()
            await self._graceful_shutdown()
            
        except Exception as e:
            self.logger.error(f"Error in application: {e}")
            sys.exit(1)
        finally:
            if self.nc:
                self.logger.info("Closing NATS connection...")
                await self.nc.close()
            self.logger.info("Shutdown complete")


# Convenience function for creating apps
def create_nats_app(
    servers: Union[str, List[str]],
    **kwargs
) -> NatsApp:
    """Create a NATS application instance"""
    return NatsApp(servers, **kwargs)
