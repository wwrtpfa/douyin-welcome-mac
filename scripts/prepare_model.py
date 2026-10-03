"""Download the voice model ahead of a livestream. No audio is uploaded."""
from welcome_assistant.model_store import model_path

if __name__ == "__main__":
    print(model_path(lambda message: print(message, flush=True)))
