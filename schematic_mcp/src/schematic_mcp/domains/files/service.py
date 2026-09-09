class FilesService:
    """Add use cases here; authorize data before calling backend."""
    def __init__(self, backend, authorizer):
        self.backend, self.authorizer = backend, authorizer
