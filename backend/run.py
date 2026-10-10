"""Start the Jarvis backend: python run.py"""
import logging

import uvicorn


class _QuietPolls(logging.Filter):
    """The desktop app polls the screen-activity state 5x a second."""
    def filter(self, record: logging.LogRecord) -> bool:
        return "/api/screen/activity" not in record.getMessage()


if __name__ == "__main__":
    logging.getLogger("uvicorn.access").addFilter(_QuietPolls())
    uvicorn.run("app.main:app", host="127.0.0.1", port=8765, reload=False)
