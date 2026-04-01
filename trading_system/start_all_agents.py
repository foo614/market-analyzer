import subprocess
import sys
import time
import os

def start_agent(agent_name, file_name):
    """Starts an agent script as a separate process."""
    print(f"Starting {agent_name}...")
    agent_path = os.path.join(os.path.dirname(__file__), 'agents', file_name)
    
    # We use Popen so we don't block. We let them print to stdout/stderr.
    process = subprocess.Popen([sys.executable, agent_path])
    return process

if __name__ == "__main__":
    print("========================================")
    print("Starting ClawdBot Multi-Agent System")
    print("========================================")
    print("DEMO: Fully Automated Paper Trading")
    print("REAL: Manual Signals & Telegram Monitoring")
    print("========================================")
    
    processes = []
    
    try:
        # Start the ZeroMQ broker first!
        print("Starting ZeroMQ Message Broker...")
        bus_process = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(__file__), 'bus_server.py')])
        processes.append(bus_process)
        time.sleep(2) # Give socket time to bind
        
        # Start the agents
        processes.append(start_agent("Notification Agent", "notification_agent.py"))
        time.sleep(1) 
        processes.append(start_agent("Execution Agent", "execution_agent.py"))
        time.sleep(1)
        processes.append(start_agent("Quant Agent", "quant_agent.py"))
        time.sleep(1)
        processes.append(start_agent("Data Agent", "data_agent.py"))
        time.sleep(1)
        processes.append(start_agent("Sentiment Agent", "sentiment_agent.py"))
        time.sleep(1)
        processes.append(start_agent("Tracker Agent", "etoro_tracker.py"))
        
        print("\nAll agents are running successfully!")
        print("Press Ctrl+C to stop all agents.\n")
        
        for p in processes:
            p.wait()
            
    except KeyboardInterrupt:
        print("\nStopping all agents...")
        for p in processes:
            p.terminate()
        print("System shutdown complete.")
    except Exception as e:
        print(f"Failed to start system: {e}")
        for p in processes:
            p.terminate()
