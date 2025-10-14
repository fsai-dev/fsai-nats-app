# fsai-nats-app

# NatsApp - NATS JetStream Wrapper

A Python wrapper that provides a FastStream-like interface for NATS JetStream, making it easy to build robust message-driven microservices with minimal boilerplate code.

[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://python.org)
[![NATS](https://img.shields.io/badge/NATS-JetStream-green.svg)](https://nats.io)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## ✨ Features

- 🚀 **FastStream-like API** - Familiar decorator-based interface for easy adoption
- 🔄 **Graceful Shutdown** - Configurable timeout ensuring message processing completion
- 🛡️ **Robust Error Handling** - Automatic message acknowledgment/negative acknowledgment with retry logic
- 🔌 **Auto-Reconnection** - Built-in connection resilience with exponential backoff
- 📦 **Pydantic Integration** - Seamless validation with Pydantic models
- ⚡ **Pull Subscriptions** - Efficient JetStream pull-based message consumption
- 🎯 **Multiple Subscribers** - Support for multiple concurrent message handlers
- 📊 **Monitoring** - Built-in subscription statistics and health monitoring
- 🐛 **Debug Mode** - Comprehensive logging for development and troubleshooting

## 🚀 Quick Start

### Installation

```bash
pip install nats-py pydantic loguru
```

### Basic Example

```python
import asyncio
from pydantic import BaseModel
from nats_wrapper import ConsumerConfig, PullSubConfig, StreamConfig, create_nats_app

# Define your data models
class UserMessage(BaseModel):
    user_id: int
    content: str
    timestamp: str

class ProcessedMessage(BaseModel):
    user_id: int
    processed_content: str
    status: str

# Create the NATS application
app = create_nats_app(
    servers=["nats://localhost:4222"],
    graceful_timeout=30
)

# Create a publisher
output_publisher = app.publisher(
    subject="processed.messages",
    stream=StreamConfig(name="PROCESSED_STREAM", declare=False)
)

# Define message handler with decorator
@app.subscriber(
    subject="user.messages",
    stream=StreamConfig(name="USER_STREAM", declare=False),
    durable="message_processor",
    pull_sub=PullSubConfig(batch_size=1, timeout=5),
    config=ConsumerConfig(ack_wait=30, max_deliver=3)
)
async def process_user_message(data, msg):
    # Validate incoming data
    user_msg = UserMessage(**data)
    
    # Process the message
    processed_content = f"Processed: {user_msg.content}"
    
    # Create and publish result
    result = ProcessedMessage(
        user_id=user_msg.user_id,
        processed_content=processed_content,
        status="completed"
    )
    
    await output_publisher.publish(result)

# Run the application
async def main():
    await app.run()

if __name__ == "__main__":
    asyncio.run(main())
```

## 📚 Documentation

### Application Configuration

Create a NATS application with custom configuration:

```python
app = create_nats_app(
    servers=["nats://server1:4222", "nats://server2:4222"],  # Multiple servers for HA
    graceful_timeout=60,           # Shutdown timeout in seconds
    allow_reconnect=True,          # Enable auto-reconnection
    reconnect_time_wait=2,         # Wait time between reconnection attempts
    max_reconnect_attempts=10000,  # Maximum reconnection attempts (-1 for infinite)
    ping_interval=5,               # Health check ping interval
    connect_timeout=2.0,           # Initial connection timeout
    logger_instance=my_logger,     # Custom logger instance (optional)
    message_parser=my_parser_func  # Custom message parser function (optional)
)
```

### Subscriber Configuration

Configure message subscribers with fine-grained control:

```python
@app.subscriber(
    subject="order.created",              # NATS subject to subscribe to
    stream=StreamConfig(                  # JetStream configuration
        name="ORDER_EVENTS", 
        declare=False                     # Don't create stream (assume exists)
    ),
    durable="order_processor",            # Durable consumer name
    pull_sub=PullSubConfig(               # Pull subscription settings
        batch_size=5,                     # Process up to 5 messages at once
        timeout=10                        # Timeout for message fetching
    ),
    config=ConsumerConfig(                # Consumer behavior
        ack_wait=60,                      # Time to wait for ACK before retry
        max_deliver=3                     # Maximum delivery attempts
    )
)
async def handle_order_created(data, msg):
    # Your message processing logic here
    order = OrderModel(**data)
    await process_order(order)
```

### Publisher Configuration

Create publishers for sending messages:

```python
# Simple publisher
publisher = app.publisher(
    subject="order.notifications",
    stream=StreamConfig(name="NOTIFICATION_STREAM", declare=False),
    timeout=30  # Publish timeout
)

# Publishing messages
await publisher.publish({"order_id": 123, "status": "completed"})
await publisher.publish(OrderNotification(order_id=123, status="completed"))  # Pydantic model
```

### Environment-Based Configuration

Use environment variables for deployment flexibility:

```python
import os

app = create_nats_app(
    servers=os.getenv("NATS_SERVERS", "nats://localhost:4222").split(","),
    graceful_timeout=int(os.getenv("GRACEFUL_SHUTDOWN_TIMEOUT", "30"))
)

@app.subscriber(
    subject=os.getenv("INPUT_SUBJECT", "default.input"),
    stream=StreamConfig(name=os.getenv("INPUT_STREAM", "DEFAULT_STREAM")),
    durable=os.getenv("CONSUMER_GROUP", "default_consumer")
)
async def handler(data, msg):
    # Process message
    pass
```

## 🔧 Advanced Usage

### Multiple Subscribers

Handle different message types with multiple subscribers:

```python
@app.subscriber(
    subject="user.created",
    stream=StreamConfig(name="USER_EVENTS"),
    durable="user_created_processor"
)
async def handle_user_created(data, msg):
    user = UserCreatedEvent(**data)
    await send_welcome_email(user)

@app.subscriber(
    subject="user.updated", 
    stream=StreamConfig(name="USER_EVENTS"),
    durable="user_updated_processor"
)
async def handle_user_updated(data, msg):
    user = UserUpdatedEvent(**data)
    await update_user_cache(user)

@app.subscriber(
    subject="user.deleted",
    stream=StreamConfig(name="USER_EVENTS"), 
    durable="user_deleted_processor"
)
async def handle_user_deleted(data, msg):
    user = UserDeletedEvent(**data)
    await cleanup_user_data(user)
```

### Error Handling and Retry Logic

The wrapper automatically handles errors and retries:

```python
@app.subscriber(
    subject="payment.process",
    stream=StreamConfig(name="PAYMENT_STREAM"),
    durable="payment_processor",
    config=ConsumerConfig(
        ack_wait=30,      # 30 second timeout
        max_deliver=5     # Retry up to 5 times
    )
)
async def process_payment(data, msg):
    try:
        payment = PaymentRequest(**data)
        
        # This might fail and trigger retry
        result = await external_payment_service.charge(payment)
        
        # Publish success event
        await success_publisher.publish(PaymentSuccess(**result))
        
    except ValidationError as e:
        # Invalid data - don't retry
        logger.error(f"Invalid payment data: {e}")
        await msg.term()  # Terminate message (no retry)
        
    except PaymentServiceError as e:
        # Temporary error - will retry automatically
        logger.warning(f"Payment service error: {e}")
        raise  # Let wrapper handle retry logic
        
    except Exception as e:
        # Unknown error - retry
        logger.error(f"Unexpected error: {e}")
        raise
```

### Manual Message Acknowledgment

Control message acknowledgment manually when needed:

```python
@app.subscriber(
    subject="batch.process",
    stream=StreamConfig(name="BATCH_STREAM"),
    durable="batch_processor"
)
async def process_batch(data, msg):
    batch = BatchJob(**data)
    
    try:
        # Start processing
        await start_batch_job(batch)
        
        # Don't auto-ack yet - wait for completion
        # Manually acknowledge when ready
        await msg.ack()
        
    except TemporaryError:
        # Negative ack for redelivery
        await msg.nak()
        
    except PermanentError:
        # Terminate message (permanent failure)
        await msg.term()
```

### Monitoring and Statistics

Monitor your application's health:

```python
# Enable debug logging
app.enable_debug_logging(True)

# Get subscription statistics
stats = app.get_subscription_stats()
print(f"Active subscribers: {stats['total_subscribers']}")
print(f"Connection status: {stats['connection_status']}")

# Log detailed statistics
app.log_subscription_stats()
```

### Batch Processing

Process messages in batches for better throughput:

```python
@app.subscriber(
    subject="analytics.events",
    stream=StreamConfig(name="ANALYTICS_STREAM"),
    durable="analytics_batch_processor",
    pull_sub=PullSubConfig(
        batch_size=50,    # Process 50 messages at once
        timeout=5         # 5 second batch timeout
    )
)
async def process_analytics_batch(data, msg):
    # This handler will receive up to 50 messages
    event = AnalyticsEvent(**data)
    await store_analytics_event(event)
```

### Custom Message Parsers

Override the default message parsing logic with a custom parser function:

```python
def custom_message_parser(message_bytes: bytes) -> Any:
    """
    Custom parser that handles special message formats.
    
    Args:
        message_bytes: Raw message bytes from NATS
        
    Returns:
        Parsed data in any format (dict, object, string, etc.)
        
    Raises:
        Exception: If parsing fails, will fall back to default parser
    """
    # Example: Parse Protocol Buffer messages
    try:
        proto_message = MyProtoMessage()
        proto_message.ParseFromString(message_bytes)
        return proto_message
    except Exception:
        # If custom parsing fails, default parser will be used
        raise

# Create app with custom parser
app = create_nats_app(
    servers=["nats://localhost:4222"],
    message_parser=custom_message_parser
)

@app.subscriber(
    subject="proto.messages",
    stream=StreamConfig(name="PROTO_STREAM"),
    durable="proto_processor"
)
async def handle_proto_message(data, msg):
    # data is already parsed by custom_message_parser
    # data will be a MyProtoMessage instance
    process_proto_data(data)
```

#### Common Custom Parser Use Cases

**1. Protocol Buffers:**
```python
import my_proto_pb2

def protobuf_parser(message_bytes: bytes):
    message = my_proto_pb2.MyMessage()
    message.ParseFromString(message_bytes)
    return message

app = create_nats_app(
    servers=["nats://localhost:4222"],
    message_parser=protobuf_parser
)
```

**2. MessagePack:**
```python
import msgpack

def msgpack_parser(message_bytes: bytes):
    return msgpack.unpackb(message_bytes, raw=False)

app = create_nats_app(
    servers=["nats://localhost:4222"],
    message_parser=msgpack_parser
)
```

**3. AVRO:**
```python
import avro.io
import io

def avro_parser(message_bytes: bytes):
    bytes_reader = io.BytesIO(message_bytes)
    decoder = avro.io.BinaryDecoder(bytes_reader)
    reader = avro.io.DatumReader(avro_schema)
    return reader.read(decoder)

app = create_nats_app(
    servers=["nats://localhost:4222"],
    message_parser=avro_parser
)
```

**4. Custom Binary Format:**
```python
import struct

def custom_binary_parser(message_bytes: bytes):
    # Parse custom binary format: 4 bytes int, 8 bytes timestamp, rest is string
    message_id = struct.unpack('>I', message_bytes[:4])[0]
    timestamp = struct.unpack('>Q', message_bytes[4:12])[0]
    payload = message_bytes[12:].decode('utf-8')
    
    return {
        'id': message_id,
        'timestamp': timestamp,
        'payload': payload
    }

app = create_nats_app(
    servers=["nats://localhost:4222"],
    message_parser=custom_binary_parser
)
```

#### Default Parser Behavior

If no custom parser is provided (or if the custom parser raises an exception), the default parser will:

1. **Try UTF-8 decoding**: Attempt to decode bytes as UTF-8 text
2. **Try JSON parsing**: If UTF-8 successful, try parsing as JSON
3. **Fallback to string**: If not JSON, return as plain string
4. **Return raw bytes**: If not UTF-8, return original bytes

```python
# Default parsing logic (automatic):
# - JSON message: {"key": "value"} → dict
# - Plain text: "hello" → str
# - Binary data: b'\x00\x01\x02' → bytes
```

#### Error Handling with Custom Parsers

If your custom parser raises an exception, the default parser will automatically be used as a fallback:

```python
def strict_json_parser(message_bytes: bytes):
    """Only parse JSON, fail otherwise"""
    import json
    return json.loads(message_bytes.decode('utf-8'))  # Will raise on non-JSON

app = create_nats_app(
    servers=["nats://localhost:4222"],
    message_parser=strict_json_parser
)

# If strict_json_parser fails:
# - Exception is logged
# - Default parser takes over
# - Message still gets processed
```

## 🔄 Migration from FastStream

Migrating from FastStream is straightforward:

### Before (FastStream):
```python
from faststream import FastStream
from faststream.nats import NatsBroker, JStream, PullSub

broker = NatsBroker("nats://localhost:4222")
app = FastStream(broker)

@broker.subscriber(
    "input.messages",
    stream=JStream("INPUT_STREAM"),
    pull_sub=PullSub(batch_size=1)
)
async def handler(data: MyModel):
    # Process data
    pass
```

### After (NatsApp):
```python
from nats_wrapper import create_nats_app, StreamConfig, PullSubConfig

app = create_nats_app("nats://localhost:4222")

@app.subscriber(
    subject="input.messages",
    stream=StreamConfig(name="INPUT_STREAM"),
    durable="my_consumer",
    pull_sub=PullSubConfig(batch_size=1)
)
async def handler(data, msg):
    # Validate data manually
    validated_data = MyModel(**data)
    # Process data
    pass
```

### Key Migration Points:

1. **Handler Signature**: Change from `(model)` to `(data, msg)`
2. **Manual Validation**: Add Pydantic validation in handler
3. **Durable Consumer**: Specify consumer name explicitly
4. **Message Access**: Use `msg` parameter for advanced operations

## 🌟 Real-World Example

Here's a complete microservice example:

```python
import asyncio
import os
from datetime import datetime
from pydantic import BaseModel
from loguru import logger
from nats_wrapper import create_nats_app, StreamConfig, PullSubConfig, ConsumerConfig

# Data Models
class OrderCreated(BaseModel):
    order_id: str
    user_id: str
    total_amount: float
    items: list[dict]

class OrderProcessed(BaseModel):
    order_id: str
    status: str
    processed_at: datetime
    tracking_number: str

class InventoryUpdate(BaseModel):
    item_id: str
    quantity_reserved: int

# Application Setup
app = create_nats_app(
    servers=os.getenv("NATS_SERVERS", "nats://localhost:4222").split(","),
    graceful_timeout=60,
    logger_instance=logger
)

# Publishers
order_status_publisher = app.publisher(
    subject="order.status",
    stream=StreamConfig(name="ORDER_STATUS_STREAM")
)

inventory_publisher = app.publisher(
    subject="inventory.updates", 
    stream=StreamConfig(name="INVENTORY_STREAM")
)

# Order Processing Service
@app.subscriber(
    subject="order.created",
    stream=StreamConfig(name="ORDER_EVENTS"),
    durable="order_processor_service",
    pull_sub=PullSubConfig(batch_size=3, timeout=10),
    config=ConsumerConfig(ack_wait=120, max_deliver=3)
)
async def process_order(data, msg):
    """Process new orders and update inventory"""
    try:
        # Validate order data
        order = OrderCreated(**data)
        logger.info(f"Processing order {order.order_id} for user {order.user_id}")
        
        # Reserve inventory for each item
        for item in order.items:
            inventory_update = InventoryUpdate(
                item_id=item["id"],
                quantity_reserved=item["quantity"]
            )
            await inventory_publisher.publish(inventory_update)
        
        # Generate tracking number
        tracking_number = f"TRK{order.order_id}{datetime.now().strftime('%Y%m%d')}"
        
        # Create processed order status
        processed_order = OrderProcessed(
            order_id=order.order_id,
            status="processed",
            processed_at=datetime.now(),
            tracking_number=tracking_number
        )
        
        # Publish status update
        await order_status_publisher.publish(processed_order)
        
        logger.info(f"Successfully processed order {order.order_id} with tracking {tracking_number}")
        
    except ValidationError as e:
        logger.error(f"Invalid order data: {e}")
        await msg.term()  # Don't retry invalid data
        
    except InventoryServiceError as e:
        logger.warning(f"Inventory service error for order {order.order_id}: {e}")
        raise  # Retry on inventory service errors
        
    except Exception as e:
        logger.error(f"Unexpected error processing order {order.order_id}: {e}")
        raise

# Health Check Endpoint
@app.subscriber(
    subject="service.health.check",
    stream=StreamConfig(name="HEALTH_STREAM"),
    durable="order_service_health"
)
async def health_check(data, msg):
    """Respond to health check requests"""
    stats = app.get_subscription_stats()
    
    health_response = {
        "service": "order-processor",
        "status": "healthy" if stats["connection_status"] == "connected" else "unhealthy",
        "timestamp": datetime.now().isoformat(),
        "stats": stats
    }
    
    if msg.reply:
        await app.nc.publish(msg.reply, json.dumps(health_response).encode())

# Service Entry Point
async def main():
    logger.info("🚀 Starting Order Processing Service")
    logger.info(f"📊 Configuration: NATS={os.getenv('NATS_SERVERS')}")
    
    # Run the service
    await app.run()

if __name__ == "__main__":
    asyncio.run(main())
```

## 🔧 Configuration Reference

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `NATS_SERVERS` | Comma-separated NATS server URLs | `nats://localhost:4222` |
| `GRACEFUL_SHUTDOWN_TIMEOUT` | Shutdown timeout in seconds | `30` |
| `NATS_DEBUG` | Enable debug logging | `false` |
| `INPUT_STREAM` | Input stream name | - |
| `INPUT_SUBJECT` | Input subject pattern | - |
| `OUTPUT_STREAM` | Output stream name | - |
| `OUTPUT_SUBJECT` | Output subject pattern | - |
| `CONSUMER_GROUP` | Consumer group/durable name | - |

### Docker Environment

```yaml
version: '3.8'
services:
  order-processor:
    image: my-app:latest
    environment:
      - NATS_SERVERS=nats://nats-server:4222
      - INPUT_STREAM=ORDER_EVENTS
      - INPUT_SUBJECT=order.created
      - OUTPUT_STREAM=ORDER_STATUS
      - OUTPUT_SUBJECT=order.processed
      - CONSUMER_GROUP=order_processor_v1
      - GRACEFUL_SHUTDOWN_TIMEOUT=60
      - NATS_DEBUG=false
    depends_on:
      - nats-server
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built on top of the excellent [nats-py](https://github.com/nats-io/nats.py) library
- Inspired by [FastStream](https://github.com/airtai/faststream) for the developer experience
- Uses [Pydantic](https://pydantic-docs.helpmanual.io/) for data validation
- Logging powered by [Loguru](https://github.com/Delgan/loguru)
