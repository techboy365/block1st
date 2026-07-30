#!/usr/bin/env python3
"""
ProMailer Pro — Professional Bulk Email Sender
Entry point.
"""
import sys
import os

# Ensure the workspace root is on the path regardless of CWD
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    try:
        from gui.app import EmailSenderApp
    except ImportError as e:
        print(f"Import error: {e}")
        print("\nMissing dependencies. Please install them with:")
        print("  pip install -r requirements.txt\n")
        sys.exit(1)

    try:
        app = EmailSenderApp()
        app.run()
    except RuntimeError as e:
        print(f"\n{e}\n")
        print("Install with:  pip install customtkinter")
        sys.exit(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
