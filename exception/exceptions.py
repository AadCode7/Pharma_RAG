class AppError(Exception):
    """Base for every error we raise deliberately (as opposed to a bug).
    Carries an HTTP status code so the FastAPI handler in handlers.py can
    turn it into the right response without every route repeating that logic."""

    status_code = 500

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class UnauthorizedError(AppError):
    status_code = 401


class ForbiddenError(AppError):
    status_code = 403


class NotFoundError(AppError):
    status_code = 404


class BadRequestError(AppError):
    status_code = 400


class UpstreamServiceError(AppError):
    """A downstream API (Hugging Face, Groq, Supabase) failed or returned
    something we didn't expect."""

    status_code = 502
