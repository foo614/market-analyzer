import zmq
import json
import uuid
import time
from datetime import datetime

class MessageBus:
    """
    A lightweight, ZeroMQ-backed message bus for agents to communicate.
    Replaces the legacy JSON file-based system.
    """
    def __init__(self):
        self.context = zmq.Context()
        self._pub_socket = None

    def get_pub(self):
        if not self._pub_socket:
            self._pub_socket = self.context.socket(zmq.PUB)
            self._pub_socket.connect("tcp://localhost:5555")
            # give it a tiny bit of time to establish tcp connection before burst firing
            time.sleep(0.1)
        return self._pub_socket

    def get_sub(self, topic):
        """Returns a connected SUB socket filtered by the topic."""
        sub_socket = self.context.socket(zmq.SUB)
        sub_socket.connect("tcp://localhost:5556")
        sub_socket.setsockopt_string(zmq.SUBSCRIBE, topic)
        return sub_socket

    def publish(self, topic, message):
        """Publish a message to a topic queue."""
        pub = self.get_pub()
        
        msg_wrapper = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now().isoformat(),
            "payload": message
        }
        
        json_data = json.dumps(msg_wrapper).encode('utf-8')
        topic_bytes = topic.encode('utf-8')
        
        # multipart: [topic_bytes, json_bytes]
        pub.send_multipart([topic_bytes, json_data])
        return msg_wrapper["id"]

    # --- Legacy File Fallbacks (Mocked to prevent old agents from crashing if not yet updated) ---
    def load_consumer_offset(self, consumer_name, topic):
        return None

    def save_consumer_offset(self, consumer_name, topic, last_id):
        pass
        
    def get_latest_id(self, topic):
        return None
        
    def consume(self, topic, last_id=None):
        raise NotImplementedError("consume() is deprecated. Agents must use get_sub() and zmq Event Loops.")

# Singleton instance for easy importing
bus = MessageBus()
