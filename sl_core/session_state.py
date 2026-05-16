"""Session state helpers for Streamlit apps."""


class SessionState(dict):
    """Lightweight dict-backed session state."""

    def get_or_set(self, key, default=None):
        if key not in self:
            self[key] = default
        return self[key]
