import zmq
import time

def start_bus():
    context = zmq.Context()

    # Frontend socket talks to publishers over TCP
    frontend = context.socket(zmq.XSUB)
    frontend.bind("tcp://*:5555")

    # Backend socket talks to subscribers over TCP
    backend = context.socket(zmq.XPUB)
    backend.bind("tcp://*:5556")
    
    print("ZMQ Broker started (IN: 5555 | OUT: 5556)")

    try:
        zmq.proxy(frontend, backend)
    except KeyboardInterrupt:
        print("ZMQ Broker stopping...")
    except Exception as e:
        print(f"ZMQ Proxy error: {e}")

if __name__ == "__main__":
    start_bus()
