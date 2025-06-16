import logging
from radiox_spotify import bot_instance

def main():
    logging.info("[run_bot.py] Starting RadioXBot main loop as a background worker.")
    bot_instance.authenticate_spotify()
    bot_instance.load_state()
    bot_instance.run_startup_diagnostics(send_email=False)
    bot_instance.run()

if __name__ == "__main__":
    main() 